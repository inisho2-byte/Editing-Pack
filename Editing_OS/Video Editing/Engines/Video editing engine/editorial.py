"""Deterministic editorial planning for word-timestamped footage.

This module is deliberately media-agnostic.  It turns verbatim, word-level ASR
into a reviewable EDL and timing manifests; ffmpeg execution remains in
``engine.py``.  The heuristics make conservative correctness decisions (dead
air, obvious filler, stutters and repeated takes) and expose lower-confidence
semantic decisions as review notes instead of silently deleting meaning.

The public contract is:

    plan = build_editorial_plan(words, source_id="main", source_path="in.mp4")
    report = validate_edl(plan["edl"], {"main": words})

All times in the EDL and handoff manifests are seconds.  Source times are never
mixed with output-timeline times.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "arete-editorial-plan/v2"
EDL_SCHEMA = "arete-edl/v1"
EPSILON = 1e-6

PLATFORM_PROFILES = {
    "reels": {"refresh_s": 2.6, "shot_s": 2.8, "pause_s": 0.16},
    "tiktok": {"refresh_s": 2.2, "shot_s": 2.5, "pause_s": 0.14},
    "shorts": {"refresh_s": 2.8, "shot_s": 3.0, "pause_s": 0.16},
    "x": {"refresh_s": 3.4, "shot_s": 3.8, "pause_s": 0.18},
    "youtube": {"refresh_s": 5.0, "shot_s": 5.5, "pause_s": 0.24},
    "documentary": {"refresh_s": 7.0, "shot_s": 7.0, "pause_s": 0.34},
}

PACING_MULTIPLIER = {
    "tight": 0.75,
    "adaptive": 1.0,
    "natural": 1.25,
    "cinematic": 1.65,
}

HARD_FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er"}
SOFT_FILLERS = {"basically", "literally", "honestly", "actually"}
FILLER_PHRASES = (("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of"))
PRESERVED_AUDIO_EVENTS = {
    "laugh", "laughs", "laughing", "applause", "sigh", "sighs", "music", "cheers"
}
WEAK_OPENINGS = {
    "hi", "hello", "hey", "okay", "so", "well", "today", "welcome", "basically"
}
POWER_WORDS = {
    "never", "secret", "mistake", "wrong", "truth", "why", "how", "fastest",
    "best", "worst", "only", "free", "stop", "without", "before", "after",
    "problem", "solution", "risk", "save", "lost", "gain", "proven", "exactly",
}
CONTRAST_WORDS = {"but", "however", "instead", "versus", "vs", "unlike", "although"}
CTA_WORDS = {"follow", "subscribe", "comment", "share", "download", "try", "start", "join"}
PROBLEM_WORDS = {"problem", "mistake", "waste", "fails", "failed", "hard", "stuck", "risk"}
SOLUTION_WORDS = {"solution", "fix", "fixed", "use", "build", "method", "system", "works"}
PROOF_WORDS = {"proof", "result", "results", "tested", "because", "percent", "%", "data"}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "his", "i", "if", "in", "is", "it", "its",
    "me", "my", "of", "on", "or", "our", "she", "so", "that", "the", "their", "them",
    "there", "they", "this", "to", "was", "we", "were", "with", "you", "your",
}


class EditorialError(ValueError):
    """Raised when transcript or EDL input violates a correctness contract."""


@dataclass(frozen=True)
class EditorialConfig:
    """Editorial policy.  Taste-sensitive values stay configurable.

    Padding is clamped to the ecosystem's verified 30-200ms window.  A shorter
    actual pad is allowed only when adjacent words leave no more room and is
    surfaced as a validation warning.
    """

    platform: str = "reels"
    pacing: str = "adaptive"
    cleanup_strength: str = "balanced"  # conservative | balanced | ruthless
    dead_air_threshold_s: float = 0.45
    breath_padding_before_s: float = 0.06
    breath_padding_after_s: float = 0.08
    hook_window_s: float = 3.0
    min_range_s: float = 0.08
    remove_fillers: bool = True
    remove_false_starts: bool = True
    remove_repeated_takes: bool = True
    preserve_audio_events: bool = True

    def checked(self) -> "EditorialConfig":
        if self.platform not in PLATFORM_PROFILES:
            raise EditorialError(f"unknown platform: {self.platform}")
        if self.pacing not in PACING_MULTIPLIER:
            raise EditorialError(f"unknown pacing: {self.pacing}")
        if self.cleanup_strength not in {"conservative", "balanced", "ruthless"}:
            raise EditorialError(f"unknown cleanup strength: {self.cleanup_strength}")
        if self.dead_air_threshold_s < 0.15:
            raise EditorialError("dead_air_threshold_s must be >= 0.15")
        for name, value in (
            ("breath_padding_before_s", self.breath_padding_before_s),
            ("breath_padding_after_s", self.breath_padding_after_s),
        ):
            if not 0.03 <= value <= 0.20:
                raise EditorialError(f"{name} must be between 0.03 and 0.20 seconds")
        if self.hook_window_s <= 0 or self.min_range_s <= 0:
            raise EditorialError("hook_window_s and min_range_s must be positive")
        return self

    @property
    def pause_target_s(self) -> float:
        profile = PLATFORM_PROFILES[self.platform]
        target = profile["pause_s"] * PACING_MULTIPLIER[self.pacing]
        return min(self.dead_air_threshold_s - 0.01, max(0.08, target))

    @property
    def visual_refresh_s(self) -> float:
        return PLATFORM_PROFILES[self.platform]["refresh_s"] * PACING_MULTIPLIER[self.pacing]

    @property
    def target_shot_s(self) -> float:
        return PLATFORM_PROFILES[self.platform]["shot_s"] * PACING_MULTIPLIER[self.pacing]


def _round(value: float) -> float:
    return round(float(value), 3)


def _union_duration(intervals: Iterable[tuple[float, float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted((float(start), float(end)) for start, end in intervals if end > start):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:10]}"


def _norm(text: str) -> str:
    return re.sub(r"[^\w%'-]", "", str(text).lower(), flags=re.UNICODE).strip("-'")


def _tokens(text: str) -> list[str]:
    return [token for token in (_norm(part) for part in str(text).split()) if token]


def _word_text(word: Mapping[str, Any]) -> str:
    return str(word.get("text", word.get("word", ""))).strip()


def normalize_words(words: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and copy ASR words into one canonical, monotonic shape."""

    normalized: list[dict[str, Any]] = []
    previous_start = -math.inf
    previous_end = -math.inf
    for index, raw in enumerate(words):
        text = _word_text(raw)
        if not text:
            continue
        try:
            start = float(raw["start"])
            end = float(raw["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EditorialError(f"word {index} needs numeric start/end") from exc
        if not (math.isfinite(start) and math.isfinite(end)):
            raise EditorialError(f"word {index} has non-finite timing")
        if start < 0 or end <= start:
            raise EditorialError(f"word {index} has invalid timing {start}-{end}")
        if start + EPSILON < previous_start:
            raise EditorialError(f"word {index} starts before the previous word")
        if start < previous_end - 0.08:
            raise EditorialError(
                f"word {index} overlaps the previous word by more than 80ms"
            )
        previous_start = start
        previous_end = end
        item = dict(raw)
        item.update({
            "text": text,
            "start": start,
            "end": end,
            "score": float(raw.get("score", raw.get("confidence", 1.0))),
            "index": index,
            "norm": _norm(text),
        })
        normalized.append(item)
    if not normalized:
        raise EditorialError("at least one timed word is required")
    return normalized


def _is_sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?…][\"')\]]*$", text))


def _is_clause_end(text: str) -> bool:
    return _is_sentence_end(text) or bool(re.search(r"[,;:—–][\"')\]]*$", text))


def _contains_audio_event(word: Mapping[str, Any]) -> bool:
    token = _norm(_word_text(word))
    raw = _word_text(word)
    return token in PRESERVED_AUDIO_EVENTS and bool(re.search(r"[\[({]", raw))


def _marks_intentional_pause(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Recognize explicit performance timing without pretending to infer emotion."""
    if left.get("preserve_pause_after") or right.get("preserve_pause_before"):
        return True
    left_text = _word_text(left).lower().strip()
    right_text = _word_text(right).lower().strip()
    if left_text.endswith(("...", "…")):
        return True
    markers = ("[beat]", "(beat)", "[pause]", "(pause)", "[silence]", "(silence)")
    return any(marker in left_text or marker in right_text for marker in markers)


def clause_spans(words: Sequence[Mapping[str, Any]], pause_break_s: float = 0.55) -> list[tuple[int, int]]:
    """Return inclusive word-index spans, split on meaning and natural pauses."""

    if not words:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    for index, word in enumerate(words):
        last = index == len(words) - 1
        pause = 0.0 if last else max(0.0, float(words[index + 1]["start"]) - float(word["end"]))
        if last or _is_clause_end(_word_text(word)) or pause >= pause_break_s:
            spans.append((start, index))
            start = index + 1
    if start < len(words):
        spans.append((start, len(words) - 1))
    return spans


def _span_text(words: Sequence[Mapping[str, Any]], start: int, end: int) -> str:
    return " ".join(_word_text(word) for word in words[start:end + 1]).strip()


def _issue(kind: str, words: Sequence[Mapping[str, Any]], start: int, end: int,
           confidence: float, action: str, reason: str, *, automatic: bool = False,
           source_start: float | None = None, source_end: float | None = None) -> dict[str, Any]:
    source_start = float(words[start]["start"]) if source_start is None else source_start
    source_end = float(words[end]["end"]) if source_end is None else source_end
    return {
        "id": _stable_id("decision", kind, start, end, _round(source_start), _round(source_end)),
        "kind": kind,
        "word_start_index": start,
        "word_end_index": end,
        "source_start": _round(source_start),
        "source_end": _round(source_end),
        "text": _span_text(words, start, end),
        "confidence": round(float(confidence), 2),
        "recommended_action": action,
        "automatic": bool(automatic),
        "reason": reason,
    }


def detect_dead_air(words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index in range(len(words) - 1):
        left, right = words[index], words[index + 1]
        gap = float(right["start"]) - float(left["end"])
        if gap + EPSILON < cfg.dead_air_threshold_s:
            continue
        preserve = _marks_intentional_pause(left, right) or (
            cfg.preserve_audio_events and (_contains_audio_event(left) or _contains_audio_event(right))
        )
        target = gap if preserve else min(gap, cfg.pause_target_s)
        action = "preserve" if preserve else "compress_pause"
        reason = (
            "Explicit performance, comedic, or emotional pause marker; preserve its timing."
            if preserve else
            f"Compress {gap:.2f}s of dead air to {target:.2f}s while retaining a breath."
        )
        item = _issue(
            "dead_air", words, index, index + 1, 0.99, action, reason,
            automatic=not preserve,
            source_start=float(left["end"]), source_end=float(right["start"]),
        )
        item.update({"gap_s": _round(gap), "keep_s": _round(target), "remove_s": _round(gap - target)})
        issues.append(item)
    return issues


def detect_fillers(words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    if not cfg.remove_fillers:
        return []
    norms = [str(word["norm"]) for word in words]
    issues: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for phrase in FILLER_PHRASES:
        width = len(phrase)
        for start in range(len(norms) - width + 1):
            if tuple(norms[start:start + width]) != phrase or any(i in claimed for i in range(start, start + width)):
                continue
            # These surface forms are genuinely ambiguous: "people you know",
            # "what I mean", and "this kind of tool" carry semantic payload.
            # Position is not evidence of discourse usage. Balanced and
            # conservative modes therefore keep every multiword phrase for
            # review; only explicitly ruthless cleanup authorizes broad removal.
            automatic = cfg.cleanup_strength == "ruthless"
            issues.append(_issue(
                "filler_phrase", words, start, start + width - 1, 0.90 if automatic else 0.65,
                "remove" if automatic else "review_remove",
                (
                    "Ruthless cleanup treats this ambiguous phrase as discourse filler; verify the claim survives."
                    if automatic else
                    "Ambiguous multiword phrase may be discourse filler or semantic content; human review is required."
                ),
                automatic=automatic,
            ))
            claimed.update(range(start, start + width))
    for index, token in enumerate(norms):
        if index in claimed:
            continue
        if token in HARD_FILLERS:
            issues.append(_issue(
                "filler", words, index, index, 0.99, "remove",
                "Non-lexical hesitation with no semantic payload.", automatic=True,
            ))
        elif token in SOFT_FILLERS and cfg.cleanup_strength != "conservative":
            automatic = cfg.cleanup_strength == "ruthless"
            issues.append(_issue(
                "soft_filler", words, index, index, 0.72, "remove" if automatic else "review_remove",
                "Potential intensifier/filler; verify tone before deleting.", automatic=automatic,
            ))
    return issues


def detect_false_starts(words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    if not cfg.remove_false_starts:
        return []
    norms = [str(word["norm"]) for word in words]
    issues: list[dict[str, Any]] = []
    claimed: set[int] = set()

    # Broken prefix followed by its completed word: "th- the".
    for index in range(len(words) - 1):
        raw = _word_text(words[index]).lower().strip()
        if raw.endswith("-") and norms[index] and norms[index + 1].startswith(norms[index]):
            issues.append(_issue(
                "stumble", words, index, index, 0.99, "remove",
                "Abandoned word fragment immediately followed by the completed word.", automatic=True,
            ))
            claimed.add(index)

    # Prefer the longest immediate repeated phrase, keeping the later delivery.
    index = 0
    while index < len(words) - 1:
        if index in claimed or not norms[index]:
            index += 1
            continue
        found: tuple[int, int, int] | None = None
        for width in range(min(6, (len(words) - index) // 2), 0, -1):
            second = index + width
            if norms[index:second] != norms[second:second + width]:
                continue
            gap = float(words[second]["start"]) - float(words[second - 1]["end"])
            if gap <= 1.5:
                found = (index, second - 1, width)
                break
        if found:
            start, end, width = found
            if not any(i in claimed for i in range(start, end + 1)):
                # A complete word repeated once or more can be deliberate
                # rhetoric ("very very", "no no no", "go go go"). Without a
                # broken-token marker or other explicit stutter evidence, the
                # default modes must not silently flatten that emphasis.
                # The longest-match search can represent a four-word emphasis
                # run as two repeated two-word spans ("no no" + "no no"). It
                # is still a single complete-word repetition, not a retake.
                emphatic_word_run = len(set(norms[start:start + width])) == 1
                automatic = (
                    (width > 1 and not emphatic_word_run)
                    or cfg.cleanup_strength == "ruthless"
                )
                issues.append(_issue(
                    "false_start", words, start, end,
                    0.98 if automatic else 0.62,
                    "remove" if automatic else "review_remove",
                    (
                        "Immediate repeated multiword take; keep the completed/later delivery."
                        if width > 1 and not emphatic_word_run else
                        "Exact complete-word repetition may be emphatic rhetoric; review before removing."
                    ),
                    automatic=automatic,
                ))
                claimed.update(range(start, end + 1))
            index += width * 2
        else:
            index += 1
    return issues


def _delivery_quality(words: Sequence[Mapping[str, Any]], span: tuple[int, int]) -> float:
    start, end = span
    selected = words[start:end + 1]
    confidence = sum(float(word.get("score", 1.0)) for word in selected) / max(1, len(selected))
    filler_penalty = sum(str(word["norm"]) in HARD_FILLERS for word in selected) * 0.08
    return confidence - filler_penalty


def detect_repetitions(words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    """Detect repeated takes and semantic redundancy.

    Only adjacent, near-verbatim clauses are safe automatic removals.  Similar
    but non-identical claims are emitted as review notes because a lexical
    metric cannot determine whether nuance is intentional.
    """

    spans = clause_spans(words)
    issues: list[dict[str, Any]] = []
    for left_index, left in enumerate(spans):
        left_tokens = _tokens(_span_text(words, *left))
        if len(left_tokens) < 3:
            continue
        for right_index in range(left_index + 1, min(len(spans), left_index + 4)):
            right = spans[right_index]
            right_tokens = _tokens(_span_text(words, *right))
            if len(right_tokens) < 3:
                continue
            sequence_similarity = SequenceMatcher(a=left_tokens, b=right_tokens, autojunk=False).ratio()
            left_content = {token for token in left_tokens if token not in STOP_WORDS}
            right_content = {token for token in right_tokens if token not in STOP_WORDS}
            containment = (
                len(left_content & right_content) / max(1, min(len(left_content), len(right_content)))
            )
            similarity = max(sequence_similarity, containment * 0.92)
            if similarity < 0.72:
                continue
            adjacent = right_index == left_index + 1
            time_gap = float(words[right[0]]["start"]) - float(words[left[1]]["end"])
            exactish = similarity >= 0.90
            automatic = cfg.remove_repeated_takes and adjacent and exactish and time_gap <= 2.0
            if automatic:
                left_quality = _delivery_quality(words, left)
                right_quality = _delivery_quality(words, right)
                # Later takes win ties because speakers usually restart to improve.
                remove_span = left if left_quality <= right_quality + 0.02 else right
                keep_span = right if remove_span == left else left
                item = _issue(
                    "repeated_take", words, *remove_span, min(0.99, similarity), "remove",
                    "Adjacent near-verbatim take; preserve the stronger delivery and remove duplicate work.",
                    automatic=True,
                )
                item.update({
                    "similarity": round(similarity, 3),
                    "kept_word_start_index": keep_span[0],
                    "kept_word_end_index": keep_span[1],
                })
                issues.append(item)
            else:
                item = _issue(
                    "semantic_repetition", words, *right, similarity, "review_remove",
                    "This clause substantially overlaps an earlier idea; confirm that it adds nuance before keeping it.",
                    automatic=False,
                )
                item.update({
                    "similarity": round(similarity, 3),
                    "compared_word_start_index": left[0],
                    "compared_word_end_index": left[1],
                })
                issues.append(item)
    # An exact adjacent repeated take can be rediscovered by another comparison.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for issue in issues:
        key = (issue["kind"], issue["word_start_index"], issue["word_end_index"])
        unique[key] = issue
    return list(unique.values())


def score_clauses(words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    """Explainable hook/retention triage, not a substitute for semantic review."""

    results: list[dict[str, Any]] = []
    seen_content: set[str] = set()
    for order, (start, end) in enumerate(clause_spans(words)):
        text = _span_text(words, start, end)
        tokens = [str(word["norm"]) for word in words[start:end + 1] if word["norm"]]
        content = {token for token in tokens if token not in STOP_WORDS and len(token) > 2}
        duration = max(EPSILON, float(words[end]["end"]) - float(words[start]["start"]))
        position = float(words[start]["start"]) - float(words[0]["start"])

        hook = 35.0
        hook_reasons: list[str] = []
        if position <= cfg.hook_window_s:
            hook += 18
            hook_reasons.append("lands inside the opening hook window")
        elif position <= cfg.hook_window_s * 2:
            hook += 8
        if "?" in text:
            hook += 9
            hook_reasons.append("creates a direct question")
        if any(re.search(r"\d", token) for token in tokens):
            hook += 8
            hook_reasons.append("uses a concrete number")
        power_hits = content & POWER_WORDS
        if power_hits:
            hook += min(12, 4 * len(power_hits))
            hook_reasons.append("contains stakes/curiosity language")
        if "you" in tokens or "your" in tokens:
            hook += 5
            hook_reasons.append("addresses the viewer")
        if tokens and tokens[0] in WEAK_OPENINGS and not (power_hits or "?" in text):
            hook -= 14
            hook_reasons.append("opens with generic throat-clearing")
        if duration > 5.0:
            hook -= min(14, (duration - 5.0) * 3)
            hook_reasons.append("takes too long to resolve for a hook")
        filler_ratio = sum(token in HARD_FILLERS for token in tokens) / max(1, len(tokens))
        hook -= filler_ratio * 35

        overlap = (len(content & seen_content) / max(1, len(content))) if content else 1.0
        novelty = 1.0 - overlap
        density = len(content) / duration
        retention = 38.0 + min(18, density * 7) + novelty * 18
        retention_reasons = [f"{density:.1f} content words/second", f"{novelty:.0%} lexical novelty"]
        if content & (POWER_WORDS | CONTRAST_WORDS):
            retention += 8
            retention_reasons.append("contains contrast or stakes")
        if any(re.search(r"\d", token) for token in tokens):
            retention += 5
            retention_reasons.append("concrete detail improves specificity")
        if duration > 8:
            retention -= 12
            retention_reasons.append("long unbroken thought needs a visual refresh")
        if overlap > 0.65 and order > 0:
            retention -= 14
            retention_reasons.append("repeats vocabulary from earlier clauses")

        seen_content.update(content)
        hook_score = int(round(max(0, min(100, hook))))
        retention_score = int(round(max(0, min(100, retention))))
        results.append({
            "id": _stable_id("clause", start, end, text),
            "order": order,
            "word_start_index": start,
            "word_end_index": end,
            "source_start": _round(float(words[start]["start"])),
            "source_end": _round(float(words[end]["end"])),
            "duration_s": _round(duration),
            "text": text,
            "hook_score": hook_score,
            "hook_tier": "strong" if hook_score >= 70 else "workable" if hook_score >= 50 else "weak",
            "hook_reasons": hook_reasons or ["clear statement without a distinct curiosity device"],
            "retention_score": retention_score,
            "retention_tier": "strong" if retention_score >= 70 else "workable" if retention_score >= 50 else "weak",
            "retention_reasons": retention_reasons,
        })
    return results


def classify_beat(text: str, order: int, start_s: float, cfg: EditorialConfig) -> str:
    tokens = set(_tokens(text))
    if start_s <= cfg.hook_window_s or order == 0:
        return "HOOK"
    if tokens & CTA_WORDS:
        return "CTA"
    if tokens & PROBLEM_WORDS:
        return "PROBLEM"
    if tokens & PROOF_WORDS or any(re.search(r"\d", token) for token in tokens):
        return "PROOF"
    if tokens & SOLUTION_WORDS:
        return "SOLUTION"
    return "VALUE"


def _automatic_removal_indices(issues: Sequence[Mapping[str, Any]]) -> tuple[set[int], dict[int, list[str]]]:
    removed: set[int] = set()
    issue_ids: dict[int, list[str]] = {}
    for issue in issues:
        if not issue.get("automatic") or issue.get("recommended_action") != "remove":
            continue
        for index in range(int(issue["word_start_index"]), int(issue["word_end_index"]) + 1):
            removed.add(index)
            issue_ids.setdefault(index, []).append(str(issue["id"]))
    return removed, issue_ids


def _dead_air_by_boundary(issues: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {
        int(issue["word_start_index"]): issue
        for issue in issues
        if issue.get("kind") == "dead_air" and issue.get("automatic")
    }


def _build_ranges(words: Sequence[Mapping[str, Any]], issues: Sequence[Mapping[str, Any]],
                  source_id: str, grade: str, cfg: EditorialConfig,
                  source_duration_s: float | None = None) -> list[dict[str, Any]]:
    removed, issue_ids = _automatic_removal_indices(issues)
    dead_boundaries = _dead_air_by_boundary(issues)
    kept = [index for index in range(len(words)) if index not in removed]
    if not kept:
        raise EditorialError("cleanup would remove every word; no EDL can be built")

    runs: list[tuple[int, int, str | None]] = []
    run_start = kept[0]
    previous = kept[0]
    boundary_reason: str | None = None
    for index in kept[1:]:
        split = index != previous + 1 or previous in dead_boundaries
        if split:
            reason = str(dead_boundaries[previous]["id"]) if previous in dead_boundaries else None
            runs.append((run_start, previous, reason))
            run_start = index
            boundary_reason = reason
        previous = index
    runs.append((run_start, previous, boundary_reason))

    ranges: list[dict[str, Any]] = []
    for run_index, (start_index, end_index, _) in enumerate(runs):
        first, last = words[start_index], words[end_index]
        source_start = max(0.0, float(first["start"]) - cfg.breath_padding_before_s)
        source_end = float(last["end"]) + cfg.breath_padding_after_s
        if source_duration_s is not None:
            source_end = min(float(source_duration_s), source_end)

        preceding_issue_ids: list[str] = []
        following_issue_ids: list[str] = []

        if start_index > 0:
            if start_index - 1 in removed:
                source_start = max(source_start, float(words[start_index - 1]["end"]))
                preceding_issue_ids.extend(issue_ids.get(start_index - 1, []))
            elif start_index - 1 in dead_boundaries:
                pause = float(dead_boundaries[start_index - 1]["keep_s"])
                source_start = max(float(words[start_index - 1]["end"]), float(first["start"]) - pause / 2)
                preceding_issue_ids.append(str(dead_boundaries[start_index - 1]["id"]))

        if end_index + 1 < len(words):
            if end_index + 1 in removed:
                source_end = min(source_end, float(words[end_index + 1]["start"]))
                following_issue_ids.extend(issue_ids.get(end_index + 1, []))
            elif end_index in dead_boundaries:
                pause = float(dead_boundaries[end_index]["keep_s"])
                source_end = min(float(words[end_index + 1]["start"]), float(last["end"]) + pause / 2)
                following_issue_ids.append(str(dead_boundaries[end_index]["id"]))

        # Adjacent removed runs can constrain padding to zero, but an edge still
        # lands exactly on a word boundary and never inside a spoken word.
        source_start = min(source_start, float(first["start"]))
        source_end = max(source_end, float(last["end"]))
        if source_end - source_start < cfg.min_range_s:
            raise EditorialError(f"planned range {run_index} is too short to render safely")

        text = _span_text(words, start_index, end_index)
        decision_ids = sorted(set(preceding_issue_ids + following_issue_ids))
        start_rel = float(first["start"]) - float(words[0]["start"])
        item = {
            "id": _stable_id("range", source_id, start_index, end_index, _round(source_start), _round(source_end)),
            "source": source_id,
            "start": _round(source_start),
            "end": _round(source_end),
            "grade": grade,
            "beat": classify_beat(text, run_index, start_rel, cfg),
            "quote": text,
            "reason": "Keep semantic content; boundary tightened at verified word/pause edges.",
            "word_boundary_start": _word_text(first),
            "word_boundary_end": _word_text(last),
            "word_start_index": start_index,
            "word_end_index": end_index,
            "word_start_s": _round(float(first["start"])),
            "word_end_s": _round(float(last["end"])),
            "pad_in_s": _round(float(first["start"]) - source_start),
            "pad_out_s": _round(source_end - float(last["end"])),
            "decision_ids": decision_ids,
        }
        ranges.append(item)
    return ranges


def retime_words(words: Sequence[Mapping[str, Any]], ranges: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map kept source words onto the concatenated output timeline."""

    output: list[dict[str, Any]] = []
    offset = 0.0
    for range_item in ranges:
        start_index = int(range_item["word_start_index"])
        end_index = int(range_item["word_end_index"])
        source_start = float(range_item["start"])
        for index in range(start_index, end_index + 1):
            word = dict(words[index])
            word.update({
                "source_start": _round(float(word["start"])),
                "source_end": _round(float(word["end"])),
                "start": _round(offset + float(word["start"]) - source_start),
                "end": _round(offset + float(word["end"]) - source_start),
                "source_word_index": index,
            })
            output.append(word)
        offset += float(range_item["end"]) - source_start
    return output


def build_timeline_map(ranges: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Emit the source-to-output mapping shared by captions and graphics."""
    mapping: list[dict[str, Any]] = []
    output_start = 0.0
    for item in ranges:
        duration = float(item["end"]) - float(item["start"])
        mapping.append({
            "range_id": item["id"],
            "source": item["source"],
            "source_start": _round(item["start"]),
            "source_end": _round(item["end"]),
            "output_start": _round(output_start),
            "output_end": _round(output_start + duration),
            "source_to_output_offset": _round(output_start - float(item["start"])),
            "word_start_index": item["word_start_index"],
            "word_end_index": item["word_end_index"],
        })
        output_start += duration
    return mapping


def _output_clauses(output_words: Sequence[Mapping[str, Any]], cfg: EditorialConfig) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    for order, (start, end) in enumerate(clause_spans(output_words)):
        text = _span_text(output_words, start, end)
        item = {
            "id": _stable_id("output_clause", order, text, output_words[start]["start"]),
            "order": order,
            "start": _round(float(output_words[start]["start"])),
            "end": _round(float(output_words[end]["end"])),
            "text": text,
            "beat": classify_beat(text, order, float(output_words[start]["start"]), cfg),
            "word_start_index": start,
            "word_end_index": end,
        }
        clauses.append(item)
    return clauses


def _emphasis_words(text: str, limit: int = 3) -> list[str]:
    candidates = []
    for raw in text.split():
        token = _norm(raw)
        if not token or token in STOP_WORDS:
            continue
        score = (12 if token in POWER_WORDS else 0) + (10 if re.search(r"\d", token) else 0) + len(token)
        candidates.append((score, raw.strip(".,!?;:")))
    candidates.sort(key=lambda pair: (-pair[0], pair[1].lower()))
    return [word for _, word in candidates[:limit]]


def _caption_handoff(clauses: Sequence[Mapping[str, Any]], total_duration: float) -> dict[str, Any]:
    cues = []
    for clause in clauses:
        cues.append({
            "id": _stable_id("caption_cue", clause["id"]),
            "start_in_output": clause["start"],
            "end_in_output": clause["end"],
            "text": clause["text"],
            "beat": clause["beat"],
            "emphasis_words": _emphasis_words(str(clause["text"])),
            "instruction": "Phrase as one idea; word timing comes from retimed_words, never estimated characters.",
        })
    return {
        "schema": "arete-caption-handoff/v1",
        "timing_basis": "output_timeline_seconds",
        "duration_s": _round(total_duration),
        "source_of_truth": "retimed_words",
        "cues": cues,
    }


def _graphic_type(text: str) -> tuple[str, str] | None:
    tokens = set(_tokens(text))
    if any(re.search(r"\d", token) for token in tokens):
        return "stat_or_number", "Make the number the information hierarchy; show its unit and context."
    if tokens & CONTRAST_WORDS:
        return "comparison", "Show the contrast spatially; do not duplicate the full sentence."
    if tokens & {"first", "second", "third", "step", "steps"}:
        return "process_steps", "Reveal one step at a time in spoken order."
    if tokens & {"means", "defined", "definition"}:
        return "definition_callout", "Clarify the term with one concise label or diagram."
    if tokens & {"because", "therefore", "causes", "works"}:
        return "mechanism_diagram", "Visualize the cause-and-effect mechanism, not decoration."
    return None


def _graphics_handoff(clauses: Sequence[Mapping[str, Any]], total_duration: float,
                      cfg: EditorialConfig) -> dict[str, Any]:
    cues: list[dict[str, Any]] = []
    last_refresh = -math.inf
    for clause in clauses:
        start = float(clause["start"])
        end = float(clause["end"])
        text = str(clause["text"])
        graphic = _graphic_type(text)
        overdue = start - last_refresh >= cfg.visual_refresh_s
        is_hook = clause["beat"] == "HOOK" and start <= cfg.hook_window_s
        if graphic:
            cue_type, instruction = graphic
            priority = "high" if is_hook else "medium"
        elif is_hook:
            cue_type, instruction, priority = (
                "hook_support",
                "Support the spoken promise with one concrete visual; keep the speaker or proof dominant.",
                "high",
            )
        elif overdue:
            cue_type, instruction, priority = (
                "visual_refresh",
                "Introduce a motivated B-roll, reframing, or graphic change tied to this idea.",
                "medium",
            )
        else:
            continue
        duration = min(max(1.2, end - start), max(1.2, cfg.visual_refresh_s * 1.4))
        cue = {
            "id": _stable_id("graphic_cue", clause["id"], cue_type),
            "type": cue_type,
            "priority": priority,
            "start_in_output": _round(start),
            "duration": _round(min(duration, total_duration - start)),
            "anchor_text": text,
            "emphasis_words": _emphasis_words(text, limit=2),
            "instruction": instruction,
            "guardrails": [
                "clarify rather than restate",
                "one focal idea",
                "no generic template motion",
                "caption-safe composition",
            ],
        }
        cues.append(cue)
        last_refresh = start
    return {
        "schema": "arete-graphics-handoff/v1",
        "timing_basis": "output_timeline_seconds",
        "duration_s": _round(total_duration),
        "target_visual_refresh_s": _round(cfg.visual_refresh_s),
        "cues": cues,
    }


def _shot_treatment(text: str, beat: str, duration: float, cfg: EditorialConfig) -> str:
    graphic = _graphic_type(text)
    if graphic:
        return "graphic_takeover" if duration >= 2.0 else "graphic_overlay"
    if beat in {"HOOK", "CTA"}:
        return "speaker_full"
    if duration > cfg.target_shot_s * 1.6:
        return "b_roll_or_diagram_window"
    if set(_tokens(text)) & POWER_WORDS:
        return "restrained_emphasis_reframe"
    return "speaker_hold"


def _rhythm_plan(clauses: Sequence[Mapping[str, Any]], total_duration: float,
                 cfg: EditorialConfig) -> dict[str, Any]:
    shots: list[dict[str, Any]] = []
    durations: list[float] = []
    for clause in clauses:
        duration = max(0.0, float(clause["end"]) - float(clause["start"]))
        durations.append(duration)
        shots.append({
            "id": _stable_id("shot", clause["id"]),
            "start_in_output": clause["start"],
            "end_in_output": clause["end"],
            "duration_s": _round(duration),
            "beat": clause["beat"],
            "treatment": _shot_treatment(str(clause["text"]), str(clause["beat"]), duration, cfg),
            "cut_rule": "Meaning boundary first; beat alignment may only nudge within silence.",
            "visual_refresh_due": duration > cfg.visual_refresh_s,
        })
    variation = 0.0
    if len(durations) > 1:
        mean = sum(durations) / len(durations)
        variation = (sum((item - mean) ** 2 for item in durations) / len(durations)) ** 0.5
    hook_end = min(total_duration, max(cfg.hook_window_s, total_duration * 0.12))
    peak_start = max(hook_end, total_duration * 0.72)
    peak_end = max(peak_start, total_duration * 0.90)
    phases = [
        {"name": "hook", "start": 0.0, "end": _round(hook_end), "pace": "tight"},
        {"name": "build", "start": _round(hook_end), "end": _round(peak_start), "pace": "varied"},
        {"name": "peak", "start": _round(peak_start), "end": _round(peak_end), "pace": "accelerate"},
        {"name": "release", "start": _round(peak_end), "end": _round(total_duration), "pace": "breathe"},
    ]
    phases = [phase for phase in phases if phase["end"] - phase["start"] > 0.05]
    return {
        "schema": "arete-rhythm-plan/v1",
        "timing_basis": "output_timeline_seconds",
        "target_shot_s": _round(cfg.target_shot_s),
        "target_visual_refresh_s": _round(cfg.visual_refresh_s),
        "duration_variation_s": _round(variation),
        "macro_shape": "tight hook -> varied build -> accelerate into peak -> release",
        "phases": phases,
        "shots": shots,
    }


def build_qa_plan(edl: Mapping[str, Any]) -> dict[str, Any]:
    total = float(edl.get("total_duration_s", 0.0))
    boundaries = []
    offset = 0.0
    ranges = list(edl.get("ranges", []))
    for index, range_item in enumerate(ranges[:-1]):
        offset += float(range_item["end"]) - float(range_item["start"])
        boundaries.append({
            "cut_index": index,
            "at_output_s": _round(offset),
            "inspect_start_s": _round(max(0.0, offset - 1.5)),
            "inspect_end_s": _round(min(total, offset + 1.5)),
            "checks": ["visual discontinuity", "audio pop", "caption continuity", "overlay timing"],
        })
    samples = {0.0, max(0.0, total - 2.0)}
    if total > 4:
        samples.update({total * 0.25, total * 0.5, total * 0.75})
    return {
        "schema": "arete-qa-plan/v1",
        "review_order": ["story", "retention", "emotion", "captions", "motion", "audio", "color", "platform", "export"],
        "cut_windows": boundaries,
        "sample_times_s": [_round(value) for value in sorted(samples)],
        "mandatory_checks": [
            "all EDL edges land outside spoken words",
            "duration matches EDL within 0.25s",
            "30ms audio fades prevent boundary pops",
            "captions use output-timeline word offsets",
            "voice-activated caption words land within one output frame of speech",
            "graphics never obscure captions",
            "graphic labels and diagrams remain legible at 50% linear scale",
            "semantic graphic items reveal on their exact retimed-word anchors",
            "3D depth and PiP layering preserve the focal message without occlusion",
            "grade, background, graphics palette, and skin tones form one coherent visual world",
            "first and last frames are intentional",
            "encoded output contains the expected video and dialogue streams",
            "actual export is reviewed, not only the source timeline",
        ],
        "max_self_eval_passes": 3,
    }


def build_editorial_plan(words: Sequence[Mapping[str, Any]], *, source_id: str = "main",
                         source_path: str = "input.mp4", project_id: str | None = None,
                         grade: str = "subtle", config: EditorialConfig | None = None,
                         source_duration_s: float | None = None) -> dict[str, Any]:
    """Analyze a transcript and build one deterministic, reviewable EDL."""

    cfg = (config or EditorialConfig()).checked()
    normalized = normalize_words(words)
    dead_air = detect_dead_air(normalized, cfg)
    fillers = detect_fillers(normalized, cfg)
    false_starts = detect_false_starts(normalized, cfg)
    repetitions = detect_repetitions(normalized, cfg)
    false_start_indices = {
        index
        for issue in false_starts
        if issue.get("automatic")
        for index in range(int(issue["word_start_index"]), int(issue["word_end_index"]) + 1)
    }
    # The n-gram stumble detector already resolves immediate verbatim restarts.
    # Do not let the clause-level repetition pass independently delete the
    # surviving delivery of the same restart.
    repetitions = [
        issue for issue in repetitions
        if not (
            issue.get("automatic")
            and (
                any(index in false_start_indices for index in range(
                    int(issue["word_start_index"]), int(issue["word_end_index"]) + 1
                ))
                or any(index in false_start_indices for index in range(
                    int(issue.get("kept_word_start_index", -1)),
                    int(issue.get("kept_word_end_index", -2)) + 1,
                ))
            )
        )
    ]
    issues = sorted(
        dead_air + fillers + false_starts + repetitions,
        key=lambda item: (float(item["source_start"]), float(item["source_end"]), str(item["kind"])),
    )
    ranges = _build_ranges(
        normalized, issues, source_id, grade, cfg,
        source_duration_s=source_duration_s,
    )
    total_duration = sum(float(item["end"]) - float(item["start"]) for item in ranges)
    output_words = retime_words(normalized, ranges)
    output_clauses = _output_clauses(output_words, cfg)
    scores = score_clauses(normalized, cfg)
    source_duration = float(normalized[-1]["end"]) - float(normalized[0]["start"])

    edl: dict[str, Any] = {
        "schema": EDL_SCHEMA,
        "version": 1,
        "project_id": project_id or _stable_id("project", source_id, source_path),
        "sources": {source_id: str(source_path)},
        "ranges": ranges,
        "grade": grade,
        "overlays": [],
        "total_duration_s": _round(total_duration),
        "loudnorm": {"target_lufs": -14, "target_dbtp": -1, "lra": 11},
        "editorial": {
            "schema": SCHEMA,
            "timing_basis": "source_seconds_for_ranges; output_seconds_for_handoffs",
            "config": asdict(cfg),
            "source_words": [
                {
                    "text": word["text"],
                    "start": _round(word["start"]),
                    "end": _round(word["end"]),
                    "score": round(float(word.get("score", 1.0)), 4),
                }
                for word in normalized
            ],
            "timeline_map": build_timeline_map(ranges),
            "decisions": issues,
            "retimed_words": output_words,
            "handoffs": {
                "captions": _caption_handoff(output_clauses, total_duration),
                "graphics": _graphics_handoff(output_clauses, total_duration, cfg),
            },
            "rhythm_plan": _rhythm_plan(output_clauses, total_duration, cfg),
        },
    }
    edl["editorial"]["qa_plan"] = build_qa_plan(edl)
    validation = validate_edl(edl, {source_id: normalized})
    edl["editorial"]["validation"] = validation

    auto_removed = [item for item in issues if item.get("automatic") and item.get("recommended_action") == "remove"]
    pause_saved = sum(float(item.get("remove_s", 0.0)) for item in dead_air)
    word_saved = _union_duration(
        (float(item["source_start"]), float(item["source_end"]))
        for item in auto_removed
    )
    best_hooks = sorted(scores, key=lambda item: (-int(item["hook_score"]), int(item["order"])))[:3]
    opening_score = scores[0]["hook_score"] if scores else 0
    review_required = [item for item in issues if not item.get("automatic")]
    if best_hooks and best_hooks[0]["order"] != 0 and int(best_hooks[0]["hook_score"]) >= int(opening_score) + 12:
        review_required.append({
            "id": _stable_id("review", "hook", best_hooks[0]["id"]),
            "kind": "hook_opportunity",
            "recommended_action": "review_restructure",
            "automatic": False,
            "reason": "A later clause scores materially stronger than the current opening; verify context before promoting it.",
            "candidate_clause_id": best_hooks[0]["id"],
        })

    return {
        "schema": SCHEMA,
        "config": asdict(cfg),
        "analysis": {
            "source_word_count": len(normalized),
            "kept_word_count": len(output_words),
            "source_spoken_span_s": _round(source_duration),
            "planned_duration_s": _round(total_duration),
            "estimated_time_removed_s": _round(max(0.0, pause_saved + word_saved)),
            "issues": issues,
            "sentence_scores": scores,
            "hook_candidates": best_hooks,
            "review_required": review_required,
        },
        "edl": edl,
        "validation": validation,
    }


def _edge_inside_word(edge: float, words: Sequence[Mapping[str, Any]], tolerance: float = 0.002) -> Mapping[str, Any] | None:
    for word in words:
        if float(word["start"]) + tolerance < edge < float(word["end"]) - tolerance:
            return word
    return None


def validate_edl(edl: Mapping[str, Any], words_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                 *, duration_tolerance_s: float = 0.01) -> dict[str, Any]:
    """Validate renderer compatibility, timeline math, and semantic cut safety."""

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def error(code: str, message: str, **context: Any) -> None:
        errors.append({"code": code, "message": message, **context})

    def warning(code: str, message: str, **context: Any) -> None:
        warnings.append({"code": code, "message": message, **context})

    if edl.get("version") != 1:
        error("version", "EDL version must be 1")
    sources = edl.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        error("sources", "EDL needs a non-empty sources mapping")
        sources = {}
    ranges = edl.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        error("ranges", "EDL needs at least one range")
        ranges = []

    normalized_sources: dict[str, list[dict[str, Any]]] = {}
    if words_by_source:
        for source, words in words_by_source.items():
            try:
                normalized_sources[source] = normalize_words(words)
            except EditorialError as exc:
                error("transcript", str(exc), source=source)

    computed_duration = 0.0
    ids: set[str] = set()
    for index, item in enumerate(ranges):
        source = item.get("source")
        if source not in sources:
            error("unknown_source", f"range {index} references unknown source {source!r}", range_index=index)
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            error("range_time", f"range {index} needs numeric start/end", range_index=index)
            continue
        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start:
            error("range_time", f"range {index} has invalid interval {start}-{end}", range_index=index)
            continue
        computed_duration += end - start
        range_id = item.get("id")
        if range_id:
            if range_id in ids:
                error("duplicate_id", f"duplicate range id {range_id}", range_index=index)
            ids.add(str(range_id))

        if source in normalized_sources:
            words = normalized_sources[str(source)]
            for edge_name, edge in (("start", start), ("end", end)):
                hit = _edge_inside_word(edge, words)
                if hit:
                    error(
                        "cut_inside_word",
                        f"range {index} {edge_name} edge {edge:.3f}s cuts inside {_word_text(hit)!r}",
                        range_index=index, edge=edge_name, word_index=hit["index"],
                    )
            try:
                word_start_index = int(item["word_start_index"])
                word_end_index = int(item["word_end_index"])
                if not 0 <= word_start_index <= word_end_index < len(words):
                    raise IndexError
                first, last = words[word_start_index], words[word_end_index]
                if start > float(first["start"]) + EPSILON or end < float(last["end"]) - EPSILON:
                    error("word_not_contained", f"range {index} does not contain its declared boundary words", range_index=index)
                if item.get("word_boundary_start") != _word_text(first) or item.get("word_boundary_end") != _word_text(last):
                    error("word_label_mismatch", f"range {index} boundary labels do not match transcript", range_index=index)
                for pad_name in ("pad_in_s", "pad_out_s"):
                    pad = float(item.get(pad_name, 0.0))
                    if pad < 0.03 - EPSILON:
                        warning(
                            "constrained_padding",
                            f"range {index} {pad_name} is {pad:.3f}s; adjacent speech constrained the 30ms target",
                            range_index=index, edge=pad_name,
                        )
                    elif pad > 0.20 + EPSILON:
                        error("excess_padding", f"range {index} {pad_name} exceeds 200ms", range_index=index)
            except (KeyError, TypeError, ValueError, IndexError):
                error("word_boundary_metadata", f"range {index} has invalid word-boundary metadata", range_index=index)

    try:
        declared_duration = float(edl.get("total_duration_s"))
        if abs(declared_duration - computed_duration) > duration_tolerance_s:
            error(
                "duration_mismatch",
                f"declared duration {declared_duration:.3f}s != range sum {computed_duration:.3f}s",
                declared=_round(declared_duration), computed=_round(computed_duration),
            )
    except (TypeError, ValueError):
        error("duration", "total_duration_s must be numeric")
        declared_duration = computed_duration

    for index, overlay in enumerate(edl.get("overlays", [])):
        try:
            start = float(overlay["start_in_output"])
            duration = float(overlay["duration"])
            if start < 0 or duration <= 0 or start + duration > declared_duration + 0.02:
                error("overlay_bounds", f"overlay {index} falls outside the output timeline", overlay_index=index)
        except (KeyError, TypeError, ValueError):
            error("overlay_time", f"overlay {index} needs numeric start_in_output/duration", overlay_index=index)

    editorial = edl.get("editorial", {})
    if isinstance(editorial, Mapping):
        timeline_map = editorial.get("timeline_map", [])
        if timeline_map:
            if not isinstance(timeline_map, list) or len(timeline_map) != len(ranges):
                error("timeline_map", "timeline_map must contain exactly one entry per range")
            else:
                output_offset = 0.0
                for index, (mapping, range_item) in enumerate(zip(timeline_map, ranges)):
                    try:
                        expected_end = output_offset + float(range_item["end"]) - float(range_item["start"])
                        matches = (
                            mapping.get("range_id") == range_item.get("id")
                            and mapping.get("source") == range_item.get("source")
                            and abs(float(mapping["source_start"]) - float(range_item["start"])) <= 0.002
                            and abs(float(mapping["source_end"]) - float(range_item["end"])) <= 0.002
                            and abs(float(mapping["output_start"]) - output_offset) <= 0.002
                            and abs(float(mapping["output_end"]) - expected_end) <= 0.002
                        )
                        if not matches:
                            error("timeline_map", f"timeline_map entry {index} does not match its range", map_index=index)
                        output_offset = expected_end
                    except (KeyError, TypeError, ValueError):
                        error("timeline_map", f"timeline_map entry {index} has invalid timing", map_index=index)

        retimed_words = editorial.get("retimed_words", [])
        if retimed_words:
            previous_start = -math.inf
            for index, word in enumerate(retimed_words):
                try:
                    start = float(word["start"])
                    end = float(word["end"])
                    if start + EPSILON < previous_start or start < -EPSILON or end <= start or end > declared_duration + 0.02:
                        error("retimed_words", f"retimed word {index} is outside or non-monotonic on the output timeline", word_index=index)
                    previous_start = start
                except (KeyError, TypeError, ValueError):
                    error("retimed_words", f"retimed word {index} has invalid timing", word_index=index)

        # Monotonic timing alone does not prove the handoff came from this EDL.
        # Reconstruct every expected word directly from source evidence+ranges,
        # then compare identity and both clocks field-by-field.  This prevents a
        # stale/tampered transcript from driving captions or graphics after cuts.
        if normalized_sources and ranges:
            expected_retimed: list[dict[str, Any]] = []
            output_offset = 0.0
            reconstruction_possible = True
            for range_index, range_item in enumerate(ranges):
                source = str(range_item.get("source"))
                source_words = normalized_sources.get(source)
                try:
                    start_index = int(range_item["word_start_index"])
                    end_index = int(range_item["word_end_index"])
                    source_start = float(range_item["start"])
                    source_end = float(range_item["end"])
                    if source_words is None or not 0 <= start_index <= end_index < len(source_words):
                        raise IndexError
                except (KeyError, TypeError, ValueError, IndexError):
                    reconstruction_possible = False
                    break
                for source_word_index in range(start_index, end_index + 1):
                    source_word = source_words[source_word_index]
                    expected_retimed.append({
                        "text": _word_text(source_word),
                        "source_start": _round(float(source_word["start"])),
                        "source_end": _round(float(source_word["end"])),
                        "start": _round(
                            output_offset + float(source_word["start"]) - source_start
                        ),
                        "end": _round(
                            output_offset + float(source_word["end"]) - source_start
                        ),
                        "source_word_index": source_word_index,
                    })
                output_offset += source_end - source_start

            if reconstruction_possible:
                if not isinstance(retimed_words, list) or len(retimed_words) != len(expected_retimed):
                    error(
                        "retimed_words",
                        "retimed_words does not contain exactly the words selected by the EDL ranges",
                        declared_count=(len(retimed_words) if isinstance(retimed_words, list) else None),
                        expected_count=len(expected_retimed),
                    )
                else:
                    for index, (actual, expected) in enumerate(zip(retimed_words, expected_retimed)):
                        try:
                            matches = (
                                _word_text(actual) == expected["text"]
                                and int(actual["source_word_index"]) == expected["source_word_index"]
                                and abs(float(actual["source_start"]) - expected["source_start"]) <= 0.002
                                and abs(float(actual["source_end"]) - expected["source_end"]) <= 0.002
                                and abs(float(actual["start"]) - expected["start"]) <= 0.002
                                and abs(float(actual["end"]) - expected["end"]) <= 0.002
                            )
                        except (KeyError, TypeError, ValueError):
                            matches = False
                        if not matches:
                            error(
                                "retimed_words",
                                f"retimed word {index} does not match source_words+ranges reconstruction",
                                word_index=index,
                            )

        handoffs = editorial.get("handoffs", {})
        if isinstance(handoffs, Mapping):
            for kind, handoff in handoffs.items():
                if not isinstance(handoff, Mapping):
                    continue
                for index, cue in enumerate(handoff.get("cues", [])):
                    try:
                        start = float(cue["start_in_output"])
                        duration = (
                            float(cue["duration"]) if "duration" in cue
                            else float(cue["end_in_output"]) - start
                        )
                        if start < -EPSILON or duration < -EPSILON or start + duration > declared_duration + 0.02:
                            error("cue_bounds", f"{kind} cue {index} falls outside the output timeline", cue_kind=kind, cue_index=index)
                    except (KeyError, TypeError, ValueError):
                        error("cue_time", f"{kind} cue {index} has invalid timing", cue_kind=kind, cue_index=index)

    checks = {
        "schema": not any(item["code"] in {"version", "sources", "ranges"} for item in errors),
        "range_math": not any(item["code"] in {"range_time", "duration", "duration_mismatch"} for item in errors),
        "word_safe_edges": not any(item["code"] in {"cut_inside_word", "word_not_contained", "word_label_mismatch", "word_boundary_metadata"} for item in errors),
        "timeline_bounds": not any(item["code"] in {"overlay_bounds", "overlay_time", "cue_bounds", "cue_time"} for item in errors),
        "retiming_contract": not any(item["code"] in {"timeline_map", "retimed_words"} for item in errors),
        "deterministic_ids": not any(item["code"] == "duplicate_id" for item in errors),
    }
    return {
        "schema": "arete-edl-validation/v1",
        "valid": not errors,
        "computed_duration_s": _round(computed_duration),
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def assert_edl_valid(edl: Mapping[str, Any], words_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    report = validate_edl(edl, words_by_source)
    if not report["valid"]:
        detail = "; ".join(f"{item['code']}: {item['message']}" for item in report["errors"])
        raise EditorialError(f"EDL validation failed: {detail}")
    return report


def load_words_json(path: str) -> list[dict[str, Any]]:
    """Load common word-ASR or HyperFrames-caption JSON shapes."""

    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EditorialError(f"could not load words JSON {path}: {exc}") from exc
    if isinstance(data, list):
        return normalize_words(data)
    if not isinstance(data, Mapping):
        raise EditorialError("words JSON must be an array or object")
    for key in ("words", "word_segments"):
        if isinstance(data.get(key), list):
            return normalize_words(data[key])
    clips = data.get("clips")
    if isinstance(clips, list):
        flattened = []
        for clip in clips:
            if isinstance(clip, Mapping):
                flattened.extend(clip.get("words", []))
        return normalize_words(flattened)
    segments = data.get("segments")
    if isinstance(segments, list):
        flattened = []
        for segment in segments:
            if isinstance(segment, Mapping):
                flattened.extend(segment.get("words", []))
        return normalize_words(flattened)
    raise EditorialError("could not find word-level timestamps in JSON")

"""Semantic caption phrasing, emphasis and readable display windows.

The engine treats word timestamps as immutable evidence.  It groups them into
one-idea caption chunks, balances line breaks at grammatical boundaries,
selects at most a scarce set of meaning words, and adds display windows without
moving any spoken-word onset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


SENTENCE_END = set(".!?…")
CLAUSE_PUNCT = set(",;:—–")

ABBREV = {
    "dr", "rev", "mr", "mrs", "ms", "sr", "jr", "st", "prof", "gen", "sen",
    "gov", "pres", "inc", "ltd", "co", "corp", "no", "vs", "etc", "eg", "ie",
    "am", "pm", "dept", "est", "approx", "fig", "vol",
}

FUNCTIONAL_WORDS = {
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "at", "by", "for",
    "from", "with", "as", "is", "am", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "i", "me", "my", "mine", "we", "us",
    "our", "ours", "you", "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "they", "them", "their", "this", "that", "these", "those", "there",
    "here", "who", "whom", "whose", "which", "what", "can", "could", "would", "should",
    "may", "might", "must", "will", "just", "very", "really", "actually", "like",
}
STRUCTURAL_WORDS = {
    "but", "because", "however", "instead", "although", "though", "therefore", "so",
    "then", "finally", "first", "second", "next", "until", "unless", "while", "when",
    "before", "after", "otherwise", "meanwhile", "suddenly", "yet", "if", "than",
}
STRONG_CONNECTORS = {
    "but", "because", "however", "instead", "although", "therefore", "until", "unless",
    "otherwise", "meanwhile", "yet",
}
NEGATIONS = {"no", "not", "never", "none", "nothing", "without", "cannot", "can't", "won't"}
HIGH_IMPACT = {
    "truth", "secret", "mistake", "failure", "success", "freedom", "fear", "money",
    "impossible", "always", "only", "best", "worst", "first", "last", "stop", "warning",
    "proven", "critical", "breakthrough", "risk", "win", "lose", "lost", "found",
}

PLATFORM_DEFAULTS = {
    "instagram-reels": dict(max_chars_per_line=24, max_words_per_caption=7, min_caption_dur=0.75),
    "tiktok": dict(max_chars_per_line=21, max_words_per_caption=6, min_caption_dur=0.70),
    "youtube-shorts": dict(max_chars_per_line=25, max_words_per_caption=8, min_caption_dur=0.80),
    "x": dict(max_chars_per_line=32, max_words_per_caption=11, min_caption_dur=0.90),
    "youtube": dict(max_chars_per_line=36, max_words_per_caption=12, min_caption_dur=0.90),
    "generic": dict(max_chars_per_line=26, max_words_per_caption=8, min_caption_dur=0.75),
}
PLATFORM_ALIASES = {
    "reels": "instagram-reels",
    "instagram": "instagram-reels",
    "ig": "instagram-reels",
    "shorts": "youtube-shorts",
    "twitter": "x",
}


def canonical_platform(platform):
    key = (platform or "instagram-reels").strip().lower().replace("_", "-")
    key = PLATFORM_ALIASES.get(key, key)
    if key not in PLATFORM_DEFAULTS:
        raise ValueError(
            f"unsupported platform {platform!r}; choose {', '.join(sorted(PLATFORM_DEFAULTS))}"
        )
    return key


@dataclass(frozen=True)
class Config:
    platform: str = "instagram-reels"
    max_chars_per_line: int = 24
    max_lines: int = 2
    max_words_per_caption: int = 7
    max_caption_dur: float = 3.2
    min_caption_dur: float = 0.75
    max_gap_join: float = 0.65
    soft_gap_break: float = 0.28
    min_caption_gap: float = 0.035
    hold_after_speech: float = 0.10
    reading_words_per_second: float = 3.6
    reading_behavior: str = "auto"
    max_emphasis_words: int = 1
    timing_tolerance: float = 0.08

    @property
    def char_budget(self):
        return self.max_chars_per_line * self.max_lines

    @classmethod
    def for_platform(cls, platform="instagram-reels", **overrides):
        platform = canonical_platform(platform)
        values = dict(PLATFORM_DEFAULTS[platform])
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(platform=platform, **values)

    def with_overrides(self, **overrides):
        values = {key: value for key, value in overrides.items() if value is not None}
        if "platform" in values:
            values["platform"] = canonical_platform(values["platform"])
        return replace(self, **values)


def _plain(text):
    return re.sub(r"[^\w%$€£'-]", "", text, flags=re.UNICODE).casefold()


def _is_abbrev(text):
    key = re.sub(r"[^a-zA-Z.]", "", text).rstrip(".").replace(".", "").lower()
    return key in ABBREV or len(key) == 1


def _trailing_punct(text):
    if not text:
        return None
    char = text[-1]
    if char in SENTENCE_END:
        return None if _is_abbrev(text) else "sentence"
    if char in CLAUSE_PUNCT:
        return "clause"
    return None


def _chars(words):
    return sum(len(word["text"]) for word in words) + max(0, len(words) - 1)


def _line_chars(words):
    return _chars(words)


def _boundary_score(words, index, cfg):
    """Lower is better for a break between index-1 and index."""
    if index <= 0 or index >= len(words):
        return 0.0
    left = words[index - 1]
    right = words[index]
    left_plain = _plain(left["text"])
    right_plain = _plain(right["text"])
    score = 0.0
    punct = _trailing_punct(left["text"])
    if punct == "sentence":
        score -= 8.0
    elif punct == "clause":
        score -= 5.0
    if right_plain in STRONG_CONNECTORS:
        score -= 4.0
    gap = max(0.0, right["start"] - left["end"])
    if gap >= cfg.soft_gap_break:
        score -= 4.0
    elif gap >= 0.16:
        score -= 1.5

    # Keep tightly bound phrases intact.
    if left_plain in {"a", "an", "the", "to", "of", "for", "with", "by"}:
        score += 8.0
    if right_plain in {"of", "to", "for", "with"}:
        score += 5.0
    return score


def _reading_behavior(words, cfg):
    if cfg.reading_behavior != "auto":
        return cfg.reading_behavior
    has_data = any(re.search(r"(?:\d|[$€£%])", word["text"]) for word in words)
    average_length = sum(len(_plain(word["text"])) for word in words) / max(1, len(words))
    if has_data or len(words) >= 8 or average_length >= 7.0:
        return "full-reading"
    if len(words) <= 3:
        return "glancing"
    return "skimming"


def _fits(words, cfg):
    if not words:
        return False
    duration = words[-1]["end"] - words[0]["start"]
    char_ok = _chars(words) <= cfg.char_budget or len(words) == 1
    return (
        char_ok
        and len(words) <= cfg.max_words_per_caption
        and duration <= cfg.max_caption_dur + 1e-9
    )


def _partition_utterance(words, cfg):
    """Dynamic-programming partition that prefers semantic/legal boundaries."""
    count = len(words)
    if not count:
        return []
    best = [None] * (count + 1)
    best[count] = (0.0, [])
    target = min(cfg.max_words_per_caption, 6)

    for start in range(count - 1, -1, -1):
        choices = []
        for end in range(start + 1, count + 1):
            chunk = words[start:end]
            if not _fits(chunk, cfg):
                if end == start + 1:
                    continue
                break
            if best[end] is None:
                continue
            length_cost = ((len(chunk) - target) / max(1, target)) ** 2 * 2.2
            if len(chunk) == 1 and count > 1:
                length_cost += 3.5
            break_cost = _boundary_score(words, end, cfg) if end < count else 0.0
            choices.append((length_cost + break_cost + best[end][0], [chunk] + best[end][1]))
        if choices:
            best[start] = min(choices, key=lambda choice: (choice[0], len(choice[1])))
        else:
            # A single unusually long token is still renderable and will be QA-warned.
            tail_cost, tail_chunks = best[start + 1]
            best[start] = (tail_cost + 10.0, [[words[start]]] + tail_chunks)
    return best[0][1]


def _utterances(words, cfg):
    chunks = []
    current = []
    for word in words:
        if current and word["start"] - current[-1]["end"] > cfg.max_gap_join:
            chunks.append(current)
            current = []
        current.append(word)
        if _trailing_punct(word["text"]) == "sentence":
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def _can_merge(left, right, cfg):
    words = left + right
    return (
        _chars(words) <= cfg.char_budget
        and len(words) <= cfg.max_words_per_caption
        and words[-1]["end"] - words[0]["start"] <= cfg.max_caption_dur
        and right[0]["start"] - left[-1]["end"] <= cfg.max_gap_join
    )


def _merge_unreadable(chunks, cfg):
    """Merge rapid-fire micro chunks when a legal readable handoff is impossible."""
    chunks = [list(chunk) for chunk in chunks]
    index = 0
    while index < len(chunks) - 1:
        available = chunks[index + 1][0]["start"] - chunks[index][0]["start"]
        speech_duration = chunks[index][-1]["end"] - chunks[index][0]["start"]
        if min(available, speech_duration) < cfg.min_caption_dur and _can_merge(
            chunks[index], chunks[index + 1], cfg
        ):
            chunks[index:index + 2] = [chunks[index] + chunks[index + 1]]
            continue
        index += 1
    return chunks


def _wrap(words, cfg):
    if cfg.max_lines <= 1 or len(words) <= 1:
        return [list(words)]
    if _line_chars(words) <= cfg.max_chars_per_line:
        return [list(words)]

    # Two lines are the production contract; choose the most balanced legal break.
    candidates = []
    for index in range(1, len(words)):
        left, right = words[:index], words[index:]
        left_chars, right_chars = _line_chars(left), _line_chars(right)
        overflow = max(0, left_chars - cfg.max_chars_per_line) + max(
            0, right_chars - cfg.max_chars_per_line
        )
        balance = abs(left_chars - right_chars) / max(1, cfg.max_chars_per_line)
        candidates.append(
            (overflow * 20.0 + balance + _boundary_score(words, index, cfg), index)
        )
    _, split = min(candidates, key=lambda item: (item[0], item[1]))
    return [list(words[:split]), list(words[split:])]


def _word_role_and_score(word, index, total):
    token = _plain(word["text"])
    if token in NEGATIONS:
        return "meaning", 0.97, "negation"
    if re.search(r"(?:\d|[$€£%])", word["text"]):
        return "meaning", 1.0, "number"
    if token in HIGH_IMPACT:
        return "meaning", 0.93, "keyword"
    if token in STRUCTURAL_WORDS:
        return "structural", 0.34, "structure"
    if token in FUNCTIONAL_WORDS or not token:
        return "functional", 0.05, "functional"

    score = 0.58
    if len(token) >= 8:
        score += 0.10
    if index > 0 and word["text"][:1].isupper():
        score += 0.13
    if word["text"].isupper() and len(token) > 1:
        score += 0.16
    if index == total - 1:
        score += 0.04
    return "meaning", min(0.90, score), "keyword"


def _annotate(words, cfg):
    annotated = []
    candidates = []
    for index, source in enumerate(words):
        word = dict(source)
        role, score, kind = _word_role_and_score(word, index, len(words))
        word.update(
            {
                "role": role,
                "emphasis_score": round(score, 3),
                "emphasis": False,
                "emphasis_kind": None,
                "motion_tier": 1,
            }
        )
        annotated.append(word)
        if role == "meaning" and score >= 0.55:
            candidates.append((score, index, kind))

    # Stable selection: higher score wins, then the later payoff word.
    selected = sorted(candidates, key=lambda item: (-item[0], -item[1]))[: cfg.max_emphasis_words]
    for score, index, kind in selected:
        annotated[index]["emphasis"] = True
        annotated[index]["emphasis_kind"] = kind
        annotated[index]["motion_tier"] = 3 if score >= 0.92 else 2
    return annotated


def _required_read_duration(words, behavior, cfg):
    behavior_factor = {
        "full-reading": 1.12,
        "skimming": 1.0,
        "glancing": 0.82,
    }.get(behavior, 1.0)
    conceptual = 0.28 + len(words) / max(1.0, cfg.reading_words_per_second)
    complex_words = sum(1 for word in words if len(_plain(word["text"])) >= 9)
    conceptual += complex_words * 0.08
    return round(max(cfg.min_caption_dur, conceptual * behavior_factor), 3)


def _finalize_chunks(chunks, cfg):
    segments = []
    for raw_words in chunks:
        words = _annotate(raw_words, cfg)
        behavior = _reading_behavior(words, cfg)
        start, speech_end = words[0]["start"], words[-1]["end"]
        segments.append(
            {
                "start": start,
                "end": speech_end,
                "speech_start": start,
                "speech_end": speech_end,
                "words": words,
                "lines": _wrap(words, cfg),
                "reading_behavior": behavior,
                "required_read_duration": _required_read_duration(words, behavior, cfg),
            }
        )

    for index, segment in enumerate(segments):
        desired_end = max(
            segment["speech_end"] + cfg.hold_after_speech,
            segment["speech_start"] + segment["required_read_duration"],
        )
        if index + 1 < len(segments):
            handoff = segments[index + 1]["speech_start"] - cfg.min_caption_gap
            display_end = min(desired_end, handoff)
            display_end = max(segment["speech_end"], display_end)
        else:
            display_end = desired_end
        segment["display_start"] = segment["speech_start"]
        segment["display_end"] = round(display_end, 6)
        segment["display_duration"] = round(display_end - segment["speech_start"], 6)

    # A rapid connector can be too wide to merge yet too brief to satisfy the
    # minimum exposure on its literal speech interval. Borrow the adjacent
    # handoff window without moving any word onset: the empty caption shell may
    # enter after the preceding speech ends, and its words still reveal only at
    # their immutable aligned starts.
    for index in range(1, len(segments) - 1):
        segment = segments[index]
        if segment["display_duration"] + 0.015 >= cfg.min_caption_dur:
            continue
        previous = segments[index - 1]
        following = segments[index + 1]
        borrowed_start = previous["speech_end"]
        borrowed_end = following["speech_start"]
        if borrowed_end - borrowed_start + 0.015 < cfg.min_caption_dur:
            continue
        if borrowed_start - previous["display_start"] + 0.015 < cfg.min_caption_dur:
            continue
        previous["display_end"] = round(
            min(previous["display_end"], borrowed_start),
            6,
        )
        previous["display_duration"] = round(
            previous["display_end"] - previous["display_start"],
            6,
        )
        segment["display_start"] = round(borrowed_start, 6)
        segment["display_end"] = round(borrowed_end, 6)
        segment["display_duration"] = round(borrowed_end - borrowed_start, 6)

    for segment in segments:
        segment_words = segment["words"]
        segment["emphasis"] = [
            {
                "word_index": word_index,
                "text": word["text"],
                "score": word["emphasis_score"],
                "kind": word["emphasis_kind"],
                "motion_tier": word["motion_tier"],
            }
            for word_index, word in enumerate(segment_words)
            if word["emphasis"]
        ]
    return segments


def segment_words(words, cfg=None):
    """Create semantic, timestamp-faithful caption segments.

    Sentence ends and long pauses define utterances.  Dynamic programming then
    chooses clause-, connector- and pause-aware breaks under word, character and
    duration budgets.  Rapid micro-chunks are merged when required for a readable
    non-overlapping handoff.
    """
    cfg = cfg or Config.for_platform("instagram-reels")
    clean = [dict(word) for word in words if str(word.get("text", "")).strip()]
    if not clean:
        return []

    chunks = []
    for utterance in _utterances(clean, cfg):
        chunks.extend(_partition_utterance(utterance, cfg))
    chunks = _merge_unreadable(chunks, cfg)
    return _finalize_chunks(chunks, cfg)

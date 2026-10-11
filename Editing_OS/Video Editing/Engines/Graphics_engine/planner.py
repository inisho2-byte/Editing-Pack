"""Semantic graphics planning for the Video Editing OS.

The planner consumes *word-timed* transcript data and produces a deterministic
graphics plan.  It deliberately does not put a graphic on every sentence:
clauses must earn one through information value (a number, comparison, process,
mechanism, named object, or genuine emphasis).  The resulting cues are anchored
to the word that motivated the graphic, frame-quantized, layout-aware, and safe
for captions/platform UI.

No model or network call is required.  This module is intentionally a reliable
baseline that an LLM can augment with curated cues without losing deterministic
timing and QA.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def intersects(self, other: "Rect", padding: int = 0) -> bool:
        return not (
            self.right + padding <= other.x
            or other.right + padding <= self.x
            or self.bottom + padding <= other.y
            or other.bottom + padding <= self.y
        )


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float
    index: int


@dataclass(frozen=True)
class Clause:
    words: tuple[TimedWord, ...]
    text: str
    start: float
    end: float
    index: int


@dataclass(frozen=True)
class AssetRecord:
    path: str
    kind: str
    tags: tuple[str, ...]
    is_meme: bool = False


@dataclass
class GraphicCue:
    id: str
    graphic_type: str
    intent: str
    evidence: list[str]
    headline: str
    detail: str
    start_sec: float
    anchor_sec: float
    end_sec: float
    anchor_word: str
    anchor_word_index: int
    score: float
    layout: str
    graphic_bounds: Rect
    speaker_bounds: Rect | None
    speaker_shape: str
    accent_index: int
    content: dict[str, Any] = field(default_factory=dict)
    asset_path: str | None = None
    motion: str = "settled-reveal"
    speaker_crop_status: str = "not-applicable"
    meaning_end_sec: float | None = None

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_sec"] = round(self.duration, 4)
        return data


@dataclass
class GraphicsPlan:
    schema_version: int
    composition: dict[str, Any]
    theme: dict[str, Any]
    safe_areas: dict[str, Any]
    source_video: str | None
    cues: list[GraphicCue]
    asset_catalog: dict[str, Any]
    treatment: dict[str, Any] | None = None
    qa: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "composition": self.composition,
            "theme": self.theme,
            "safeAreas": self.safe_areas,
            "sourceVideo": self.source_video,
            "cues": [cue.to_dict() for cue in self.cues],
            "assetCatalog": self.asset_catalog,
            "treatment": self.treatment,
            "qa": self.qa,
        }


PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "reels": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        # Fractions are shared with Captions_engine/emit.py.  Keeping them
        # normalized (rather than as 1080x1920 pixels) makes custom and 2x
        # renders preserve exactly the same usable surface.
        "safe_fractions": {"top": 0.10, "right": 0.18, "bottom": 0.20, "left": 0.07},
        "caption_height_fraction": 300 / 1920,
        "target_spacing": 2.7,
        "threshold": 2.25,
        "max_graphic_ratio": 0.78,
        "max_headline_words": 7,
        "style": "designed-editorial",
    },
    "tiktok": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "safe_fractions": {"top": 0.11, "right": 0.19, "bottom": 0.23, "left": 0.07},
        "caption_height_fraction": 310 / 1920,
        "target_spacing": 2.45,
        "threshold": 2.15,
        "max_graphic_ratio": 0.82,
        "max_headline_words": 7,
        "style": "native-clean",
    },
    "shorts": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "safe_fractions": {"top": 0.09, "right": 0.17, "bottom": 0.18, "left": 0.07},
        "caption_height_fraction": 300 / 1920,
        "target_spacing": 3.15,
        "threshold": 2.35,
        "max_graphic_ratio": 0.72,
        "max_headline_words": 7,
        "style": "legible-clean",
    },
    "youtube": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "safe_fractions": {"top": 0.06, "right": 0.06, "bottom": 0.11, "left": 0.06},
        "caption_height_fraction": 150 / 1080,
        "target_spacing": 6.0,
        "threshold": 2.55,
        "max_graphic_ratio": 0.56,
        "max_headline_words": 9,
        "style": "editorial-broadcast",
    },
    "x": {
        "width": 1080,
        "height": 1350,
        "fps": 30,
        "safe_fractions": {"top": 0.07, "right": 0.08, "bottom": 0.14, "left": 0.08},
        "caption_height_fraction": 210 / 1350,
        "target_spacing": 4.0,
        "threshold": 2.3,
        "max_graphic_ratio": 0.72,
        "max_headline_words": 9,
        "style": "information-dense",
    },
}

PLATFORM_ALIASES = {
    "instagram": "reels",
    "instagram-reels": "reels",
    "ig": "reels",
    "youtube-shorts": "shorts",
    "yt-shorts": "shorts",
    "twitter": "x",
    "landscape": "youtube",
}

NICHE_THEMES: dict[str, dict[str, Any]] = {
    "tech": {
        "background": "#0B1118",
        "surface": "#111C27",
        "text": "#F4F8FC",
        "muted": "#9FB0C1",
        "accents": ["#37D6D0", "#7DD3FC", "#A7F3D0", "#C4B5FD"],
        "font": "Inter",
        "tone": "precise",
    },
    "finance": {
        "background": "#07131F",
        "surface": "#102131",
        "text": "#F4F7FA",
        "muted": "#9FB1C2",
        "accents": ["#54C5D0", "#7BC5A5", "#B9D8E8", "#D9B86C"],
        "font": "Inter",
        "tone": "calm-authoritative",
    },
    "luxury": {
        "background": "#12100E",
        "surface": "#211D19",
        "text": "#F7F1E8",
        "muted": "#B8AA99",
        "accents": ["#D2B47A", "#C9A98C", "#E7DCCB", "#8D9A8B"],
        "font": "Inter",
        "tone": "warm-restrained",
    },
    "fitness": {
        "background": "#0B0C0D",
        "surface": "#181A1C",
        "text": "#F7F8F8",
        "muted": "#B2B7BA",
        "accents": ["#B7E34B", "#67D6C5", "#F1C66B", "#91A8FF"],
        "font": "Inter",
        "tone": "high-contrast-controlled",
    },
    "podcast": {
        "background": "#121416",
        "surface": "#1C2024",
        "text": "#F4F2ED",
        "muted": "#ABA8A1",
        "accents": ["#73CFC5", "#D6A876", "#A7B5D8", "#C5B5D8"],
        "font": "Inter",
        "tone": "natural-editorial",
    },
    "education": {
        "background": "#F2F0EA",
        "surface": "#E5E1D7",
        "text": "#161A1E",
        "muted": "#5D6670",
        "accents": ["#217C7E", "#B35B3F", "#3D6EA8", "#7B6BA8"],
        "font": "Inter",
        "tone": "clear-editorial",
    },
    "documentary": {
        "background": "#161616",
        "surface": "#222220",
        "text": "#F2EFE8",
        "muted": "#AAA69B",
        "accents": ["#B6A47C", "#829A91", "#B88274", "#8795AA"],
        "font": "Inter",
        "tone": "muted-human",
    },
    "general": {
        "background": "#0E151C",
        "surface": "#17222C",
        "text": "#F5F8FA",
        "muted": "#A2B0BC",
        "accents": ["#3DD6D0", "#7DB7D8", "#9FC7A6", "#C2AEDB"],
        "font": "Inter",
        "tone": "adaptive-precision",
    },
}

FILLER = {
    "um", "uh", "erm", "like", "you", "know", "basically", "literally",
    "actually", "kind", "sort", "just", "really", "very", "so", "well",
}
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "at",
    "for", "with", "is", "are", "was", "were", "be", "been", "being", "it",
    "this", "that", "these", "those", "i", "we", "they", "he", "she", "you",
    "your", "our", "their", "my", "me", "do", "does", "did", "can", "could",
    "would", "should", "have", "has", "had", "from", "as", "by", "if", "then",
}

TYPE_SIGNALS: dict[str, set[str]] = {
    "comparison": {
        "versus", "vs", "unlike", "instead", "compared", "before", "after",
        "better", "worse", "more", "less", "difference", "between",
    },
    "process": {
        "first", "second", "third", "next", "then", "finally", "step", "steps",
        "process", "workflow", "collect", "build", "test", "measure", "repeat",
    },
    "concept_diagram": {
        "because", "why", "means", "works", "system", "connect", "cause", "drives",
        "distribution", "growth", "engine", "loop", "idea", "ideas", "strategy",
    },
    "quote": {"said", "says", "called", "quote", "remember", "mantra"},
    "asset_focus": {
        "app", "website", "screen", "product", "podcast", "video", "photo", "logo",
        "document", "dashboard", "phone", "book", "report",
    },
    "emphasis": {
        "important", "critical", "never", "always", "only", "secret", "truth",
        "key", "best", "worst", "clever", "easy", "hard", "mistake", "remember",
    },
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def resolve_platform(platform: str) -> tuple[str, dict[str, Any]]:
    key = re.sub(r"\s+", "-", (platform or "reels").strip().lower())
    key = PLATFORM_ALIASES.get(key, key)
    if key not in PLATFORM_PROFILES:
        supported = ", ".join(sorted(PLATFORM_PROFILES))
        raise ValueError(f"unsupported platform {platform!r}; choose one of: {supported}")
    return key, dict(PLATFORM_PROFILES[key])


def resolve_theme(niche: str) -> tuple[str, dict[str, Any]]:
    text = (niche or "general").strip().lower()
    aliases = {
        "saas": "tech", "software": "tech", "ai": "tech", "coding": "tech",
        "business": "finance", "investing": "finance", "real-estate": "finance",
        "health": "fitness", "workout": "fitness", "interview": "podcast",
        "tutorial": "education", "explainer": "education", "cinematic": "documentary",
    }
    key = aliases.get(text, text)
    if key not in NICHE_THEMES:
        key = next((candidate for candidate in NICHE_THEMES if candidate in text), "general")
    return key, dict(NICHE_THEMES[key])


def theme_from_treatment_tokens(tokens: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a selected ``taste-selection/v1`` treatment without guessing.

    The selected contract must freeze every color the compositor consumes. A
    missing surface or muted color is an approval defect, not permission to
    fall back to the historical niche table.
    """
    if not isinstance(tokens, Mapping):
        raise ValueError("treatment tokens must be an object")
    palette = tokens.get("palette")
    typography = tokens.get("typography")
    if not isinstance(palette, Mapping) or not isinstance(typography, Mapping):
        raise ValueError("treatment tokens require palette and typography objects")
    required_colors = {"background", "surface", "foreground", "muted", "accents"}
    missing = sorted(required_colors - set(palette))
    if missing:
        raise ValueError(
            "selected treatment palette is incomplete: " + ", ".join(missing)
        )
    accents = palette.get("accents")
    if not isinstance(accents, list) or not accents:
        raise ValueError("selected treatment palette requires at least one accent")
    display_family = str(typography.get("display_family") or "").strip()
    body_family = str(typography.get("body_family") or "").strip()
    if not display_family or not body_family:
        raise ValueError(
            "selected treatment typography requires display_family and body_family"
        )
    supported_families = {"inter", "arial"}
    if (
        display_family.casefold() not in supported_families
        or body_family.casefold() not in supported_families
    ):
        raise ValueError(
            "selected treatment requests a font that is not packaged by this "
            "engine; use vendored Inter, Windows Arial, or supply a future "
            "hash-bound font artifact"
        )
    return {
        "background": str(palette["background"]),
        "surface": str(palette["surface"]),
        "text": str(palette["foreground"]),
        "muted": str(palette["muted"]),
        "accents": [str(color) for color in accents],
        "font": display_family,
        "tone": "selected-treatment",
    }


def _flatten_word_source(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return data
    if not isinstance(data, Mapping):
        raise TypeError("transcript must be a word list or a mapping containing words")
    if isinstance(data.get("words"), list):
        return data["words"]
    if isinstance(data.get("retimed_words"), list):
        return data["retimed_words"]
    if isinstance(data.get("segments"), list):
        words: list[Mapping[str, Any]] = []
        for segment in data["segments"]:
            if isinstance(segment, Mapping) and isinstance(segment.get("words"), list):
                words.extend(segment["words"])
        if words:
            return words
    raise ValueError("word-level timestamps are required (expected words[] with text/word, start, end)")


def normalize_words(data: Any) -> list[TimedWord]:
    """Normalize Whisper/WhisperX/HyperFrames word JSON into strict timed words."""
    source = _flatten_word_source(data)
    words: list[TimedWord] = []
    for item in source:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("text", item.get("word", ""))
        text = str(raw).strip()
        if not text or item.get("start") is None or item.get("end") is None:
            continue
        start = float(item["start"])
        end = float(item["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"invalid word timing for {text!r}: {start}..{end}")
        if words and start < words[-1].end - 1e-6:
            raise ValueError(
                "word timestamps must not overlap: "
                f"{text!r} starts at {start} before {words[-1].text!r} ends at {words[-1].end}"
            )
        words.append(TimedWord(text=text, start=start, end=end, index=len(words)))
    if not words:
        raise ValueError("transcript contains no usable word-level timestamps")
    return words


def _join_words(words: Sequence[TimedWord]) -> str:
    text = " ".join(word.text for word in words)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([\"'])\s+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def build_clauses(words: Sequence[TimedWord], pause_threshold: float = 0.42,
                  max_words: int = 13, max_duration: float = 5.2) -> list[Clause]:
    """Group words at linguistic boundaries, never by character count."""
    raw_groups: list[list[TimedWord]] = []
    current: list[TimedWord] = []
    for index, word in enumerate(words):
        current.append(word)
        next_word = words[index + 1] if index + 1 < len(words) else None
        pause = (next_word.start - word.end) if next_word else pause_threshold
        terminal = bool(re.search(r"[.!?][\"']?$", word.text))
        soft = bool(re.search(r"[,;:][\"']?$", word.text)) and len(current) >= 5
        long_enough = len(current) >= max_words or (word.end - current[0].start) >= max_duration
        pause_break = pause >= pause_threshold and len(current) >= 3
        if terminal or soft or long_enough or pause_break or next_word is None:
            raw_groups.append(current)
            current = []

    # Merge tiny fragments so a graphic never represents a dangling filler phrase.
    merged: list[list[TimedWord]] = []
    for group in raw_groups:
        meaningful = [w for w in group if _token(w.text) not in STOPWORDS | FILLER]
        if merged and len(meaningful) < 2 and len(merged[-1]) + len(group) <= max_words + 3:
            merged[-1].extend(group)
        else:
            merged.append(list(group))

    return [
        Clause(tuple(group), _join_words(group), group[0].start, group[-1].end, index)
        for index, group in enumerate(merged)
    ]


def _token(text: str) -> str:
    return re.sub(r"[^a-z0-9%$/'-]+", "", text.lower()).strip("'-")


def _tokens(text: str) -> list[str]:
    return [token for token in (_token(part) for part in text.split()) if token]


def _is_number(token: str) -> bool:
    if re.fullmatch(r"\d+/\d+", token):
        return True
    return bool(re.search(r"(?:[$£€]?\d[\d,.]*%?|\d+(?:x|k|m|b))$", token, re.I))


def _parse_proportion(tokens: Sequence[str]) -> float | None:
    """Parse only proportions explicitly stated by the transcript.

    Bare counts such as ``3 prototypes`` are not evidence for a progress bar.
    Accepted evidence is a percentage, fraction, unit-interval decimal,
    ``N percent``, or ``N out of M``.
    """
    cleaned = [_token(token).replace(",", "") for token in tokens]
    for index, token in enumerate(cleaned):
        if token.endswith("%"):
            try:
                value = float(token[:-1]) / 100.0
            except ValueError:
                continue
            if 0.0 <= value <= 1.0:
                return round(value, 6)
        if "/" in token:
            numerator, _, denominator = token.partition("/")
            try:
                value = float(numerator) / float(denominator)
            except (ValueError, ZeroDivisionError):
                continue
            if 0.0 <= value <= 1.0:
                return round(value, 6)
        stripped = re.sub(r"^[^0-9.-]+", "", token)
        try:
            number = float(stripped)
        except ValueError:
            continue
        next_token = cleaned[index + 1] if index + 1 < len(cleaned) else ""
        if next_token in {"percent", "percentage"} and 0.0 <= number <= 100.0:
            return round(number / 100.0, 6)
        if 0.0 <= number <= 1.0 and "." in token:
            return round(number, 6)
        if next_token == "out" and index + 3 < len(cleaned) and cleaned[index + 2] == "of":
            try:
                value = number / float(cleaned[index + 3])
            except (ValueError, ZeroDivisionError):
                continue
            if 0.0 <= value <= 1.0:
                return round(value, 6)
    return None


def _semantic_analysis(clause: Clause) -> dict[str, Any]:
    tokens = _tokens(clause.text)
    token_set = set(tokens)
    evidence: list[str] = []
    scores: dict[str, float] = {}

    number_tokens = [token for token in tokens if _is_number(token)]
    if number_tokens:
        scores["stat"] = 3.0 + min(0.6, 0.2 * (len(number_tokens) - 1))
        evidence.append("specific number/data point")

    for graphic_type, signals in TYPE_SIGNALS.items():
        hits = token_set & signals
        if not hits:
            continue
        base = {
            "comparison": 2.55,
            "process": 2.25,
            "concept_diagram": 1.75,
            "quote": 1.65,
            "asset_focus": 1.35,
            "emphasis": 1.4,
        }[graphic_type]
        scores[graphic_type] = base + min(0.6, 0.18 * (len(hits) - 1))
        evidence.append(f"{graphic_type.replace('_', ' ')} language: {', '.join(sorted(hits)[:3])}")

    meaningful = [token for token in tokens if token not in STOPWORDS | FILLER]
    if len(meaningful) >= 5:
        evidence.append("information-dense clause")
    density_bonus = min(0.7, max(0, len(meaningful) - 3) * 0.1)
    question_bonus = 0.45 if clause.text.rstrip().endswith("?") else 0.0
    hook_bonus = 0.45 if clause.index == 0 and len(meaningful) >= 3 else 0.0
    filler_ratio = sum(token in FILLER for token in tokens) / max(1, len(tokens))
    penalty = 1.2 if len(meaningful) < 2 else 0.0
    if filler_ratio > 0.34:
        penalty += 0.9
        evidence.append("filler-heavy (penalized)")

    if scores:
        graphic_type = max(scores, key=lambda key: (scores[key], key))
        score = scores[graphic_type] + density_bonus + question_bonus + hook_bonus - penalty
    elif len(meaningful) >= 5:
        graphic_type = "keyword"
        score = 1.35 + density_bonus + hook_bonus - penalty
        evidence.append("single concise idea")
    else:
        graphic_type = "none"
        score = max(0.0, 0.6 + density_bonus - penalty)

    return {
        "type": graphic_type,
        "score": round(score, 3),
        "evidence": evidence,
        "tokens": tokens,
        "meaningful": meaningful,
        "numbers": number_tokens,
    }


def discover_assets(paths: Iterable[str | Path], allow_memes: bool = False) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    for raw_root in sorted({str(Path(path).resolve()) for path in paths if path}):
        root = Path(raw_root)
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in files:
            suffix = path.suffix.lower()
            kind = "image" if suffix in IMAGE_EXTENSIONS else "video" if suffix in VIDEO_EXTENSIONS else None
            if not kind:
                continue
            lowered_parts = [part.lower() for part in path.parts]
            is_meme = any("meme" in part for part in lowered_parts)
            if is_meme and not allow_memes:
                continue
            tag_text = " ".join(path.with_suffix("").parts[-4:])
            tags = sorted({token for token in re.split(r"[^a-z0-9]+", tag_text.lower())
                           if len(token) > 1 and token not in STOPWORDS})
            records.append(AssetRecord(str(path.resolve()), kind, tuple(tags), is_meme))
    return sorted(records, key=lambda asset: asset.path.lower())


def select_asset(clause: Clause, assets: Sequence[AssetRecord], niche: str,
                 graphic_type: str) -> AssetRecord | None:
    tokens = set(_tokens(clause.text)) - STOPWORDS - FILLER
    if not tokens or not assets:
        return None
    synonyms = {
        "podcast": {"microphone", "mic", "studio", "episode"},
        "idea": {"bulb", "lightbulb", "brainstorm"},
        "money": {"finance", "cash", "dollar", "chart"},
        "phone": {"mobile", "iphone", "screen"},
        "video": {"footage", "clip", "film"},
    }
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(synonyms.get(token, set()))

    ranked: list[tuple[float, AssetRecord]] = []
    for asset in assets:
        overlap = expanded & set(asset.tags)
        if not overlap:
            continue
        score = float(len(overlap) * 3)
        if niche in asset.tags:
            score += 0.75
        if graphic_type == "asset_focus" and asset.kind in {"image", "video"}:
            score += 0.5
        if asset.is_meme:
            score -= 0.75
        ranked.append((score, asset))
    return max(ranked, key=lambda pair: (pair[0], pair[1].path.lower()))[1] if ranked else None


def _anchor_word(clause: Clause, analysis: Mapping[str, Any]) -> TimedWord:
    graphic_type = analysis["type"]
    signal_sets = {
        "stat": set(analysis.get("numbers", [])),
        "comparison": TYPE_SIGNALS["comparison"],
        "process": TYPE_SIGNALS["process"],
        "concept_diagram": TYPE_SIGNALS["concept_diagram"],
        "quote": TYPE_SIGNALS["quote"],
        "asset_focus": TYPE_SIGNALS["asset_focus"],
        "emphasis": TYPE_SIGNALS["emphasis"],
    }
    signals = signal_sets.get(graphic_type, set())
    for word in clause.words:
        token = _token(word.text)
        if token in signals or (graphic_type == "stat" and _is_number(token)):
            return word
    meaningful = [word for word in clause.words if _token(word.text) not in STOPWORDS | FILLER]
    return meaningful[-1] if meaningful else clause.words[0]


def _clean_phrase(clause: Clause, max_words: int) -> str:
    words = list(clause.words)
    while words and _token(words[0].text) in FILLER | {"and", "but", "so", "well"}:
        words.pop(0)
    selected = words[:max_words]
    text = _join_words(selected).strip(" ,.;:!?-")
    if len(words) > max_words:
        text += "…"
    return text or clause.text


def _content_for(clause: Clause, analysis: Mapping[str, Any], max_words: int) -> tuple[str, str, dict[str, Any]]:
    graphic_type = analysis["type"]
    headline = _clean_phrase(clause, max_words)
    detail = ""
    content: dict[str, Any] = {}
    tokens = [word.text.strip(" ,.;:!?") for word in clause.words]

    if graphic_type == "stat":
        number = next((text for text in tokens if _is_number(_token(text))), analysis["numbers"][0])
        label_words = [text for text in tokens if text != number]
        label = " ".join(label_words).strip()
        headline = number
        detail = _clean_text(label, max_words + 2)
        content = {"value": number, "label": detail}
        proportion = _parse_proportion(tokens)
        if proportion is not None:
            content["proportion"] = proportion
    elif graphic_type == "comparison":
        split_at = next((i for i, text in enumerate(tokens) if _token(text) in TYPE_SIGNALS["comparison"]), len(tokens) // 2)
        left = _clean_text(" ".join(tokens[:split_at]), max(2, max_words // 2)) or "Current"
        right = _clean_text(" ".join(tokens[split_at + 1:]), max(2, max_words // 2)) or "Better"
        headline = "A clearer comparison"
        content = {"left": left, "right": right}
    elif graphic_type == "process":
        chunks = re.split(r"\b(?:then|next|finally|and then|and)\b|[,;]", clause.text, flags=re.I)
        steps = [_clean_text(chunk, 5) for chunk in chunks if _clean_text(chunk, 5)][:3]
        if len(steps) < 2:
            meaningful = analysis["meaningful"][:6]
            midpoint = max(1, len(meaningful) // 2)
            steps = [" ".join(meaningful[:midpoint]), " ".join(meaningful[midpoint:])]
        headline = "The process"
        content = {"steps": steps}
    elif graphic_type == "concept_diagram":
        nodes = [token for token in analysis["meaningful"] if token not in TYPE_SIGNALS["concept_diagram"]]
        nodes = list(dict.fromkeys(nodes))[:3]
        headline = _clean_phrase(clause, min(max_words, 6))
        content = {"center": _token(_anchor_word(clause, analysis).text) or "idea", "nodes": nodes}
    elif graphic_type == "quote":
        headline = _clean_phrase(clause, min(max_words + 2, 10))
        content = {"quote": headline}
    elif graphic_type == "asset_focus":
        content = {"subject": _token(_anchor_word(clause, analysis).text)}
    else:
        emphasis = [token for token in analysis["meaningful"] if token in TYPE_SIGNALS["emphasis"]]
        content = {"emphasis": emphasis[0] if emphasis else (analysis["meaningful"][-1] if analysis["meaningful"] else "")}

    return headline, detail, content


def _clean_text(text: str, max_words: int) -> str:
    parts = [part for part in re.sub(r"\s+", " ", text).strip(" ,.;:!?-").split() if part]
    result = " ".join(parts[:max_words])
    return result + ("…" if len(parts) > max_words else "")


def _quantize(value: float, fps: int) -> float:
    return round(round(value * fps) / fps, 4)


def _safe_rect(profile: Mapping[str, Any], width: int, height: int) -> Rect:
    fractions = profile["safe_fractions"]
    left = round(width * float(fractions["left"]))
    top = round(height * float(fractions["top"]))
    right = round(width * float(fractions["right"]))
    bottom = round(height * float(fractions["bottom"]))
    return Rect(left, top, width - left - right, height - top - bottom)


def _caption_rect(profile: Mapping[str, Any], width: int, height: int) -> Rect:
    fractions = profile["safe_fractions"]
    left = round(width * float(fractions["left"]))
    right = round(width * float(fractions["right"]))
    bottom = round(height * float(fractions["bottom"]))
    caption_height = min(
        round(height * float(profile["caption_height_fraction"])),
        height - bottom,
    )
    return Rect(left, height - bottom - caption_height, width - left - right, caption_height)


def _layout_bounds(layout: str, profile: Mapping[str, Any], width: int, height: int,
                   captions_enabled: bool) -> tuple[Rect, Rect | None, str]:
    safe = _safe_rect(profile, width, height)
    caption = _caption_rect(profile, width, height)
    usable_bottom = caption.y - 28 if captions_enabled else safe.bottom
    usable_height = max(100, usable_bottom - safe.y)
    portrait = height > width

    if layout == "stage_pip":
        pip_size = round(width * (0.24 if portrait else 0.17))
        pip = Rect(safe.right - pip_size, safe.y + (26 if portrait else 0), pip_size, pip_size)
        # A portrait PiP is an intentional foreground layer over a full video
        # stage, not a reason to squeeze the graphic into a web-sized column.
        graphics = Rect(safe.x, safe.y, safe.width, usable_height)
        return graphics, pip, "circle"
    if layout == "side_panel":
        if portrait:
            speaker_h = round(usable_height * 0.34)
            speaker = Rect(safe.x, safe.y, safe.width, speaker_h)
            graphics = Rect(safe.x, speaker.bottom + 28, safe.width,
                            max(120, usable_bottom - speaker.bottom - 28))
        else:
            speaker_w = round(safe.width * 0.42)
            speaker = Rect(safe.x, safe.y, speaker_w, usable_height)
            graphics = Rect(speaker.right + 36, safe.y,
                            safe.right - speaker.right - 36, usable_height)
        return graphics, speaker, "rounded-rect"
    if layout == "full_stage":
        return Rect(safe.x, safe.y, safe.width, usable_height), None, "hidden"
    if layout == "lower_third":
        height_value = round(safe.height * 0.28)
        return Rect(safe.x, safe.bottom - height_value, safe.width, height_value), None, "full-frame"
    # overlay: keep the graphic in the upper/side safe zone; full-frame speaker remains visible.
    overlay_height = round(usable_height * (0.61 if portrait else 0.64))
    return Rect(safe.x, safe.y, safe.width, overlay_height), None, "full-frame"


def _choose_layout(graphic_type: str, score: float, index: int, previous: str | None,
                   captions_enabled: bool, portrait: bool) -> str:
    primary = {
        "stat": "full_stage" if score >= 3.7 else "stage_pip",
        "comparison": "side_panel",
        "process": "stage_pip",
        "concept_diagram": "stage_pip",
        "asset_focus": "stage_pip",
        "quote": "overlay",
        "emphasis": "overlay",
        "keyword": "overlay",
    }.get(graphic_type, "overlay")
    alternatives = {
        "stage_pip": ["side_panel", "full_stage", "overlay"],
        "side_panel": ["stage_pip", "overlay"],
        "full_stage": ["stage_pip", "overlay"],
        "overlay": ["stage_pip", "side_panel"],
    }
    if primary == previous:
        primary = alternatives[primary][index % len(alternatives[primary])]
    if primary == "lower_third" and captions_enabled:
        primary = "overlay"
    if primary == "side_panel" and portrait and graphic_type == "comparison":
        # Vertical stack is still semantically split, and preserves readable type on mobile.
        return "side_panel"
    return primary


def _candidate_windows(clauses: Sequence[Clause], analyses: Sequence[Mapping[str, Any]],
                       duration: float, profile: Mapping[str, Any], fps: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    holds = {
        "stat": 2.8, "comparison": 3.4, "process": 3.8, "concept_diagram": 3.5,
        "quote": 2.8, "asset_focus": 3.2, "emphasis": 2.3, "keyword": 2.2,
    }
    for clause, analysis in zip(clauses, analyses):
        if analysis["type"] == "none" or analysis["score"] < profile["threshold"]:
            continue
        anchor = _anchor_word(clause, analysis)
        # Give both the shell and cue-specific reveal enough editorial lead to
        # be visibly established on the exact trigger-word frame.
        start = _quantize(max(0.0, anchor.start - 0.52), fps)
        anchor_sec = _quantize(anchor.start, fps)
        # Preserve the explanatory clause instead of enforcing a refresh timer.
        settled_hold = max(0.38, min(0.85, len(clause.words) * 0.06))
        end = min(duration, max(clause.end + settled_hold, start + 1.55,
                                anchor_sec + min(holds[analysis["type"]], 0.85)))
        candidates.append({
            "clause": clause,
            "analysis": analysis,
            "anchor": anchor,
            "start": start,
            "anchor_sec": anchor_sec,
            "end": _quantize(end, fps),
        })

    # Select strongest moments with a density ceiling, then restore chronology.
    max_count = max(1, math.ceil(duration / profile["target_spacing"]))
    ranked = sorted(candidates, key=lambda item: (-item["analysis"]["score"], item["anchor_sec"]))
    selected: list[dict[str, Any]] = []
    minimum_anchor_gap = min(1.6, profile["target_spacing"] * 0.48)
    for item in ranked:
        if any(abs(item["anchor_sec"] - other["anchor_sec"]) < minimum_anchor_gap for other in selected):
            continue
        selected.append(item)
        if len(selected) >= max_count:
            break
    selected.sort(key=lambda item: item["start"])

    # Remove interval collisions without breaking word anchors.
    result: list[dict[str, Any]] = []
    for item in selected:
        rejected = False
        while result and item["start"] < result[-1]["end"] + 0.20:
            previous = result[-1]
            boundary = _quantize(item["start"] - 0.20, fps)
            meaning_end = _quantize(previous["clause"].end, fps)
            if (boundary - previous["start"] >= 1.35
                    and previous["anchor_sec"] + 0.38 <= boundary
                    and meaning_end <= boundary):
                previous["end"] = boundary
                break
            elif item["analysis"]["score"] > previous["analysis"]["score"]:
                result.pop()
            else:
                rejected = True
                break
        if not rejected and item["end"] - item["start"] >= 1.35:
            result.append(item)
    return result


def plan_graphics(transcript: Any, duration: float | None = None, *, platform: str = "reels",
                  niche: str = "general", goal: str = "retention and clarity",
                  source_video: str | None = None, asset_dirs: Iterable[str | Path] = (),
                  captions_enabled: bool = True, allow_meme_assets: bool = False,
                  fps: int | None = None, width: int | None = None,
                  height: int | None = None, seed: int = 7,
                  treatment_tokens: Mapping[str, Any] | None = None,
                  treatment_provenance: Mapping[str, Any] | None = None) -> GraphicsPlan:
    """Build a deterministic, word-anchored graphics plan.

    ``seed`` is recorded for provenance but no unseeded/random behavior exists;
    identical inputs always produce byte-equivalent plan dictionaries.
    """
    words = normalize_words(transcript)
    platform_key, profile = resolve_platform(platform)
    niche_key, fallback_theme = resolve_theme(niche)
    theme = (
        theme_from_treatment_tokens(treatment_tokens)
        if treatment_tokens is not None
        else fallback_theme
    )
    fps_value = int(fps or profile["fps"])
    width_value = int(width or profile["width"])
    height_value = int(height or profile["height"])
    duration_value = float(duration if duration is not None else words[-1].end)
    if duration_value <= 0:
        raise ValueError("duration must be positive")
    if words[-1].end > duration_value + 1e-6:
        raise ValueError(
            f"word {words[-1].text!r} ends at {words[-1].end}, "
            f"beyond composition duration {duration_value}"
        )

    assets = discover_assets(asset_dirs, allow_memes=allow_meme_assets)
    clauses = build_clauses(words)
    analyses: list[dict[str, Any]] = []
    for clause in clauses:
        analysis = _semantic_analysis(clause)
        matched_asset = select_asset(clause, assets, niche_key, analysis["type"])
        if matched_asset:
            analysis = dict(analysis)
            analysis["score"] = round(float(analysis["score"]) + 1.15, 3)
            analysis["evidence"] = [*analysis["evidence"], "local asset matches the spoken subject"]
            # A relevant real asset beats generic decoration unless a data/comparison
            # graphic carries more explanatory value.
            if analysis["type"] not in {"stat", "comparison", "process"}:
                analysis["type"] = "asset_focus"
        analyses.append(analysis)
    candidates = _candidate_windows(clauses, analyses, duration_value, profile, fps_value)
    safe = _safe_rect(profile, width_value, height_value)
    caption = _caption_rect(profile, width_value, height_value)

    cues: list[GraphicCue] = []
    previous_layout: str | None = None
    portrait = height_value > width_value
    for index, item in enumerate(candidates):
        clause: Clause = item["clause"]
        analysis: Mapping[str, Any] = item["analysis"]
        graphic_type = analysis["type"]
        asset = select_asset(clause, assets, niche_key, graphic_type)
        if asset and graphic_type in {"keyword", "asset_focus"}:
            graphic_type = "asset_focus"
        layout = _choose_layout(graphic_type, analysis["score"], index, previous_layout,
                                captions_enabled, portrait)
        graphic_bounds, speaker_bounds, speaker_shape = _layout_bounds(
            layout, profile, width_value, height_value, captions_enabled
        )
        headline, detail, content = _content_for(clause, {**analysis, "type": graphic_type},
                                                 profile["max_headline_words"])
        cue_id = f"graphic-{index + 1:02d}"
        cue = GraphicCue(
            id=cue_id,
            graphic_type=graphic_type,
            intent=f"Make the spoken idea tangible without repeating the caption: {clause.text}",
            evidence=list(analysis["evidence"]),
            headline=headline,
            detail=detail,
            start_sec=item["start"],
            anchor_sec=item["anchor_sec"],
            end_sec=item["end"],
            anchor_word=item["anchor"].text,
            anchor_word_index=item["anchor"].index,
            score=analysis["score"],
            layout=layout,
            graphic_bounds=graphic_bounds,
            speaker_bounds=speaker_bounds,
            speaker_shape=speaker_shape,
            accent_index=index % len(theme["accents"]),
            content=content,
            asset_path=asset.path if asset else None,
            motion="continuous-ease" if layout in {"stage_pip", "side_panel"} else "settled-reveal",
            speaker_crop_status=("unverified" if source_video and speaker_bounds else "not-applicable"),
            meaning_end_sec=_quantize(clause.end, fps_value),
        )
        cues.append(cue)
        previous_layout = layout

    plan = GraphicsPlan(
        schema_version=6,
        composition={
            "id": "graphics-main",
            "durationSeconds": _quantize(duration_value, fps_value),
            "fps": fps_value,
            "width": width_value,
            "height": height_value,
            "platform": platform_key,
            "platformStyle": profile["style"],
            "niche": niche_key,
            "treatmentMode": (
                "selected-contract"
                if treatment_tokens is not None
                else "draft-niche-heuristic"
            ),
            "goal": goal,
            "seed": int(seed),
            "captionsEnabled": bool(captions_enabled),
            "motionPolicy": "continuous transforms; no bounce, spin, glitch, or unmotivated loops",
            "timingPolicy": "preserve explanatory clause; prefer fewer cues over truncated meaning",
            "speakerCropVerification": {
                "status": "unverified" if source_video and any(cue.speaker_bounds for cue in cues) else "not-required",
                "method": "visual-review-required",
                "note": "No face/subject tracking is inferred from transcript timing alone.",
            },
        },
        theme=theme,
        safe_areas={
            "content": asdict(safe),
            "captions": asdict(caption) if captions_enabled else None,
            "captionPolicy": {
                "enabled": bool(captions_enabled),
                "heightFraction": float(profile["caption_height_fraction"]),
                "bottomMarginFraction": float(profile["safe_fractions"]["bottom"]),
                "source": "Captions_engine platform safe-area contract",
            },
            "platformUI": {
                "top": safe.y,
                "right": width_value - safe.right,
                "bottom": height_value - safe.bottom,
                "left": safe.x,
                "fractions": dict(profile["safe_fractions"]),
            },
        },
        source_video=str(Path(source_video).resolve()) if source_video else None,
        cues=cues,
        asset_catalog={
            "roots": sorted(str(Path(path).resolve()) for path in asset_dirs if path),
            "indexed": len(assets),
            "selected": sum(bool(cue.asset_path) for cue in cues),
            "memesAllowed": bool(allow_meme_assets),
        },
        treatment=(
            dict(treatment_provenance)
            if treatment_provenance is not None
            else (
                {"source": "inline-selected-treatment"}
                if treatment_tokens is not None
                else {
                    "source": "historical-niche-heuristic",
                    "approvalStatus": "draft-only",
                }
            )
        ),
    )
    plan.qa = validate_plan(plan, max_graphic_ratio=profile["max_graphic_ratio"])
    return plan


def _inside(inner: Rect, outer: Rect, tolerance: int = 1) -> bool:
    return (
        inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.right <= outer.right + tolerance
        and inner.bottom <= outer.bottom + tolerance
    )


def validate_plan(plan: GraphicsPlan, max_graphic_ratio: float | None = None) -> list[dict[str, Any]]:
    """Return machine-readable errors/warnings for timing, layout and density."""
    issues: list[dict[str, Any]] = []
    composition = plan.composition
    duration = float(composition["durationSeconds"])
    fps = int(composition["fps"])
    width = int(composition["width"])
    height = int(composition["height"])
    canvas = Rect(0, 0, width, height)
    safe = Rect(**plan.safe_areas["content"])
    caption_data = plan.safe_areas.get("captions")
    caption = Rect(**caption_data) if caption_data else None
    previous: GraphicCue | None = None
    layout_run = 0
    active_time = 0.0

    for cue in plan.cues:
        def issue(severity: str, code: str, message: str) -> None:
            issues.append({"severity": severity, "code": code, "cueId": cue.id, "message": message})

        if cue.start_sec < 0 or cue.end_sec > duration + 1e-4 or cue.end_sec <= cue.start_sec:
            issue("error", "timing_out_of_range", f"{cue.start_sec}..{cue.end_sec} outside 0..{duration}")
        if not (cue.start_sec - 1e-4 <= cue.anchor_sec <= cue.end_sec + 1e-4):
            issue("error", "anchor_outside_cue", "semantic anchor must occur during its graphic")
        if cue.meaning_end_sec is not None:
            if not math.isfinite(cue.meaning_end_sec) or cue.meaning_end_sec < cue.anchor_sec:
                issue("error", "invalid_meaning_end", "explanation end must be finite and follow its anchor")
            elif cue.end_sec + 1e-4 < cue.meaning_end_sec:
                issue("error", "meaning_hold_truncated", "graphic ends before its explanatory clause")
        for label, value in (("start", cue.start_sec), ("anchor", cue.anchor_sec), ("end", cue.end_sec)):
            if abs(value * fps - round(value * fps)) > 0.002:
                issue("error", "not_frame_quantized", f"{label}={value} is not aligned to {fps}fps")
        if not _inside(cue.graphic_bounds, canvas):
            issue("error", "graphic_outside_canvas", str(asdict(cue.graphic_bounds)))
        if cue.layout != "lower_third" and not _inside(cue.graphic_bounds, safe, tolerance=2):
            issue("error", "graphic_outside_safe_area", str(asdict(cue.graphic_bounds)))
        if cue.speaker_bounds and not _inside(cue.speaker_bounds, safe, tolerance=2):
            issue("error", "speaker_outside_safe_area", str(asdict(cue.speaker_bounds)))
        if (cue.speaker_bounds and cue.layout != "stage_pip"
                and cue.graphic_bounds.intersects(cue.speaker_bounds, padding=12)):
            issue("error", "layout_collision", "graphic and speaker bounds collide")
        if cue.speaker_bounds and plan.source_video and cue.speaker_crop_status != "verified":
            issue(
                "warning",
                "speaker_crop_unverified",
                "speaker window is geometry-only; confirm face/subject framing in the visual export review",
            )
        if caption and cue.graphic_bounds.intersects(caption, padding=16):
            issue("error", "caption_collision", "graphic intrudes into reserved caption region")
        if len(_tokens(cue.headline)) > 10:
            issue("warning", "headline_too_dense", "headline exceeds 10 words")
        if cue.asset_path and not Path(cue.asset_path).exists():
            issue("error", "missing_asset", cue.asset_path)
        if "proportion" in cue.content:
            proportion = cue.content["proportion"]
            if not isinstance(proportion, (int, float)) or not math.isfinite(float(proportion)) or not 0 <= float(proportion) <= 1:
                issue("error", "invalid_stat_proportion", "stat proportion must be a finite value in 0..1")
        if previous:
            if cue.start_sec < previous.end_sec - 1e-4:
                issue("error", "cue_overlap", f"overlaps {previous.id}")
            layout_run = layout_run + 1 if cue.layout == previous.layout else 1
            if layout_run > 2:
                issue("warning", "layout_repetition", "same layout used more than twice consecutively")
        else:
            layout_run = 1
        active_time += max(0.0, cue.duration)
        previous = cue

    if max_graphic_ratio is not None and duration > 0 and active_time / duration > max_graphic_ratio:
        issues.append({
            "severity": "warning",
            "code": "density_budget_exceeded",
            "cueId": None,
            "message": f"graphics occupy {active_time / duration:.0%}; platform budget is {max_graphic_ratio:.0%}",
        })
    if any(token in str(plan.to_dict()) for token in ("Math.random", "Date.now", "repeat: -1")):
        issues.append({
            "severity": "error", "code": "nondeterministic_motion", "cueId": None,
            "message": "plan contains a nondeterministic or infinite animation primitive",
        })
    return issues


def assert_plan_valid(plan: GraphicsPlan) -> None:
    errors = [issue for issue in plan.qa if issue["severity"] == "error"]
    if errors:
        rendered = "\n".join(f"- {item['code']}: {item['message']}" for item in errors)
        raise ValueError(f"graphics plan failed QA:\n{rendered}")

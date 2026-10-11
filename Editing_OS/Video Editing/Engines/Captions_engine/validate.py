"""Static caption-plan QA.

These checks gate timing, readability, hierarchy, deterministic layout metadata
and style contrast before a renderer is allowed to consume the caption plan.
Visual checks that require real frames are emitted as an explicit manual-review
contract rather than being silently claimed as automated.
"""

from __future__ import annotations

import json
import math
from collections import Counter


class CaptionValidationError(RuntimeError):
    """Raised when the caption plan fails a production QA invariant."""

    def __init__(self, report):
        self.report = report
        errors = report["summary"]["errors"]
        super().__init__(f"caption QA failed with {errors} error(s)")


def _issue(issues, severity, code, message, **context):
    item = {"severity": severity, "code": code, "message": message}
    if context:
        item["context"] = context
    issues.append(item)


def _hex_rgb(value):
    value = str(value).lstrip("#")
    if len(value) != 6:
        raise ValueError(value)
    return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


def _luminance(value):
    channels = []
    for channel in _hex_rgb(value):
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def build_qa_report(words, segments, cfg, profile):
    issues = []
    words = list(words)
    segments = list(segments)

    if not words:
        _issue(issues, "error", "WORDS_EMPTY", "No aligned spoken words were supplied.")
    if not segments:
        _issue(issues, "error", "SEGMENTS_EMPTY", "No caption segments were produced.")

    timing_sources = Counter()
    low_confidence = 0
    for index, word in enumerate(words):
        source = str(word.get("timing_source", "unknown"))
        timing_sources[source] += 1
        start, end = word.get("start"), word.get("end")
        if not (_finite(start) and _finite(end)):
            _issue(
                issues, "error", "WORD_TIME_INVALID", "Word timing is not finite.",
                word_index=index, text=word.get("text"),
            )
            continue
        if start < 0:
            _issue(
                issues, "error", "WORD_TIME_NEGATIVE", "Word starts before zero.",
                word_index=index, text=word.get("text"), start=start,
            )
        if end <= start:
            _issue(
                issues, "error", "WORD_DURATION_INVALID", "Word duration must be positive.",
                word_index=index, text=word.get("text"), start=start, end=end,
            )
        if index:
            previous = words[index - 1]
            if _finite(previous.get("start")) and start + 1e-9 < previous["start"]:
                _issue(
                    issues, "error", "WORD_ORDER", "Word starts are not monotonic.",
                    word_index=index, text=word.get("text"),
                )
            overlap = previous.get("end", start) - start
            if _finite(overlap) and overlap > cfg.timing_tolerance:
                _issue(
                    issues, "error", "WORD_OVERLAP", "Adjacent word timing overlaps beyond tolerance.",
                    word_index=index, overlap_ms=round(overlap * 1000, 1),
                    tolerance_ms=round(cfg.timing_tolerance * 1000, 1),
                )
        if float(word.get("score", 1.0)) < 0.40:
            low_confidence += 1

    approximated = sum(
        count
        for source, count in timing_sources.items()
        if source.startswith("script-")
    )
    if approximated:
        _issue(
            issues,
            "warning",
            "APPROXIMATE_SCRIPT_TIMING",
            "Corrected-script words use interpolated timing; review their sync at waveform level.",
            words=approximated,
        )
    raw_whisper = sum(
        count
        for source, count in timing_sources.items()
        if source.startswith("whisper-word-timestamp")
    )
    if raw_whisper:
        _issue(
            issues,
            "warning",
            "RAW_WHISPER_TIMING",
            "Raw Whisper word timestamps are lower-confidence than forced alignment; review every cut at waveform level.",
            words=raw_whisper,
        )
    if low_confidence:
        _issue(
            issues,
            "warning",
            "LOW_ALIGNMENT_CONFIDENCE",
            "Low-confidence words require transcript and waveform review.",
            words=low_confidence,
        )

    flattened = []
    display_durations = []
    for index, segment in enumerate(segments):
        seg_words = segment.get("words", [])
        flattened.extend(seg_words)
        if not seg_words:
            _issue(issues, "error", "SEGMENT_EMPTY", "Caption segment contains no words.", segment=index)
            continue
        speech_start = segment.get("speech_start", segment.get("start"))
        speech_end = segment.get("speech_end", segment.get("end"))
        display_start = segment.get("display_start", speech_start)
        display_end = segment.get("display_end", speech_end)
        if abs(speech_start - seg_words[0]["start"]) > 0.001 or abs(
            speech_end - seg_words[-1]["end"]
        ) > 0.001:
            _issue(
                issues, "error", "SEGMENT_ENVELOPE", "Speech window must match its first/last word.",
                segment=index,
            )
        if display_start > speech_start + 0.001 or display_end < speech_end - 0.001:
            _issue(
                issues, "error", "DISPLAY_ENVELOPE", "Display window must envelop all spoken words.",
                segment=index,
            )
        display_duration = display_end - display_start
        display_durations.append(display_duration)
        if display_duration + 0.015 < cfg.min_caption_dur:
            _issue(
                issues, "error", "MIN_EXPOSURE", "Caption is too brief to read.",
                segment=index, duration=round(display_duration, 3), minimum=cfg.min_caption_dur,
            )
        required = float(segment.get("required_read_duration", cfg.min_caption_dur))
        if display_duration + 0.05 < required:
            _issue(
                issues, "warning", "READING_TIME", "Spoken cadence leaves less than the estimated reading time.",
                segment=index, duration=round(display_duration, 3), required=round(required, 3),
            )

        lines = segment.get("lines", [])
        if len(lines) > cfg.max_lines:
            _issue(
                issues, "error", "LINE_COUNT", "Caption exceeds the maximum line count.",
                segment=index, lines=len(lines), maximum=cfg.max_lines,
            )
        for line_index, line in enumerate(lines):
            chars = sum(len(word["text"]) for word in line) + max(0, len(line) - 1)
            if chars > cfg.max_chars_per_line and len(line) > 1:
                _issue(
                    issues, "error", "LINE_WIDTH", "Caption line exceeds its character budget.",
                    segment=index, line=line_index, chars=chars, maximum=cfg.max_chars_per_line,
                )
        line_words = [word for line in lines for word in line]
        if [word["text"] for word in line_words] != [word["text"] for word in seg_words]:
            _issue(
                issues, "error", "LINE_WORD_ORDER", "Wrapped lines do not preserve segment word order.",
                segment=index,
            )
        emphasized = [word for word in seg_words if word.get("emphasis")]
        if len(emphasized) > cfg.max_emphasis_words:
            _issue(
                issues, "error", "EMPHASIS_DENSITY", "Too many primary emphasis words in one caption.",
                segment=index, count=len(emphasized), maximum=cfg.max_emphasis_words,
            )

        if index + 1 < len(segments):
            next_start = segments[index + 1].get(
                "display_start", segments[index + 1].get("speech_start", segments[index + 1]["start"])
            )
            if display_end > next_start + 1e-6:
                _issue(
                    issues, "error", "DISPLAY_OVERLAP", "Caption display windows overlap.",
                    segment=index, overlap_ms=round((display_end - next_start) * 1000, 1),
                )

    original_text = [word.get("text") for word in words]
    flattened_text = [word.get("text") for word in flattened]
    if original_text != flattened_text:
        _issue(
            issues, "error", "WORD_COVERAGE", "Caption segmentation dropped, duplicated, or reordered words."
        )

    safe = profile.get("safe_area", {})
    for axis in ("top", "right", "bottom", "left"):
        value = safe.get(axis)
        if not _finite(value) or not 0 <= value < 0.5:
            _issue(
                issues, "error", "SAFE_AREA", "Safe-area fraction is missing or invalid.",
                edge=axis, value=value,
            )
    if _finite(safe.get("left")) and _finite(safe.get("right")) and safe["left"] + safe["right"] >= 0.75:
        _issue(issues, "error", "SAFE_AREA_WIDTH", "Safe-area side margins leave too little caption width.")

    outline_px = profile.get("outline_px", 0)
    check_outline_contrast = _finite(outline_px) and float(outline_px) > 0
    for color_name in ("primary", "accent"):
        try:
            ratio = _contrast(profile[color_name], profile["outline"])
        except (KeyError, ValueError):
            _issue(
                issues, "error", "STYLE_COLOR", "Style profile contains an invalid color.",
                color=color_name,
            )
            continue
        if check_outline_contrast and ratio < 4.5:
            _issue(
                issues, "error", "STYLE_CONTRAST", "Text-to-outline contrast is below WCAG AA.",
                color=color_name, ratio=round(ratio, 2), minimum=4.5,
            )

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "schema": "arete-caption-qa/v1",
        "status": status,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "words": len(words),
            "segments": len(segments),
            "approximate_timing_words": approximated,
            "minimum_display_duration": round(min(display_durations), 3) if display_durations else None,
            "maximum_display_duration": round(max(display_durations), 3) if display_durations else None,
        },
        "timing_sources": dict(sorted(timing_sources.items())),
        "style": {
            "name": profile.get("name"),
            "platform": profile.get("platform"),
            "safe_area": safe,
            "safe_area_px": profile.get("safe_area_px"),
        },
        "activation_contract": {
            "timing_basis": "absolute-word-onsets",
            "maximum_export_onset_error_frames": 1,
            "review_fps": 30,
            "stable_phrase_layout": True,
            "phone_review_scale": 0.5,
            "font_size_px": profile.get("font_size_px", profile.get("font_size")),
            "status": "export-review-required",
        },
        "issues": issues,
        "manual_review": [
            "Check final-frame contrast over bright, busy, and changing backgrounds.",
            "Check that captions never cover eyes, mouth, products, or critical graphics.",
            "Overlay the current platform UI and verify the declared safe area on a phone.",
            "At first, middle, and last caption beats, confirm the activated word lands within one output frame of the voice onset.",
            "Review the encoded export at 50% linear scale; every active and resting word must remain immediately legible.",
            "Confirm word activation changes emphasis without reflowing or jumping the full phrase layout.",
            "Review every approximate or low-confidence word against waveform and speech.",
            "Watch once normally and once muted; confirm hierarchy, comprehension, and restraint.",
        ],
    }


def raise_for_errors(report):
    if report["summary"]["errors"]:
        raise CaptionValidationError(report)


def dumps_report(report):
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

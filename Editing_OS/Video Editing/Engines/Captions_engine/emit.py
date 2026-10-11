"""Deterministic ASS and HyperFrames caption emitters."""

from __future__ import annotations

import hashlib
import json

from phrasing import canonical_platform


STYLE_PROFILES = {
    "instagram-reels": {
        "name": "arete-reels-designed",
        "font": "Arial",
        "font_size": 54,
        "primary": "#FFFFFF",
        "accent": "#65E6FF",
        "outline": "#071018",
        "outline_px": 3.2,
        "shadow_px": 1.0,
        "emphasis_scale": 118,
        "entry_ms": 120,
        "exit_ms": 90,
        "safe_area": {"top": 0.10, "right": 0.18, "bottom": 0.20, "left": 0.07},
        "motion": "scale-settle",
        "density": "designed",
    },
    "tiktok": {
        "name": "arete-tiktok-native",
        "font": "Arial",
        "font_size": 52,
        "primary": "#FFFFFF",
        "accent": "#FFEA3A",
        "outline": "#050505",
        "outline_px": 4.0,
        "shadow_px": 1.0,
        "emphasis_scale": 124,
        "entry_ms": 95,
        "exit_ms": 70,
        "safe_area": {"top": 0.11, "right": 0.19, "bottom": 0.23, "left": 0.07},
        "motion": "native-pop",
        "density": "raw-native",
    },
    "youtube-shorts": {
        "name": "arete-shorts-clean",
        "font": "Arial",
        "font_size": 50,
        "primary": "#FFFFFF",
        "accent": "#78E7FF",
        "outline": "#071018",
        "outline_px": 3.0,
        "shadow_px": 1.0,
        "emphasis_scale": 112,
        "entry_ms": 110,
        "exit_ms": 80,
        "safe_area": {"top": 0.09, "right": 0.17, "bottom": 0.18, "left": 0.07},
        "motion": "clean-settle",
        "density": "legible-clean",
    },
    "x": {
        "name": "arete-x-information",
        "font": "Arial",
        "font_size": 43,
        "primary": "#FFFFFF",
        "accent": "#9ADFFF",
        "outline": "#071018",
        "outline_px": 2.5,
        "shadow_px": 0.8,
        "emphasis_scale": 108,
        "entry_ms": 100,
        "exit_ms": 70,
        "safe_area": {"top": 0.07, "right": 0.08, "bottom": 0.14, "left": 0.08},
        "motion": "precision-fade",
        "density": "information-forward",
    },
    "youtube": {
        "name": "arete-youtube-clean",
        "font": "Arial",
        "font_size": 47,
        "primary": "#FFFFFF",
        "accent": "#78E7FF",
        "outline": "#071018",
        "outline_px": 3.0,
        "shadow_px": 1.0,
        "emphasis_scale": 110,
        "entry_ms": 120,
        "exit_ms": 90,
        "safe_area": {"top": 0.06, "right": 0.06, "bottom": 0.11, "left": 0.06},
        "motion": "clean-settle",
        "density": "legible-clean",
    },
    "generic": {
        "name": "arete-compatible",
        "font": "Arial",
        "font_size": 48,
        "primary": "#FFFFFF",
        "accent": "#FFFF00",
        "outline": "#000000",
        "outline_px": 3.0,
        "shadow_px": 1.0,
        "emphasis_scale": 135,
        "entry_ms": 120,
        "exit_ms": 90,
        "safe_area": {"top": 0.05, "right": 0.04, "bottom": 0.08, "left": 0.04},
        "motion": "arete-bounce",
        "density": "compatible",
    },
}


def available_platforms():
    return tuple(sorted(STYLE_PROFILES))


def get_style_profile(platform="instagram-reels", playres=(1080, 1920), overrides=None):
    platform = canonical_platform(platform)
    profile = dict(STYLE_PROFILES[platform])
    profile["safe_area"] = dict(profile["safe_area"])
    for key, value in (overrides or {}).items():
        if value is not None:
            profile[key] = value

    width, height = playres
    # Caption type is authored against a 1080px short edge. This keeps the
    # authored size at both platform-native 1080x1920 and 1920x1080 instead of
    # incorrectly shrinking landscape YouTube captions by portrait height.
    reference_scale = min(width, height) / 1080.0
    profile["font_size_px"] = max(18, int(round(float(profile["font_size"]) * reference_scale)))
    profile["safe_area_px"] = {
        "top": int(round(height * profile["safe_area"]["top"])),
        "right": int(round(width * profile["safe_area"]["right"])),
        "bottom": int(round(height * profile["safe_area"]["bottom"])),
        "left": int(round(width * profile["safe_area"]["left"])),
    }
    profile["platform"] = platform
    profile["playres"] = {"width": width, "height": height}
    return profile


def _ass_color(hex_color, alpha="00"):
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB color, got {hex_color!r}")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha}{blue}{green}{red}"


def _ass_header(profile, fingerprint):
    resolution = profile["playres"]
    safe = profile["safe_area_px"]
    return f"""[Script Info]
Title: ARETE Captions - {profile['platform']}
; SourceFingerprint: {fingerprint}
ScriptType: v4.00+
PlayResX: {resolution['width']}
PlayResY: {resolution['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{profile['font']},{profile['font_size_px']},{_ass_color(profile['primary'])},{_ass_color(profile['primary'])},{_ass_color(profile['outline'])},&H80000000,1,0,0,0,100,100,1,0,1,{profile['outline_px']},{profile['shadow_px']},2,{safe['left']},{safe['right']},{safe['bottom']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds):
    seconds = max(0.0, float(seconds))
    centiseconds = int(round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _safe_text(text):
    """Escape transcript text for an ASS dialogue field.

    A zero-width word joiner after each transcript backslash prevents libass
    from recognizing sequences such as ``\\N``/``\\h`` while preserving the
    visible slash. Braces use libass's literal-brace escape, so ``{\\b1}``
    cannot become an override block. Newlines are flattened because wrapping
    is owned by ``segment['lines']``.
    """
    return (
        str(text)
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\\", "\\\u2060")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _ass_word(word, seg_start, next_start, profile):
    relative_ms = max(0, int(round((word["start"] - seg_start) * 1000)))
    karaoke_end = next_start if next_start is not None else word["end"]
    karaoke_cs = max(1, int(round((karaoke_end - word["start"]) * 100)))
    emphasis = bool(word.get("emphasis"))
    color = profile["accent"] if emphasis else profile["primary"]
    scale = int(profile["emphasis_scale"]) if emphasis else 100
    settle = min(int(profile["entry_ms"]), max(45, karaoke_cs * 5))

    tags = [
        "\\alpha&H00&" if relative_ms == 0 else "\\alpha&HFF&",
        f"\\1c{_ass_color(color)}",
        f"\\2c{_ass_color(color)}",
        "\\b1",
        "\\fscx100",
        f"\\fscy{scale}",
    ]
    if relative_ms > 0:
        tags.append(f"\\t({relative_ms},{relative_ms + 1},\\alpha&H00&)")
    if emphasis:
        tags.append(
            f"\\t({relative_ms},{relative_ms + settle},\\fscy100)"
        )
    tags.append(f"\\kf{karaoke_cs}")
    return "{" + "".join(tags) + "}" + _safe_text(word["text"])


def _ass_text(segment, profile):
    words = segment["words"]
    next_start = {
        index: words[index + 1]["start"] if index + 1 < len(words) else None
        for index in range(len(words))
    }
    positions = {id(word): index for index, word in enumerate(words)}
    rendered_lines = []
    for line in segment["lines"]:
        rendered = []
        for word in line:
            index = positions.get(id(word))
            if index is None:
                # Defensive lookup for callers that copied line dictionaries.
                index = words.index(word)
            rendered.append(
                _ass_word(word, segment["speech_start"], next_start[index], profile)
            )
        rendered_lines.append(" ".join(rendered))
    return "\\N".join(rendered_lines)


def to_ass(segments, cfg, playres=(1080, 1920), profile=None, style_overrides=None):
    profile = profile or get_style_profile(
        getattr(cfg, "platform", "generic"), playres, style_overrides
    )
    body = []
    for segment in segments:
        body.append(
            "Dialogue: 0,{start},{end},Default,,0,0,0,,{text}".format(
                start=_ts(segment.get("display_start", segment["start"])),
                end=_ts(segment.get("display_end", segment["end"])),
                text=_ass_text(segment, profile),
            )
        )
    return _ass_header(profile, source_fingerprint(segments, cfg, profile)) + "\n".join(body) + "\n"


def _ass_word_popup(word, profile):
    """A word rendered as a static (non-karaoke) block member: colored, no per-word timing."""
    emphasis = bool(word.get("emphasis"))
    color = profile["accent"] if emphasis else profile["primary"]
    return f"{{\\1c{_ass_color(color)}\\2c{_ass_color(color)}\\b1}}" + _safe_text(word["text"])


def _ass_text_popup(segment, profile):
    """Whole-phrase pop-in: the caption appears as one block (no per-word karaoke fill),
    scale+fade in fast, holds static while spoken, then pops out. This is the
    'pop-up caption' look (TikTok/Reels-style phrase pop), distinct from ARETE's
    continuous per-word karaoke sweep.
    """
    lines = []
    for line in segment["lines"]:
        lines.append(" ".join(_ass_word_popup(word, profile) for word in line))
    text = "\\N".join(lines)

    start = segment.get("display_start", segment["start"])
    end = segment.get("display_end", segment["end"])
    duration_cs = max(1, int(round((end - start) * 100)))
    pop_in_cs = min(12, max(6, duration_cs // 6))
    pop_out_cs = min(8, max(4, duration_cs // 10))
    pop_out_at = max(pop_in_cs, duration_cs - pop_out_cs)

    entry = (
        f"\\fscx72\\fscy72\\alpha&HFF&"
        f"\\t(0,{pop_in_cs},\\fscx100\\fscy100\\alpha&H00&)"
    )
    exit_ = f"\\t({pop_out_at},{duration_cs},\\fscx88\\fscy88\\alpha&HFF&)"
    return "{" + entry + exit_ + "}" + text


def to_ass_popup(segments, cfg, playres=(1080, 1920), profile=None, style_overrides=None):
    """Pop-up caption variant: one phrase on screen at a time, no karaoke fill."""
    profile = profile or get_style_profile(
        getattr(cfg, "platform", "generic"), playres, style_overrides
    )
    body = []
    for segment in segments:
        body.append(
            "Dialogue: 0,{start},{end},Default,,0,0,0,,{text}".format(
                start=_ts(segment.get("display_start", segment["start"])),
                end=_ts(segment.get("display_end", segment["end"])),
                text=_ass_text_popup(segment, profile),
            )
        )
    return _ass_header(profile, source_fingerprint(segments, cfg, profile)) + "\n".join(body) + "\n"


def _round(value):
    return round(float(value), 3)


def source_fingerprint(segments, cfg, profile):
    material = {
        "config": {
            key: value
            for key, value in vars(cfg).items()
            if isinstance(value, (str, int, float, bool, type(None)))
        },
        "platform": profile["platform"],
        "playres": profile["playres"],
        "words": [
            [word["text"], _round(word["start"]), _round(word["end"])]
            for segment in segments
            for word in segment["words"]
        ],
    }
    payload = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_hyperframes(segments, cfg, playres=(1080, 1920), profile=None, style_overrides=None):
    profile = profile or get_style_profile(
        getattr(cfg, "platform", "generic"), playres, style_overrides
    )
    clips = []
    for index, segment in enumerate(segments):
        display_start = segment.get("display_start", segment["start"])
        display_end = segment.get("display_end", segment["end"])
        clips.append(
            {
                "id": f"caption-{index + 1:04d}",
                "index": index,
                "start": _round(display_start),
                "end": _round(display_end),
                "dur": _round(display_end - display_start),
                "speech_start": _round(segment.get("speech_start", segment["start"])),
                "speech_end": _round(segment.get("speech_end", segment["end"])),
                "required_read_duration": _round(segment.get("required_read_duration", 0.0)),
                "reading_behavior": segment.get("reading_behavior", "skimming"),
                "lines": [[word["text"] for word in line] for line in segment["lines"]],
                "emphasis": segment.get("emphasis", []),
                "words": [
                    {
                        "text": word["text"],
                        "start": _round(word["start"]),
                        "end": _round(word["end"]),
                        "rel_start": _round(word["start"] - display_start),
                        "rel_end": _round(word["end"] - display_start),
                        "score": round(float(word.get("score", 1.0)), 3),
                        "timing_source": word.get("timing_source", "provided"),
                        "role": word.get("role", "meaning"),
                        "emphasis": bool(word.get("emphasis", False)),
                        "emphasis_score": round(float(word.get("emphasis_score", 0.0)), 3),
                        "emphasis_kind": word.get("emphasis_kind"),
                        "motion_tier": int(word.get("motion_tier", 1)),
                    }
                    for word in segment["words"]
                ],
            }
        )
    return {
        "schema": "hyperframes-captions/v1",
        "schema_revision": 2,
        "style": profile["name"],
        "platform": profile["platform"],
        "source_fingerprint": source_fingerprint(segments, cfg, profile),
        "count": len(clips),
        "style_profile": profile,
        "clips": clips,
    }


def dumps_hyperframes(segments, cfg, playres=(1080, 1920), profile=None, style_overrides=None):
    data = to_hyperframes(segments, cfg, playres, profile, style_overrides)
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def dump_hyperframes(segments, cfg, path, playres=(1080, 1920), profile=None, style_overrides=None):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps_hyperframes(segments, cfg, playres, profile, style_overrides))

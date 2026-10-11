"""Pure-Python production tests. Run: ``python engine.py --selftest``."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path

import align
import emit
import engine
import validate
from phrasing import Config, segment_words


def _words(tokens, dur=0.25, gap=0.05, start=0.0, source="test-forced"):
    if isinstance(tokens, str):
        tokens = tokens.split()
    words = []
    time = start
    for text in tokens:
        words.append(
            {
                "text": text,
                "start": round(time, 3),
                "end": round(time + dur, 3),
                "score": 1.0,
                "timing_source": source,
            }
        )
        time += dur + gap
    return words


def _cfg(platform="instagram-reels", **overrides):
    return Config.for_platform(platform, **overrides)


def test_sentence_breaks():
    words = _words("It is official. Family and friends gathered today.")
    segments = segment_words(words, _cfg())
    assert any(segment["words"][-1]["text"] == "official." for segment in segments)
    return "sentence_breaks"


def test_clause_semantic_boundary():
    words = _words("I tried everything, but nothing worked until I found one method.")
    segments = segment_words(words, _cfg())
    phrases = [[word["text"] for word in segment["words"]] for segment in segments]
    assert phrases[0][-1] == "everything,", phrases
    assert phrases[1][0] == "but", phrases
    return "clause_semantics"


def test_no_dangling_function_word():
    words = _words("I wanted to become a much better storyteller through practice.")
    segments = segment_words(words, _cfg(max_words_per_caption=5))
    endings = [segment["words"][-1]["text"].casefold() for segment in segments[:-1]]
    assert not ({"a", "an", "the", "to", "of", "for", "with"} & set(endings)), endings
    return "phrase_glue"


def test_budget_never_exceeded():
    cfg = _cfg(max_chars_per_line=16, max_lines=2, max_caption_dur=10, max_words_per_caption=7)
    segments = segment_words(_words([f"word{i}" for i in range(40)]), cfg)
    for segment in segments:
        assert len(segment["lines"]) <= cfg.max_lines
        for line in segment["lines"]:
            chars = sum(len(word["text"]) for word in line) + max(0, len(line) - 1)
            assert chars <= cfg.max_chars_per_line, (chars, line)
    return "line_budget"


def test_balanced_natural_wrap():
    cfg = _cfg(max_chars_per_line=14, max_words_per_caption=7)
    segment = segment_words(_words("build a better story today"), cfg)[0]
    assert len(segment["lines"]) == 2
    assert segment["lines"][0][-1]["text"] != "a"
    return "balanced_wrap"


def test_pause_splits():
    words = _words("hello there")
    words.append({"text": "friend", "start": 5.0, "end": 5.3, "score": 1.0, "timing_source": "test"})
    segments = segment_words(words, _cfg())
    assert len(segments) == 2
    return "pause_split"


def test_max_duration_splits():
    cfg = _cfg(max_caption_dur=1.0, max_chars_per_line=100, max_words_per_caption=20)
    segments = segment_words(_words("a b c d e f g h", dur=0.3, gap=0.0), cfg)
    assert len(segments) >= 2
    assert all(segment["speech_end"] - segment["speech_start"] <= 1.0 + 1e-6 for segment in segments)
    return "max_duration"


def test_micro_caption_merges_for_readability():
    words = [
        {"text": "No.", "start": 0.0, "end": 0.18, "score": 1.0, "timing_source": "test"},
        {"text": "Keep", "start": 0.23, "end": 0.45, "score": 1.0, "timing_source": "test"},
        {"text": "going.", "start": 0.48, "end": 0.72, "score": 1.0, "timing_source": "test"},
    ]
    segments = segment_words(words, _cfg())
    assert len(segments) == 1, segments
    assert segments[0]["display_duration"] >= 0.75
    return "micro_merge"


def test_display_handoff_never_overlaps():
    words = _words("This works. Now keep going.", dur=0.34, gap=0.08)
    segments = segment_words(words, _cfg())
    for first, second in zip(segments, segments[1:]):
        assert first["display_end"] <= second["display_start"]
    assert all(segment["display_duration"] >= 0.75 - 1e-6 for segment in segments)
    return "display_handoff"


def test_micro_connector_borrows_adjacent_handoff_window():
    words = [
        {"text": "Always", "start": 0.0, "end": 0.30, "score": 1.0, "timing_source": "test"},
        {"text": "works.", "start": 0.34, "end": 1.30, "score": 1.0, "timing_source": "test"},
        {"text": "Because", "start": 1.54, "end": 1.68, "score": 1.0, "timing_source": "test"},
        {"text": "that's", "start": 1.70, "end": 1.84, "score": 1.0, "timing_source": "test"},
        {"text": "the", "start": 1.86, "end": 1.96, "score": 1.0, "timing_source": "test"},
        {"text": "way.", "start": 1.98, "end": 2.08, "score": 1.0, "timing_source": "test"},
        {"text": "You'll", "start": 2.12, "end": 2.30, "score": 1.0, "timing_source": "test"},
        {"text": "understand", "start": 2.34, "end": 3.20, "score": 1.0, "timing_source": "test"},
    ]
    cfg = _cfg(max_chars_per_line=12, max_words_per_caption=4)
    segments = segment_words(words, cfg)
    assert len(segments) == 3, segments
    middle = segments[1]
    assert middle["display_start"] == segments[0]["speech_end"]
    assert middle["display_end"] == segments[2]["speech_start"]
    assert middle["display_duration"] >= cfg.min_caption_dur - 0.015
    assert all(
        left["display_end"] <= right["display_start"]
        for left, right in zip(segments, segments[1:])
    )
    return "micro_handoff_borrow"


def test_meaning_word_emphasis_is_scarce():
    cfg = _cfg(max_emphasis_words=1)
    segment = segment_words(_words("This mistake cost exactly $10,000 yesterday."), cfg)[0]
    emphasized = [word for word in segment["words"] if word["emphasis"]]
    assert len(emphasized) == 1
    assert emphasized[0]["text"] == "$10,000", emphasized
    assert emphasized[0]["motion_tier"] == 3
    return "scarce_emphasis"


def test_function_words_not_emphasized():
    segment = segment_words(_words("the and to of in"), _cfg())[0]
    assert not any(word["emphasis"] for word in segment["words"])
    return "functional_restraint"


def test_force_align_fixes_name():
    asr = _words("written by rev doctor arden marlo")
    fixed = align.force_align_to_script(asr, "Written by Rev. Dr. Arden Marlowe")
    assert [word["text"] for word in fixed][-1] == "Marlowe"
    assert all(word["start"] is not None and word["end"] is not None for word in fixed)
    assert fixed[-1]["end"] <= asr[-1]["end"] + 1e-6
    return "corrected_name"


def test_force_align_insert_is_positive_and_monotonic():
    asr = _words("north press")
    fixed = align.force_align_to_script(asr, "NorthStar Press Publishing")
    assert [word["text"] for word in fixed] == ["NorthStar", "Press", "Publishing"]
    assert all(word["end"] > word["start"] for word in fixed)
    assert all(left["end"] <= right["start"] + 1e-6 for left, right in zip(fixed, fixed[1:]))
    assert fixed[-1]["end"] <= asr[-1]["end"] + 1e-6
    assert fixed[-1]["timing_source"] == "script-interpolated"
    return "script_interpolation"


def test_force_align_rejects_unrelated_script():
    asr = _words("the real spoken sentence has clear transcript anchors")
    try:
        align.force_align_to_script(asr, "Completely unrelated marketing copy replaces every single word")
    except align.AlignmentError:
        return "unrelated_script_refused"
    raise AssertionError("unrelated script should not receive fabricated timing")


def test_force_align_rejects_one_anchor_in_five_tokens():
    asr = _words("we build better stories today")
    try:
        align.force_align_to_script(asr, "We captured orange galaxies silently")
    except align.AlignmentError:
        return "one_of_five_refused"
    raise AssertionError("one shared token out of five is not correction evidence")


def test_force_align_rejects_shortened_source_script():
    asr = _words("we built a very fast system that saves your time")
    try:
        align.force_align_to_script(asr, "we built system time")
    except align.AlignmentError as exc:
        assert "omits aligned spoken token" in str(exc)
        return "source_shortening_refused"
    raise AssertionError("a corrected script cannot silently shorten audible speech")


def test_force_align_rejects_omitted_middle_word():
    asr = _words("we built a very fast system")
    try:
        align.force_align_to_script(asr, "we built a fast system")
    except align.AlignmentError as exc:
        assert "very" in str(exc)
        return "middle_word_omission_refused"
    raise AssertionError("omitting one audible word must fail closed")


def test_force_align_allows_tokenization_only_merge():
    asr = _words("published by north star press")
    fixed = align.force_align_to_script(asr, "Published by NorthStar Press")
    assert [word["text"] for word in fixed] == ["Published", "by", "NorthStar", "Press"]
    assert fixed[2]["timing_source"] == "script-tokenization"
    assert fixed[2]["start"] == asr[2]["start"]
    assert fixed[2]["end"] == asr[3]["end"]
    cfg = _cfg()
    report = validate.build_qa_report(
        fixed, segment_words(fixed, cfg), cfg, emit.get_style_profile(cfg.platform)
    )
    assert any(
        issue["code"] == "APPROXIMATE_SCRIPT_TIMING"
        for issue in report["issues"]
    )
    return "tokenization_merge"


def test_auto_requires_forced_alignment():
    original_whisperx = align._whisperx
    original_whisper = align._whisper
    raw_called = []

    def missing_whisperx(audio, model):
        raise ModuleNotFoundError("whisperx")

    def unexpected_whisper(audio, model):
        raw_called.append(True)
        return _words("must not run")

    align._whisperx = missing_whisperx
    align._whisper = unexpected_whisper
    try:
        try:
            align.transcribe_words("audio.wav", backend="auto")
        except align.AlignmentError as exc:
            assert "required for production forced alignment" in str(exc)
        else:
            raise AssertionError("auto must fail instead of silently using raw Whisper")
        assert not raw_called
    finally:
        align._whisperx = original_whisperx
        align._whisper = original_whisper
    return "auto_forced_only"


def test_explicit_whisper_is_lower_confidence():
    original_whisper = align._whisper
    align._whisper = lambda audio, model: [
        {key: value for key, value in word.items() if key != "timing_source"}
        for word in _words("diagnostic timing")
    ]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            words = align.transcribe_words("audio.wav", backend="whisper")
        assert caught and "lower-confidence" in str(caught[0].message)
        assert all(
            word["timing_source"] == "whisper-word-timestamp-low-confidence"
            for word in words
        )
        cfg = _cfg()
        report = validate.build_qa_report(
            words, segment_words(words, cfg), cfg, emit.get_style_profile(cfg.platform)
        )
        assert any(issue["code"] == "RAW_WHISPER_TIMING" for issue in report["issues"])
    finally:
        align._whisper = original_whisper
    return "explicit_whisper_warning"


def test_empty_alignment_refused():
    try:
        align.normalize_words([])
    except align.AlignmentError:
        return "empty_alignment_refused"
    raise AssertionError("empty alignment should fail")


def test_abbrev_no_false_break():
    segments = segment_words(_words("a new book by Rev. Dr. Arden Marlowe."), _cfg())
    for segment in segments:
        text = [word["text"] for word in segment["words"]]
        assert text not in (["Dr."], ["Rev."])
    return "abbreviation_guard"


def test_ass_exact_reveal_and_safe_area():
    cfg = _cfg()
    segments = segment_words(_words("It really works.", dur=0.25, gap=0.05), cfg)
    profile = emit.get_style_profile(cfg.platform)
    ass = emit.to_ass(segments, cfg, profile=profile)
    assert "Title: ARETE Captions - instagram-reels" in ass
    assert "\\alpha&HFF&" in ass and "\\t(300,301,\\alpha&H00&)" in ass
    assert "\\kf" in ass
    assert f",{profile['safe_area_px']['bottom']},1" in ass
    assert "\\fscy118" in ass, "meaning-word emphasis should use the Reels scale profile"
    accent = emit._ass_color(profile["accent"])
    assert ass.count(f"\\1c{accent}") == 1, "only the selected meaning word may use the accent"
    return "ass_word_sync"


def test_ass_karaoke_preserves_uneven_gaps():
    words = [
        {"text": "First", "start": 0.0, "end": 0.20, "score": 1.0, "timing_source": "forced"},
        {"text": "then", "start": 0.42, "end": 0.62, "score": 1.0, "timing_source": "forced"},
        {"text": "last.", "start": 1.03, "end": 1.20, "score": 1.0, "timing_source": "forced"},
    ]
    cfg = _cfg(max_gap_join=0.70)
    segments = segment_words(words, cfg)
    assert len(segments) == 1
    ass = emit.to_ass(segments, cfg)
    # Karaoke periods are onset-to-onset (42cs, then 61cs), not spoken durations.
    assert "\\kf42" in ass and "\\kf61" in ass, ass
    assert "\\t(420,421,\\alpha&H00&)" in ass
    assert "\\t(1030,1031,\\alpha&H00&)" in ass
    return "ass_gap_alignment"


def test_ass_transcript_text_is_escaped():
    unsafe = "Use {braces} C:\\new\\Npath {\\b1} literally"
    escaped = emit._safe_text(unsafe)
    assert "\\N" not in escaped.replace("\\\u2060", ""), escaped
    assert "\\{braces\\}" in escaped
    assert "{\\b1}" not in escaped
    assert "\\\u2060N" in escaped
    return "ass_text_escape"


def test_libass_escape_smoke():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return "libass_escape_smoke_skipped"

    with tempfile.TemporaryDirectory() as directory:
        ass_path = Path(directory) / "escape-smoke.ass"
        text = emit._safe_text("A\\NB {\\b1}C")
        ass_path.write_text(
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 640\nPlayResY: 360\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,0,0,5,10,10,10,1\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{text}\n",
            encoding="utf-8",
        )
        filter_path = str(ass_path).replace("\\", "/").replace(":", "\\:")
        completed = subprocess.run(
            [
                ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=black:s=640x360:d=1", "-vf",
                f"subtitles='{filter_path}'", "-frames:v", "1", "-f",
                "rawvideo", "-pix_fmt", "gray", "pipe:1",
            ],
            check=True,
            capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        bright_rows = {
            index // 640 for index, value in enumerate(completed.stdout) if value > 20
        }
        assert bright_rows, "libass rendered no transcript glyphs"
        # An unsafe A\\NB event is roughly 67px tall at this style. Escaping must
        # preserve a single text line even with braces and an override-like tag.
        assert max(bright_rows) - min(bright_rows) + 1 < 50, bright_rows
    return "libass_escape_smoke"


def test_hyperframes_rich_contract():
    cfg = _cfg("youtube-shorts")
    segments = segment_words(_words("one important number is 42."), cfg)
    data = emit.to_hyperframes(segments, cfg)
    assert data["schema"] == "hyperframes-captions/v1"
    assert data["schema_revision"] == 2
    assert data["platform"] == "youtube-shorts"
    assert data["style_profile"]["safe_area"]["right"] == 0.17
    clip = data["clips"][0]
    assert {"speech_start", "speech_end", "reading_behavior", "required_read_duration"} <= set(clip)
    assert {"rel_start", "rel_end", "timing_source", "role", "emphasis"} <= set(clip["words"][0])
    return "hyperframes_contract"


def test_platform_profiles_are_distinct():
    reels = emit.get_style_profile("instagram-reels")
    tiktok = emit.get_style_profile("tiktok")
    x_profile = emit.get_style_profile("x")
    assert reels["safe_area"]["bottom"] != x_profile["safe_area"]["bottom"]
    assert reels["density"] != tiktok["density"] != x_profile["density"]
    assert reels["emphasis_scale"] < tiktok["emphasis_scale"]
    return "platform_profiles"


def test_platform_native_font_scaling():
    youtube = emit.get_style_profile("youtube", (1920, 1080))
    reels = emit.get_style_profile("instagram-reels", (1080, 1920))
    youtube_720p = emit.get_style_profile("youtube", (1280, 720))
    assert youtube["font_size_px"] == youtube["font_size"] == 47
    assert reels["font_size_px"] == reels["font_size"] == 54
    assert youtube_720p["font_size_px"] == 31
    return "platform_native_scaling"


def test_deterministic_emit():
    cfg = _cfg()
    segments = segment_words(_words("deterministic captions render the same way."), cfg)
    first = emit.dumps_hyperframes(segments, cfg)
    second = emit.dumps_hyperframes(segments, cfg)
    assert first == second
    assert json.loads(first)["source_fingerprint"] == json.loads(second)["source_fingerprint"]
    return "deterministic_emit"


def test_qa_passes_valid_plan():
    cfg = _cfg()
    words = _words("Clean captions make every idea easier to understand.", dur=0.34, gap=0.06)
    segments = segment_words(words, cfg)
    report = validate.build_qa_report(words, segments, cfg, emit.get_style_profile(cfg.platform))
    assert report["summary"]["errors"] == 0, report["issues"]
    assert report["manual_review"], "visual/device checks must remain explicit"
    assert report["activation_contract"]["timing_basis"] == "absolute-word-onsets"
    assert report["activation_contract"]["maximum_export_onset_error_frames"] == 1
    assert report["activation_contract"]["phone_review_scale"] == 0.5
    assert report["activation_contract"]["status"] == "export-review-required"
    return "qa_valid"


def test_qa_catches_timing_overlap():
    cfg = _cfg()
    words = _words("word timing matters")
    words[1]["start"] = 0.05
    segments = segment_words(words, cfg)
    report = validate.build_qa_report(words, segments, cfg, emit.get_style_profile(cfg.platform))
    codes = {issue["code"] for issue in report["issues"] if issue["severity"] == "error"}
    assert "WORD_OVERLAP" in codes
    return "qa_overlap"


def test_qa_catches_short_exposure():
    cfg = _cfg()
    words = _words("brief caption")
    segments = segment_words(words, cfg)
    segments[0]["display_end"] = segments[0]["display_start"] + 0.2
    report = validate.build_qa_report(words, segments, cfg, emit.get_style_profile(cfg.platform))
    assert any(issue["code"] == "MIN_EXPOSURE" for issue in report["issues"])
    return "qa_exposure"


def test_engine_writes_three_deterministic_artifacts():
    words = _words("Every caption lands exactly when the speaker says it.", dur=0.38, gap=0.08)
    with tempfile.TemporaryDirectory() as directory:
        prefix = str(Path(directory) / "captions")
        engine.run(words=words, out_prefix=prefix, cfg=_cfg(), strict=True)
        paths = [Path(prefix + suffix) for suffix in (".ass", ".captions.json", ".qa.json")]
        assert all(path.exists() for path in paths)
        first = [path.read_bytes() for path in paths]
        engine.run(words=words, out_prefix=prefix, cfg=_cfg(), strict=True)
        second = [path.read_bytes() for path in paths]
        assert first == second
        hyperframes = json.loads(paths[1].read_text(encoding="utf-8"))
        qa = json.loads(paths[2].read_text(encoding="utf-8"))
        assert qa["summary"]["errors"] == 0
        assert qa["source_fingerprint"] == hyperframes["source_fingerprint"]
        assert qa["source_fingerprint"] in paths[0].read_text(encoding="utf-8")
    return "engine_artifacts"


def test_engine_strict_gate_writes_qa_only():
    words = _words("bad overlap")
    words[1]["start"] = 0.02
    with tempfile.TemporaryDirectory() as directory:
        prefix = str(Path(directory) / "blocked")
        try:
            engine.run(words=words, out_prefix=prefix, cfg=_cfg(), strict=True)
        except validate.CaptionValidationError:
            pass
        else:
            raise AssertionError("strict engine must block invalid caption plans")
        assert Path(prefix + ".qa.json").exists()
        assert not Path(prefix + ".ass").exists()
        assert not Path(prefix + ".captions.json").exists()
    return "strict_qa_gate"


def test_engine_strict_gate_removes_stale_render_artifacts():
    words = _words("bad overlap")
    words[1]["start"] = 0.02
    with tempfile.TemporaryDirectory() as directory:
        prefix = str(Path(directory) / "blocked")
        ass_path = Path(prefix + ".ass")
        json_path = Path(prefix + ".captions.json")
        qa_path = Path(prefix + ".qa.json")
        ass_path.write_text("STALE ASS", encoding="utf-8")
        json_path.write_text('{"stale": true}', encoding="utf-8")
        qa_path.write_text('{"status": "pass"}', encoding="utf-8")
        try:
            engine.run(words=words, out_prefix=prefix, cfg=_cfg(), strict=True)
        except validate.CaptionValidationError:
            pass
        else:
            raise AssertionError("strict engine must block invalid caption plans")
        assert not ass_path.exists(), "stale ASS survived a new failing QA report"
        assert not json_path.exists(), "stale JSON survived a new failing QA report"
        report = json.loads(qa_path.read_text(encoding="utf-8"))
        assert report["status"] == "fail" and report["summary"]["errors"] > 0
    return "strict_qa_stale_cleanup"


def test_words_json_shapes():
    words = _words("aligned input")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "words.json"
        path.write_text(json.dumps({"segments": [{"words": words}]}), encoding="utf-8")
        loaded = engine.load_words_json(path)
        assert [word["text"] for word in loaded] == ["aligned", "input"]
        assert all(word["timing_source"] == "test-forced" for word in loaded)
        path.write_text(json.dumps({"retimed_words": words}), encoding="utf-8")
        loaded = engine.load_words_json(path)
        assert [word["text"] for word in loaded] == ["aligned", "input"]
    return "words_json"


def test_selected_treatment_and_post_cut_timing_are_embedded():
    taste_path = (
        Path(__file__).resolve().parents[2]
        / "Contracts"
        / "examples"
        / "taste-selection.v1.example.json"
    )
    cfg_values, style_values, provenance = engine._load_selected_treatment(taste_path)
    assert style_values["accent"] == "#3B82F6"
    assert cfg_values["max_words_per_caption"] == 8
    words = _words("Selected captions follow the approved post cut clock.")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        forced = root / "forced.envelope.json"
        timeline = root / "timeline-map.json"
        retimed = root / "retimed-words.json"
        forced.write_text('{"schema":"arete-evidence-envelope/v1"}', encoding="utf-8")
        timeline.write_text(
            json.dumps({"timeline_map": [{"source_start": 0.0, "output_start": 0.0}]}),
            encoding="utf-8",
        )
        retimed.write_text(json.dumps({"retimed_words": words}), encoding="utf-8")
        timing = engine._post_cut_timing(forced, timeline, retimed)
        authorization = root / "caption-render-authorization.json"
        authorization.write_text(
            json.dumps(
                {
                    "schema": "arete-caption-render-authorization/v1",
                    "status": "pass",
                    "forced_alignment": {
                        "sha256": engine._sha256_file(forced),
                    },
                    "timeline_map": {
                        "path": str(timeline.resolve()),
                        "sha256": engine._sha256_file(timeline),
                    },
                    "retimed_words": {
                        "path": str(retimed.resolve()),
                        "sha256": engine._sha256_file(retimed),
                    },
                    "taste_selection": {
                        "path": str(taste_path.resolve()),
                        "sha256": engine._sha256_file(taste_path),
                    },
                    "timeline_fingerprint": timing["timeline_fingerprint"],
                }
            ),
            encoding="utf-8",
        )
        timing = engine._post_cut_timing(
            forced,
            timeline,
            retimed,
            authorization_path=authorization,
            taste_selection_path=taste_path,
        )
        assert timing["caption_render_authorization_sha256"] == engine._sha256_file(
            authorization
        )
        prefix = str(root / "captions")
        engine.run(
            words=words,
            out_prefix=prefix,
            cfg=Config.for_platform("instagram-reels", **cfg_values),
            style_overrides=style_values,
            treatment_provenance=provenance,
            post_cut_timing=timing,
            strict=True,
        )
        qa = json.loads(Path(prefix + ".qa.json").read_text(encoding="utf-8"))
        rendered = json.loads(
            Path(prefix + ".captions.json").read_text(encoding="utf-8")
        )
        assert qa["treatment"]["selected_option_id"] == "option-calm-tech"
        assert qa["post_cut_timing"] == timing
        assert rendered["treatment"] == provenance
        assert rendered["post_cut_timing"] == timing
    return "selected_treatment_timing"


def run_all():
    tests = [
        test_sentence_breaks,
        test_clause_semantic_boundary,
        test_no_dangling_function_word,
        test_budget_never_exceeded,
        test_balanced_natural_wrap,
        test_pause_splits,
        test_max_duration_splits,
        test_micro_caption_merges_for_readability,
        test_display_handoff_never_overlaps,
        test_micro_connector_borrows_adjacent_handoff_window,
        test_meaning_word_emphasis_is_scarce,
        test_function_words_not_emphasized,
        test_force_align_fixes_name,
        test_force_align_insert_is_positive_and_monotonic,
        test_force_align_rejects_unrelated_script,
        test_force_align_rejects_one_anchor_in_five_tokens,
        test_force_align_rejects_shortened_source_script,
        test_force_align_rejects_omitted_middle_word,
        test_force_align_allows_tokenization_only_merge,
        test_auto_requires_forced_alignment,
        test_explicit_whisper_is_lower_confidence,
        test_empty_alignment_refused,
        test_abbrev_no_false_break,
        test_ass_exact_reveal_and_safe_area,
        test_ass_karaoke_preserves_uneven_gaps,
        test_ass_transcript_text_is_escaped,
        test_libass_escape_smoke,
        test_hyperframes_rich_contract,
        test_platform_profiles_are_distinct,
        test_platform_native_font_scaling,
        test_deterministic_emit,
        test_qa_passes_valid_plan,
        test_qa_catches_timing_overlap,
        test_qa_catches_short_exposure,
        test_engine_writes_three_deterministic_artifacts,
        test_engine_strict_gate_writes_qa_only,
        test_engine_strict_gate_removes_stale_render_artifacts,
        test_words_json_shapes,
        test_selected_treatment_and_post_cut_timing_are_embedded,
    ]
    failures = 0
    for test in tests:
        try:
            print(f"  PASS  {test()}")
        except Exception as exc:  # self-test runner must report the full suite
            failures += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_all())

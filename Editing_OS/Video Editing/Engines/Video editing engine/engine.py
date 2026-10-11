"""Video editing engine — the orchestrator.

The v2 path separates editorial planning from execution.  It builds a
word-safe, reviewable EDL with attention/rhythm/handoff manifests, then renders
only an explicitly approved EDL using per-segment grade/fades, lossless concat,
PTS-shifted overlays, captions-last, loudness normalization, HDR correction and
edited-duration QA.  The legacy single-clip grade/caption path remains intact.

Usage:
    python engine.py --input in.mp4 --out out.mp4
    python engine.py --input in.mp4 --script script.txt --grade warm_cinematic --out out.mp4
    python engine.py --input in.mp4 --plan-edits --words-json words.json
    python engine.py --apply-edits --edl-in edl.json --out final.mp4
    python engine.py --apply-edits --edl-in edl.json --graphics --out final.mp4
"""

# Resolve only this standalone toolkit's owned shared runtime module.
import sys as _runtime_sys
from pathlib import Path as _RuntimePath
for _runtime_parent in _RuntimePath(__file__).resolve().parents:
    if (_runtime_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_runtime_parent))
        break
import runtime_paths as runtime

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from editorial import (
    EditorialConfig,
    EditorialError,
    PLATFORM_PROFILES,
    assert_edl_valid,
    build_editorial_plan,
    load_words_json,
    normalize_words,
)

PLATFORM_CHOICES = tuple(PLATFORM_PROFILES)

ENGINE_DIR = Path(__file__).resolve().parent
CAPTIONS_ENGINE_DIR = ENGINE_DIR.parent / "Captions_engine"
GRAPHICS_ENGINE_DIR = ENGINE_DIR.parent / "Graphics_engine"

CAPTION_PLATFORM_BY_EDL = {
    "reels": "instagram-reels",
    "tiktok": "tiktok",
    "shorts": "youtube-shorts",
    "x": "x",
    "youtube": "youtube",
    # Documentary is an editorial pacing profile rather than a distribution
    # surface.  Its safe-area/caption behavior is closest to long-form YouTube.
    "documentary": "youtube",
}
GRAPHICS_PLATFORM_BY_EDL = {
    "reels": "reels",
    "tiktok": "tiktok",
    "shorts": "shorts",
    "x": "x",
    "youtube": "youtube",
    "documentary": "youtube",
}

GRADE_FILTERS = {
    "subtle": "eq=contrast=1.03:saturation=0.98",
    "neutral_punch": (
        "eq=contrast=1.06:brightness=0.0:saturation=1.0,"
        "curves=master='0/0 0.25/0.23 0.75/0.77 1/1'"
    ),
    "warm_cinematic": (
        "eq=contrast=1.12:brightness=-0.02:saturation=0.88,"
        "colorbalance=rs=0.02:gs=0.0:bs=-0.03:rm=0.04:gm=0.01:bm=-0.02:rh=0.08:gh=0.02:bh=-0.05,"
        "curves=master='0/0 0.25/0.22 0.75/0.78 1/1'"
    ),
    "none": None,
}

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
HDR_TONEMAP_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


class EngineError(RuntimeError):
    pass


def _run(cmd, **kwargs):
    result = subprocess.run(runtime.command(cmd), capture_output=True, text=True, env=runtime.child_env(), **runtime.child_kwargs(), **kwargs)
    if result.returncode != 0:
        raise EngineError(f"command failed ({cmd[0]}):\n{result.stderr[-4000:]}")
    return result


def _ffprobe_duration(path):
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ])
    return float(result.stdout.strip())


def _ffprobe_dimensions(path):
    result = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
    ])
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def _ffprobe_stream_manifest(path):
    result = _run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels,duration:format=duration,size,bit_rate",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def _ffprobe_color_transfer(path):
    result = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_transfer", "-of", "csv=p=0", str(path),
    ])
    return result.stdout.strip().lower()


def _build_export_review_contract(edl, report, output_duration, stream_manifest):
    """Create the final encoded-artifact review map shared by all specialists."""
    sample_times = {0.1, max(0.0, float(output_duration) - 0.15)}
    qa_plan = edl.get("editorial", {}).get("qa_plan") or {}
    sample_times.update(float(value) for value in qa_plan.get("sample_times_s", []))
    sample_times.update(
        float(window["at_output_s"])
        for window in qa_plan.get("cut_windows", [])
        if "at_output_s" in window
    )
    words = list(edl.get("editorial", {}).get("retimed_words") or [])
    if words:
        for index in sorted({0, len(words) // 2, len(words) - 1}):
            sample_times.add(float(words[index]["start"]))
    graphics_plan = report.get("graphics_handoff", {}).get("plan")
    if graphics_plan and Path(graphics_plan).exists():
        try:
            data = json.loads(Path(graphics_plan).read_text(encoding="utf-8"))
            for cue in data.get("cues", []):
                sample_times.add(float(cue["anchor_sec"]))
                sample_times.add(max(float(cue["start_sec"]), float(cue["end_sec"]) - 0.2))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    bounded = sorted({
        round(min(max(0.0, value), float(output_duration)), 3)
        for value in sample_times
    })
    streams = list(stream_manifest.get("streams") or [])
    return {
        "schema": "arete-export-review/v1",
        "status": "pending-human-review",
        "artifact": report.get("output"),
        "sample_times_s": bounded,
        "streams": {
            "video_present": any(item.get("codec_type") == "video" for item in streams),
            "audio_present": any(item.get("codec_type") == "audio" for item in streams),
            "manifest": stream_manifest,
        },
        "checks": {
            "voice_activation": "active caption words land within one output frame of the spoken onset",
            "graphics_timing": "semantic items appear on their authored retimed-word anchors",
            "mobile_legibility": "captions, labels, and diagrams remain immediately readable at 50% linear scale",
            "depth_and_occlusion": "3D planes remain coherent and PiP never covers the focal label",
            "color_and_background": "grade, backdrop, graphics palette, and skin tones feel like one intentional world",
            "audio_video": "dialogue is present, synchronized, and free of cut-boundary pops",
            "platform": "the real platform UI overlay clears captions and critical graphics",
            "endpoints": "the first and last encoded frames are intentional and source-consistent",
        },
    }


def _source_video_filter(path, grade):
    filters = []
    if _ffprobe_color_transfer(path) in HDR_TRANSFERS:
        filters.append(HDR_TONEMAP_FILTER)
    grade_filter = GRADE_FILTERS.get(grade)
    if grade_filter:
        filters.append(grade_filter)
    return ",".join(filters) if filters else None


def _find_python_with_whisper():
    """Return a python executable that can `import whisper`, preferring sys.executable."""
    candidates = [sys.executable]
    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        try:
            probe = subprocess.run([cand, "-c", "import whisper"], **runtime.child_kwargs(),
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return cand
    raise EngineError("No Python interpreter with `whisper` installed was found. "
                       "Install it with: pip install openai-whisper")


def extract_audio(video_path, out_wav):
    runtime.output(out_wav)
    _run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(out_wav)])


def generate_captions(audio_path, out_prefix, script=None, model="base"):
    """Call the sibling Captions_engine and return the produced .ass path (or None)."""
    runtime.output(out_prefix)
    python_exe = _find_python_with_whisper()
    cmd = [python_exe, "engine.py", "--audio", str(audio_path),
           "--out-prefix", str(out_prefix), "--model", model]
    if script:
        cmd += ["--script", str(script)]
    _run(cmd, cwd=str(CAPTIONS_ENGINE_DIR))
    runtime.output(out_prefix)
    ass_path = Path(f"{out_prefix}.ass")
    if not ass_path.exists():
        raise EngineError("Captions_engine did not produce an .ass file")
    return ass_path


def generate_caption_assets(audio_path, out_prefix, script=None, model="base"):
    """Run the sibling caption engine and return both canonical artifacts."""
    runtime.output(out_prefix)
    ass_path = generate_captions(audio_path, out_prefix, script=script, model=model)
    json_path = Path(f"{out_prefix}.captions.json")
    if not json_path.exists():
        raise EngineError("Captions_engine did not produce caption JSON")
    return ass_path, json_path


def _edl_platform(edl):
    """Read the frozen editorial platform, retaining old-EDL compatibility."""
    platform = edl.get("editorial", {}).get("config", {}).get("platform", "reels")
    if platform not in PLATFORM_PROFILES:
        raise EngineError(f"approved EDL has an unsupported editorial platform: {platform!r}")
    return platform


def write_timeline_caption_assets(words, out_prefix, playres=(1080, 1920),
                                  platform="reels", include_qa=False):
    """Phrase already-retimed words through the sibling caption engine.

    This avoids a second ASR pass after cleanup and, critically, keeps captions
    on output-timeline offsets after source ranges have been concatenated.
    """
    sys.path.insert(0, str(CAPTIONS_ENGINE_DIR))
    try:
        import emit
        import validate as caption_validate
        from phrasing import Config, segment_words
    finally:
        try:
            sys.path.remove(str(CAPTIONS_ENGINE_DIR))
        except ValueError:
            pass

    normalized = normalize_words(words)
    caption_words = [
        {"text": word["text"], "start": word["start"], "end": word["end"],
         "score": word.get("score", 1.0)}
        for word in normalized
    ]
    caption_platform = CAPTION_PLATFORM_BY_EDL.get(platform, platform)
    cfg = Config.for_platform(caption_platform)
    segments = segment_words(caption_words, cfg)
    profile = emit.get_style_profile(cfg.platform, playres)
    runtime.output(out_prefix)
    ass_path = Path(f"{out_prefix}.ass")
    json_path = Path(f"{out_prefix}.captions.json")
    qa_path = Path(f"{out_prefix}.qa.json")
    ass_path.write_text(
        emit.to_ass(segments, cfg, playres, profile=profile), encoding="utf-8"
    )
    emit.dump_hyperframes(segments, cfg, json_path, playres=playres, profile=profile)
    qa_report = caption_validate.build_qa_report(caption_words, segments, cfg, profile)
    qa_path.write_text(caption_validate.dumps_report(qa_report), encoding="utf-8")
    try:
        caption_validate.raise_for_errors(qa_report)
    except caption_validate.CaptionValidationError as exc:
        raise EngineError(f"retimed captions failed QA; see {qa_path}: {exc}") from exc
    if include_qa:
        return ass_path, json_path, qa_path
    return ass_path, json_path


def _load_graphics_engine():
    """Load the sibling planner/composer without making it a package dependency."""
    sys.path.insert(0, str(GRAPHICS_ENGINE_DIR))
    try:
        import compose
        import planner
    finally:
        try:
            sys.path.remove(str(GRAPHICS_ENGINE_DIR))
        except ValueError:
            pass
    return planner, compose


def render_edl_graphics(base_path, retimed_words, *, duration_s, platform,
                        work_dir, niche=None, asset_dirs=(),
                        allow_meme_assets=False, captions_enabled=True,
                        quality="standard"):
    """Plan and render graphics over the clean-cut output timeline.

    The caller supplies ``retimed_words`` from the approved EDL.  This is a
    strict no-ASR handoff: graphics and later captions share the same immutable
    output-timeline evidence.
    """
    planner, compose = _load_graphics_engine()
    base_path = Path(base_path).resolve()
    graphics_dir = Path(work_dir).resolve() / "graphics_project"
    runtime.output(graphics_dir)
    graphics_dir.mkdir(parents=True, exist_ok=True)
    width, height = _ffprobe_dimensions(base_path)
    graphics_platform = GRAPHICS_PLATFORM_BY_EDL.get(platform, platform)
    graphics_niche = niche or ("documentary" if platform == "documentary" else "general")
    try:
        plan = planner.plan_graphics(
            retimed_words,
            duration=float(duration_s),
            platform=graphics_platform,
            niche=graphics_niche,
            source_video=str(base_path),
            asset_dirs=tuple(asset_dirs or ()),
            captions_enabled=bool(captions_enabled),
            allow_meme_assets=bool(allow_meme_assets),
            width=width,
            height=height,
        )
    except (TypeError, ValueError, OSError) as exc:
        raise EngineError(f"graphics planning failed: {exc}") from exc

    # Persist review/QA evidence even when semantic restraint produces no cues.
    # In that case a full HyperFrames pass would only re-encode identical video.
    plan_path = graphics_dir / "graphics-plan.json"
    qa_path = graphics_dir / "graphics-qa.json"
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    graphics_qa = {
        "passed": not any(item.get("severity") == "error" for item in plan.qa),
        "issues": plan.qa,
    }
    qa_path.write_text(json.dumps(graphics_qa, indent=2, sort_keys=True), encoding="utf-8")
    handoff = {
        "status": "skipped_no_cues" if not plan.cues else "planned",
        "timing_basis": "approved_edl.retimed_words/output_timeline_seconds",
        "platform": graphics_platform,
        "niche": graphics_niche,
        "cue_count": len(plan.cues),
        "project": str(graphics_dir),
        "plan": str(plan_path),
        "qa": str(qa_path),
        "qa_passed": graphics_qa["passed"],
        "render": None,
    }
    if not graphics_qa["passed"]:
        raise EngineError(f"graphics plan failed QA; see {qa_path}")
    if not plan.cues:
        return base_path, handoff

    try:
        paths = compose.write_project(plan, graphics_dir, source_video=base_path)
        # Use the composer-owned artifact paths in case its contract evolves.
        handoff["plan"] = str(paths["plan"])
        handoff["qa"] = str(paths["qa"])
        compose.lint(graphics_dir)
        rendered_path = Path(work_dir).resolve() / "graphics_composited.mp4"
        compose.render(
            graphics_dir, rendered_path,
            fps=int(plan.composition["fps"]), quality=quality,
        )
        if not rendered_path.exists():
            raise RuntimeError("HyperFrames reported success but produced no graphics video")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise EngineError(f"graphics composition/render failed: {exc}") from exc
    handoff["status"] = "rendered"
    handoff["render"] = str(rendered_path)
    return rendered_path, handoff


def _escape_ffmpeg_path(path):
    """Windows ffmpeg filtergraph paths: forward slashes, escaped drive-letter colon."""
    p = str(Path(path).resolve()).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = p[0] + r"\:" + p[2:]
    return p


def render_intro(width, height, title, subtitle, duration, accent, work_dir):
    """Render a HyperFrames title-card intro via the sibling Graphics_engine."""
    runtime.output(work_dir)
    sys.path.insert(0, str(GRAPHICS_ENGINE_DIR))
    import compose  # Graphics_engine's composition generator/renderer

    project_dir = work_dir / "intro_project"
    html = compose.title_card(title, subtitle=subtitle, duration=duration,
                               accent=accent, width=width, height=height)
    compose.write_composition(html, project_dir)
    compose.lint(project_dir)
    intro_silent = work_dir / "intro_silent.mp4"
    compose.render(project_dir, intro_silent, fps=30, quality="draft")

    # HyperFrames renders video-only when the composition has no <audio>; add a
    # silent track so concat (which expects matching a/v streams) can join it.
    intro_path = work_dir / "intro.mp4"
    _run(["ffmpeg", "-y", "-i", str(intro_silent),
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
          "-shortest", "-c:v", "copy", "-c:a", "aac", str(intro_path)])
    return intro_path


def concat_videos(paths, out_path):
    """Concatenate videos of matching resolution via ffmpeg's concat filter (re-encodes)."""
    runtime.output(out_path)
    cmd = ["ffmpeg", "-y"]
    filter_inputs = []
    for i, p in enumerate(paths):
        cmd += ["-i", str(p)]
        filter_inputs.append(f"[{i}:v:0][{i}:a:0]")
    filter_str = "".join(filter_inputs) + f"concat=n={len(paths)}:v=1:a=1[outv][outa]"
    cmd += ["-filter_complex", filter_str, "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_path)]
    _run(cmd)


def _concat_manifest_line(path):
    value = str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{value}'"


def _edl_words_by_source(edl):
    """Return transcript evidence for word-safe validation, or fail closed.

    The built-in planner emits one source today. Hand-authored multi-source
    EDLs must provide ``editorial.source_words_by_source`` so the renderer can
    prove every cut edge and reconstruct the downstream timing handoff.
    """
    sources = edl.get("sources", {})
    editorial = edl.get("editorial", {})
    by_source = editorial.get("source_words_by_source")
    if isinstance(by_source, dict) and by_source:
        missing = sorted(set(sources) - set(by_source))
        if missing:
            raise EngineError(
                "multi-source transcript evidence is missing for: " + ", ".join(missing)
            )
        return by_source
    source_words = editorial.get("source_words")
    if source_words and len(sources) == 1:
        return {next(iter(sources)): source_words}
    if len(sources) > 1:
        raise EngineError(
            "multi-source EDLs require editorial.source_words_by_source for word-safe validation"
        )
    return None


def render_edl_base(edl, out_path, work_dir):
    """Render approved ranges with a drift-free PCM intermediate timeline.

    AAC encoder priming is intentionally deferred until after concatenation.
    Encoding AAC independently in every segment adds roughly one priming frame
    per cut, causing captions/graphics (which use ideal EDL math) to drift later
    in multi-cut edits.
    """
    assert_edl_valid(edl, _edl_words_by_source(edl))

    segment_dir = Path(work_dir) / "segments"
    runtime.output(segment_dir)
    runtime.output(out_path)
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []
    source_durations = {}
    for index, item in enumerate(edl["ranges"]):
        source_path = Path(edl["sources"][item["source"]]).resolve()
        if not source_path.exists():
            raise EngineError(f"EDL source does not exist: {source_path}")
        if source_path not in source_durations:
            source_durations[source_path] = _ffprobe_duration(source_path)
        start = float(item["start"])
        if float(item["end"]) > source_durations[source_path] + 0.02:
            raise EngineError(
                f"EDL range {index} ends at {item['end']}s beyond "
                f"{source_path.name} ({source_durations[source_path]:.3f}s)"
            )
        duration = float(item["end"]) - start
        fade = min(0.03, duration / 3)
        segment_path = segment_dir / f"segment_{index:04d}.mkv"
        # Seek BEFORE -i (input seeking).  This resets both stream timestamps to
        # zero at the demuxer, so the per-segment afade below sees segment-local
        # time.  With output seeking (-ss after -i) the audio kept its source PTS
        # inside the filtergraph, so afade's out-point silenced every segment
        # whose source start exceeded its own duration.  Input seeking stays
        # frame-accurate here because the segment is re-encoded, not stream-copied.
        cmd = [
            "ffmpeg", "-y", "-ss", f"{start:.6f}", "-i", str(source_path),
            "-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "0:a:0?",
        ]
        grade_name = item.get("grade", edl.get("grade", "none"))
        video_filter = _source_video_filter(source_path, grade_name)
        if video_filter:
            cmd += ["-vf", video_filter]
        cmd += [
            "-af", f"afade=t=in:st=0:d={fade:.3f},"
                   f"afade=t=out:st={max(0.0, duration - fade):.6f}:d={fade:.3f}",
            # B-frame reordering gives each standalone Matroska segment an
            # encoder-delay timestamp.  Disabling B-frames keeps segment PTS at
            # zero so concat cannot accumulate that delay at every cut.
            "-c:v", "libx264", "-bf", "0", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
            "-ar", "48000", "-ac", "2", "-avoid_negative_ts", "make_zero",
            str(segment_path),
        ]
        _run(cmd)
        segment_paths.append(segment_path)

    concat_manifest = Path(work_dir) / "concat.txt"
    concat_manifest.write_text(
        "\n".join(
            f"{_concat_manifest_line(path)}\n"
            f"duration {float(item['end']) - float(item['start']):.6f}"
            for path, item in zip(segment_paths, edl["ranges"])
        ) + "\n",
        encoding="utf-8",
    )
    joined_path = Path(work_dir) / "base_pcm_joined.mkv"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_manifest),
        "-c", "copy", str(joined_path),
    ])
    out_path = Path(out_path)
    if out_path.suffix.lower() in {".mkv", ".mka"}:
        if joined_path.resolve() != out_path.resolve():
            shutil.copy2(joined_path, out_path)
    else:
        # Compatibility for direct callers requesting MP4: one AAC encode for
        # the complete timeline, never one encoder delay per edit segment.
        _run([
            "ffmpeg", "-y", "-i", str(joined_path), "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out_path),
        ])
    return Path(out_path)


def grade_and_caption(video_path, out_path, grade="subtle", ass_path=None, loudnorm=True):
    """Single-pass ffmpeg: color grade -> (burn captions LAST) -> loudness normalize."""
    runtime.output(out_path)
    vf_parts = []
    grade_filter = GRADE_FILTERS.get(grade)
    if grade_filter:
        vf_parts.append(grade_filter)
    if ass_path:
        vf_parts.append(
            f"subtitles='{_escape_ffmpeg_path(ass_path)}'"
        )
    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    if loudnorm:
        cmd += ["-af", "loudnorm=I=-14:TP=-1:LRA=11"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_path)]
    _run(cmd)


def composite_overlays_and_captions(base_path, out_path, overlays=None, ass_path=None, loudnorm=True):
    """Composite output-timed overlays, then apply captions last.

    Overlay frame zero is shifted with ``PTS-STARTPTS+T/TB`` (where ``T`` is
    the EDL start time).  This prevents an overlay from starting midway through
    its animation when it enters late in the output timeline.
    """
    runtime.output(out_path)
    overlays = list(overlays or [])
    if not overlays:
        return grade_and_caption(base_path, out_path, grade="none", ass_path=ass_path, loudnorm=loudnorm)

    cmd = ["ffmpeg", "-y", "-i", str(base_path)]
    for overlay in overlays:
        overlay_path = Path(overlay["file"]).resolve()
        if not overlay_path.exists():
            raise EngineError(f"overlay does not exist: {overlay_path}")
        cmd += ["-i", str(overlay_path)]

    filters = []
    current_video = "[0:v:0]"
    for index, overlay in enumerate(overlays, start=1):
        start = float(overlay["start_in_output"])
        duration = float(overlay["duration"])
        end = start + duration
        overlay_label = f"ov{index}"
        output_label = f"v{index}"
        filters.append(f"[{index}:v:0]setpts=PTS-STARTPTS+{start:.6f}/TB[{overlay_label}]")
        filters.append(
            f"{current_video}[{overlay_label}]overlay=0:0:"
            f"enable='between(t,{start:.6f},{end:.6f})':eof_action=pass[{output_label}]"
        )
        current_video = f"[{output_label}]"

    if ass_path:
        filters.append(
            f"{current_video}subtitles='{_escape_ffmpeg_path(ass_path)}'"
            "[vout]"
        )
        current_video = "[vout]"
    if loudnorm:
        filters.append("[0:a:0]loudnorm=I=-14:TP=-1:LRA=11[aout]")

    cmd += ["-filter_complex", ";".join(filters), "-map", current_video]
    cmd += ["-map", "[aout]" if loudnorm else "0:a:0"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out_path),
    ]
    _run(cmd)
    return Path(out_path)


def plan_edits(input_video, *, words=None, words_json=None, script=None, model="base",
               source_id="main", grade="subtle", work_dir=None, config=None,
               edl_out=None, plan_out=None):
    """Analyze footage and write a non-destructive editorial plan plus EDL."""
    input_video = Path(input_video).resolve()
    if not input_video.exists():
        raise EngineError(f"input video does not exist: {input_video}")
    work_dir = Path(work_dir).resolve() if work_dir else input_video.parent / f".{input_video.stem}_edit_plan"
    runtime.output(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if words is not None:
        source_words = normalize_words(words)
    elif words_json:
        source_words = load_words_json(str(words_json))
    else:
        audio_wav = work_dir / "source_audio.wav"
        extract_audio(input_video, audio_wav)
        _, caption_json = generate_caption_assets(
            audio_wav, work_dir / "source_captions", script=script, model=model,
        )
        source_words = load_words_json(str(caption_json))

    cfg = config or EditorialConfig()
    try:
        source_duration_s = _ffprobe_duration(input_video)
    except EngineError:
        # Pure planning remains usable with transcript fixtures or when ffprobe
        # is temporarily unavailable.  The approved render path probes media.
        source_duration_s = None
    plan = build_editorial_plan(
        source_words, source_id=source_id, source_path=str(input_video),
        grade=grade, config=cfg, source_duration_s=source_duration_s,
    )
    if not plan["validation"]["valid"]:
        raise EngineError(f"generated EDL failed validation: {plan['validation']['errors']}")

    edl_path = Path(edl_out).resolve() if edl_out else work_dir / "edl.json"
    plan_path = Path(plan_out).resolve() if plan_out else work_dir / "editorial-plan.json"
    runtime.output(edl_path)
    runtime.output(plan_path)
    edl_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    edl_path.write_text(json.dumps(plan["edl"], indent=2, ensure_ascii=False), encoding="utf-8")
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan, edl_path, plan_path


def _load_edl(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineError(f"could not load EDL {path}: {exc}") from exc
    if isinstance(data, dict) and "edl" in data and isinstance(data["edl"], dict):
        data = data["edl"]
    if not isinstance(data, dict):
        raise EngineError("EDL must be a JSON object")
    return data


def apply_edl(edl_or_path, out_path, *, make_captions=True, work_dir=None,
              intro_title=None, intro_subtitle=None, intro_duration=2.5,
              intro_accent="#22d3ee", make_graphics=False,
              graphics_niche=None, graphics_asset_dirs=(),
              allow_meme_assets=False, graphics_quality="standard"):
    """Render a previously reviewed EDL and emit an evidence-rich QA report."""
    edl = _load_edl(edl_or_path) if isinstance(edl_or_path, (str, os.PathLike)) else dict(edl_or_path)
    out_path = runtime.output(out_path)
    work_dir = Path(work_dir).resolve() if work_dir else out_path.parent / f".{out_path.stem}_work"
    runtime.output(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    validation = assert_edl_valid(edl, _edl_words_by_source(edl))
    platform = _edl_platform(edl)

    report = {
        "mode": "approved_edl",
        "output": str(out_path),
        "platform": platform,
        "edl_validation": validation,
        "source_color_transfer": {
            source_id: _ffprobe_color_transfer(source_path)
            for source_id, source_path in edl["sources"].items()
        },
        "steps": [],
    }
    report["hdr_tonemapped_sources"] = [
        source_id for source_id, transfer in report["source_color_transfer"].items()
        if transfer in HDR_TRANSFERS
    ]
    t0 = time.time()
    # Matroska carries the drift-free PCM intermediate.  AAC is encoded only
    # once in the final captions/graphics/loudness pass.
    base_path = work_dir / "base.mkv"
    step_t = time.time()
    render_edl_base(edl, base_path, work_dir)
    report["steps"].append({"step": "extract_fade_grade_concat", "seconds": round(time.time() - step_t, 2)})

    retimed_words = edl.get("editorial", {}).get("retimed_words")
    if (make_captions or make_graphics) and not retimed_words:
        raise EngineError("approved EDL has no retimed_words downstream timing handoff")

    visual_base_path = base_path
    if make_graphics:
        step_t = time.time()
        visual_base_path, graphics_handoff = render_edl_graphics(
            base_path,
            retimed_words,
            duration_s=float(edl["total_duration_s"]),
            platform=platform,
            work_dir=work_dir,
            niche=graphics_niche,
            asset_dirs=graphics_asset_dirs,
            allow_meme_assets=allow_meme_assets,
            captions_enabled=make_captions,
            quality=graphics_quality,
        )
        report["graphics_handoff"] = graphics_handoff
        report["steps"].append({
            "step": (
                "plan_and_render_graphics_from_retimed_words"
                if graphics_handoff["status"] == "rendered"
                else "plan_graphics_skip_zero_cues"
            ),
            "seconds": round(time.time() - step_t, 2),
        })

    ass_path = None
    if make_captions:
        width, height = _ffprobe_dimensions(visual_base_path)
        step_t = time.time()
        ass_path, caption_json, caption_qa = write_timeline_caption_assets(
            retimed_words,
            work_dir / "captions",
            playres=(width, height),
            platform=platform,
            include_qa=True,
        )
        caption_qa_report = json.loads(caption_qa.read_text(encoding="utf-8"))
        report["caption_handoff"] = {
            "ass": str(ass_path),
            "json": str(caption_json),
            "qa": str(caption_qa),
            "qa_status": caption_qa_report["status"],
            "platform": caption_qa_report["style"]["platform"],
            "timing_basis": "output_timeline_seconds",
            "source_of_truth": "approved_edl.editorial.retimed_words",
        }
        report["steps"].append({
            "step": "phrase_and_validate_retimed_captions",
            "seconds": round(time.time() - step_t, 2),
        })

    main_out = work_dir / "main_composited.mp4" if intro_title else out_path
    step_t = time.time()
    # Grade is already baked per segment.  This final pass is reserved for
    # captions-last and dialogue loudness, preserving the production contract.
    composite_overlays_and_captions(
        visual_base_path, main_out, overlays=edl.get("overlays", []),
        ass_path=ass_path, loudnorm=True,
    )
    report["steps"].append({
        "step": "pts_shift_overlays_then_captions_last_and_loudnorm",
        "seconds": round(time.time() - step_t, 2),
    })

    if intro_title:
        width, height = _ffprobe_dimensions(main_out)
        step_t = time.time()
        intro_path = render_intro(
            width, height, intro_title, intro_subtitle, intro_duration,
            intro_accent, work_dir,
        )
        concat_videos([intro_path, main_out], out_path)
        report["steps"].append({"step": "render_and_concat_intro", "seconds": round(time.time() - step_t, 2)})

    output_duration = _ffprobe_duration(out_path)
    expected_duration = float(edl["total_duration_s"]) + (intro_duration if intro_title else 0.0)
    duration_delta = abs(output_duration - expected_duration)
    duration_tolerance = 0.12
    stream_manifest = _ffprobe_stream_manifest(out_path)
    export_review = _build_export_review_contract(
        edl, report, output_duration, stream_manifest,
    )
    report["qa"] = {
        "expected_duration_s": round(expected_duration, 3),
        "output_duration_s": round(output_duration, 3),
        "duration_delta_s": round(duration_delta, 3),
        "duration_tolerance_s": duration_tolerance,
        "duration_ok": duration_delta < duration_tolerance,
        "cut_count": max(0, len(edl["ranges"]) - 1),
        "qa_plan": edl.get("editorial", {}).get("qa_plan"),
        "export_review": export_review,
        "export_streams": export_review["streams"],
        "requires_visual_review": True,
        "caption_qa_passed": (
            report.get("caption_handoff", {}).get("qa_status") != "fail"
            if make_captions else None
        ),
        "graphics_qa_passed": (
            report.get("graphics_handoff", {}).get("qa_passed")
            if make_graphics else None
        ),
        "automated_gate_passed": (
            duration_delta < duration_tolerance
            and validation["valid"]
            and export_review["streams"]["video_present"]
            and (not make_captions or report["caption_handoff"]["qa_status"] != "fail")
            and (not make_graphics or report["graphics_handoff"]["qa_passed"])
        ),
        "ready": False,
    }
    report["total_seconds"] = round(time.time() - t0, 2)
    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not report["qa"]["automated_gate_passed"]:
        raise EngineError(
            f"render failed the automated QA gate; see {report_path} "
            f"(duration delta {duration_delta:.3f}s)"
        )
    return report


def run(input_video, out_path, script=None, grade="subtle", model="base",
        make_captions=True, work_dir=None,
        intro_title=None, intro_subtitle=None, intro_duration=2.5, intro_accent="#22d3ee"):
    input_video = Path(input_video).resolve()
    out_path = runtime.output(out_path)
    work_dir = Path(work_dir).resolve() if work_dir else out_path.parent / f".{out_path.stem}_work"
    runtime.output(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    report = {"input": str(input_video), "output": str(out_path), "steps": []}
    t0 = time.time()

    ass_path = None
    if make_captions:
        audio_wav = work_dir / "audio.wav"
        step_t = time.time()
        extract_audio(input_video, audio_wav)
        report["steps"].append({"step": "extract_audio", "seconds": round(time.time() - step_t, 2)})

        step_t = time.time()
        ass_path = generate_captions(audio_wav, work_dir / "captions", script=script, model=model)
        report["steps"].append({"step": "generate_captions", "seconds": round(time.time() - step_t, 2)})

    main_out = work_dir / "main_graded.mp4" if intro_title else out_path
    step_t = time.time()
    grade_and_caption(input_video, main_out, grade=grade, ass_path=ass_path)
    report["steps"].append({"step": "grade_and_caption", "seconds": round(time.time() - step_t, 2)})

    if intro_title:
        width, height = _ffprobe_dimensions(main_out)
        step_t = time.time()
        intro_path = render_intro(width, height, intro_title, intro_subtitle,
                                   intro_duration, intro_accent, work_dir)
        report["steps"].append({"step": "render_intro", "seconds": round(time.time() - step_t, 2)})

        step_t = time.time()
        concat_videos([intro_path, main_out], out_path)
        report["steps"].append({"step": "concat_intro", "seconds": round(time.time() - step_t, 2)})

    in_dur = _ffprobe_duration(input_video)
    out_dur = _ffprobe_duration(out_path)
    expected_dur = in_dur + (intro_duration if intro_title else 0)
    report["qa"] = {
        "input_duration_s": round(in_dur, 3),
        "output_duration_s": round(out_dur, 3),
        "expected_duration_s": round(expected_dur, 3),
        "duration_delta_s": round(abs(expected_dur - out_dur), 3),
        "duration_ok": abs(expected_dur - out_dur) < 0.5,
    }
    report["total_seconds"] = round(time.time() - t0, 2)

    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Video editing engine orchestrator.")
    p.add_argument("--input", help="input video path (not needed when applying an EDL)")
    p.add_argument("--out", help="output video path (required for render/apply)")
    p.add_argument("--script", help="corrected script text for force-aligned captions")
    p.add_argument("--grade", default="subtle", choices=list(GRADE_FILTERS))
    p.add_argument("--model", default="base", help="whisper model (tiny.en, base, small, ...)")
    p.add_argument("--no-captions", action="store_true", help="skip transcription/captions")
    p.add_argument("--work-dir", help="scratch directory for intermediate files")
    p.add_argument("--intro-title", help="if set, prepends a HyperFrames title-card intro")
    p.add_argument("--intro-subtitle")
    p.add_argument("--intro-duration", type=float, default=2.5)
    p.add_argument("--intro-accent", default="#22d3ee")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument(
        "--plan-edits", action="store_true",
        help="analyze word-level speech and write a reviewable EDL; does not render",
    )
    modes.add_argument(
        "--apply-edits", action="store_true",
        help="render an approved --edl-in with per-segment fades and QA",
    )
    p.add_argument("--words-json", help="word-level ASR/caption JSON; transcribes when omitted")
    p.add_argument("--edl-in", help="approved EDL (or editorial-plan JSON) for --apply-edits")
    p.add_argument("--edl-out", help="EDL output path for --plan-edits")
    p.add_argument("--plan-out", help="full analysis output path for --plan-edits")
    p.add_argument("--source-id", default="main")
    p.add_argument("--platform", default="reels", choices=list(PLATFORM_CHOICES))
    p.add_argument("--pacing", default="adaptive", choices=["tight", "adaptive", "natural", "cinematic"])
    p.add_argument("--cleanup-strength", default="balanced", choices=["conservative", "balanced", "ruthless"])
    p.add_argument("--dead-air-threshold", type=float, default=0.45)
    p.add_argument("--breath-pad-before", type=float, default=0.06)
    p.add_argument("--breath-pad-after", type=float, default=0.08)
    p.add_argument("--keep-fillers", action="store_true", help="do not auto-remove high-confidence filler")
    p.add_argument("--keep-repeated-takes", action="store_true", help="flag duplicate takes but do not auto-remove")
    p.add_argument(
        "--graphics", action="store_true",
        help="plan and render semantic graphics from approved EDL retimed_words",
    )
    p.add_argument("--graphics-niche", help="niche-led graphics theme (tech, finance, luxury, etc.)")
    p.add_argument(
        "--graphics-assets-dir", action="append", default=[],
        help="local graphics asset root (repeatable)",
    )
    p.add_argument("--allow-meme-assets", action="store_true")
    p.add_argument(
        "--graphics-quality", default="standard", choices=["draft", "standard", "high"],
    )
    runtime.common_args(p)
    args = p.parse_args(argv)
    runtime.configure_args(args)
    runtime.guard_args(args, ("out", "work_dir", "edl_out", "plan_out"))

    if args.graphics and not args.apply_edits:
        p.error("--graphics is an approved-EDL option and requires --apply-edits")

    if args.plan_edits:
        if not args.input:
            p.error("--plan-edits requires --input")
        cfg = EditorialConfig(
            platform=args.platform,
            pacing=args.pacing,
            cleanup_strength=args.cleanup_strength,
            dead_air_threshold_s=args.dead_air_threshold,
            breath_padding_before_s=args.breath_pad_before,
            breath_padding_after_s=args.breath_pad_after,
            remove_fillers=not args.keep_fillers,
            remove_repeated_takes=not args.keep_repeated_takes,
        )
        try:
            plan, edl_path, plan_path = plan_edits(
                args.input, words_json=args.words_json, script=args.script,
                model=args.model, source_id=args.source_id, grade=args.grade,
                work_dir=args.work_dir, config=cfg, edl_out=args.edl_out,
                plan_out=args.plan_out,
            )
        except (EditorialError, EngineError) as exc:
            p.error(str(exc))
        summary = {
            "edl": str(edl_path),
            "plan": str(plan_path),
            "planned_duration_s": plan["analysis"]["planned_duration_s"],
            "estimated_time_removed_s": plan["analysis"]["estimated_time_removed_s"],
            "automatic_decisions": sum(
                bool(item.get("automatic")) for item in plan["analysis"]["issues"]
            ),
            "review_required": len(plan["analysis"]["review_required"]),
            "next": "Review the EDL, then run --apply-edits --edl-in <edl> --out <video>.",
        }
        print(json.dumps(summary, indent=2))
        return 0

    if args.apply_edits:
        if not args.edl_in:
            p.error("--apply-edits requires a reviewed --edl-in")
        if not args.out:
            p.error("--apply-edits requires --out")
        try:
            report = apply_edl(
                args.edl_in, args.out, make_captions=not args.no_captions,
                work_dir=args.work_dir, intro_title=args.intro_title,
                intro_subtitle=args.intro_subtitle,
                intro_duration=args.intro_duration, intro_accent=args.intro_accent,
                make_graphics=args.graphics,
                graphics_niche=args.graphics_niche,
                graphics_asset_dirs=args.graphics_assets_dir,
                allow_meme_assets=args.allow_meme_assets,
                graphics_quality=args.graphics_quality,
            )
        except (EditorialError, EngineError) as exc:
            p.error(str(exc))
        print(json.dumps(report, indent=2))
        return 0

    if not args.input:
        p.error("legacy grade/caption mode requires --input")
    if not args.out:
        p.error("--out is required unless --plan-edits is used")

    run(args.input, args.out, script=args.script, grade=args.grade, model=args.model,
        make_captions=not args.no_captions, work_dir=args.work_dir,
        intro_title=args.intro_title, intro_subtitle=args.intro_subtitle,
        intro_duration=args.intro_duration, intro_accent=args.intro_accent)
    return 0


if __name__ == "__main__":
    sys.exit(main())

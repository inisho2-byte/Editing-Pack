"""MIT. Offline synthetic draft and real gate-refusal walkthrough; never approval."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Editing_OS"))
import runtime_paths as runtime


def write(path, value):
    path = runtime.output(path, require_workspace=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(command, log, *, expected=0):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120,
                            env=runtime.child_env(), **runtime.child_kwargs())
    runtime.output(log, require_workspace=True).write_text(
        result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != expected:
        raise RuntimeError(f"Expected exit {expected}, got {result.returncode}; see {log}")
    return result


def python_cli(relative, args, log, expected=0, required_message=None):
    result = run([sys.executable, "-B", ROOT / relative, *args], log, expected=expected)
    if required_message and required_message not in result.stdout + result.stderr:
        raise RuntimeError(f"Expected refusal reason {required_message!r}; see {log}")
    return result


def build(job):
    engines = ROOT / "Editing_OS/Video Editing/Engines"
    contracts = ROOT / "Editing_OS/Video Editing/Contracts"
    ffmpeg, ffprobe = runtime.tool("ffmpeg"), runtime.tool("ffprobe")
    # Check dependencies before making a job. Never download, invoke speech APIs, or launch a server.
    load_module("demo_contract_validator", contracts / "validate.py")
    if job.exists():
        raise ValueError("Use a new job name; the walkthrough never overwrites an existing job")
    for part in ("inputs", "contracts", "work", "evidence", "exports", "cache", "simulated-contracts"):
        (job / part).mkdir(parents=True, exist_ok=False)
    os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = str(job / "cache")
    (job / "brief.md").write_text(
        "# Synthetic clock demonstration\n\nEight seconds of generated test pattern and a quiet "
        "tone; no speech or personal material. Keep source [0,3) and [5,8). "
        "Manual test words illustrate the clock only. Output is a six-second unapproved draft.\n",
        encoding="utf-8")
    write(job / "fixture-status.json", {"schema": "editing-pack-synthetic-fixture/v1",
        "synthetic": True, "timing_origin": "manually authored test timestamps; NOT forced alignment",
        "human_approval": False, "publication_approved": False,
        "rights": "Generated test pattern, oscillator tone and original generic test sentences; no external assets."})
    # A tiny encoded input, built entirely from FFmpeg filters. No voice, music, font download or source capture.
    source = job / "inputs/source.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=360x640:rate=30:duration=8", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000:duration=8", "-af", "volume=0.05",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ac", "1", "-movflags", "+faststart", source], job / "cache/source.log")
    words = [{"text": word, "start": start, "end": start + 0.45}
             for word, start in zip("Synthetic timing illustrates the output clock.".split(),
                                    [0.3, 1.0, 1.7, 5.3, 6.0, 6.7])]
    ranges = [{"id": "keep-one", "source": "test-pattern", "start": 0.0, "end": 3.0,
               "word_start_index": 0, "word_end_index": 2},
              {"id": "keep-two", "source": "test-pattern", "start": 5.0, "end": 8.0,
               "word_start_index": 3, "word_end_index": 5}]
    editorial = load_module("demo_editorial", engines / "Video editing engine/editorial.py")
    retimed = editorial.retime_words(words, ranges)
    mapping = editorial.build_timeline_map(ranges)
    if retimed[3]["start"] != 3.3 or mapping[1]["source_to_output_offset"] != -2:
        raise RuntimeError("Unexpected timing conversion")
    write(job / "work/source_words.json", {"words": words})
    write(job / "work/retimed_words.json", {"retimed_words": retimed})
    write(job / "work/timeline_map.json", {"timeline_map": mapping})
    write(job / "work/timing-demonstration.json", {"synthetic": True,
        "review_status": "SIMULATED timing inspection, not human approval",
        "ranges": ranges, "expected_output_duration_s": 6,
        "example": {"source_start": 5.3, "output_start": 3.3},
        "production_edl": False, "forced_alignment": False})
    # Standalone caption draft path is explicit; no fabricated production authorization is consumed.
    prefix = job / "work/draft-captions"
    python_cli("Editing_OS/Video Editing/Engines/Captions_engine/engine.py",
        ["--words-json", job / "work/retimed_words.json", "--out-prefix", prefix,
         "--width", "360", "--height", "640", "--platform", "instagram-reels",
         "--allow-unapproved-draft-treatment"], job / "cache/captions.log")
    ass_path = str(prefix.with_suffix(".ass")).replace("\\", "/").replace(":", "\\:")
    # FFmpeg filter quoting differs from shell quoting. Fail rather than interpolate ambiguous filenames.
    if any(c in ass_path for c in ("'", "[", "]", ";", ",")):
        raise ValueError("For this subtitle demo use a workspace without quotes/brackets/semicolon/comma")
    output = job / "exports/synthetic-DRAFT.mp4"
    filters = ("[0:v]trim=start=0:end=3,setpts=PTS-STARTPTS[v0];"
        "[0:v]trim=start=5:end=8,setpts=PTS-STARTPTS[v1];"
        "[0:a]atrim=start=0:end=3,asetpts=PTS-STARTPTS[a0];"
        "[0:a]atrim=start=5:end=8,asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a];"
        "[v]drawbox=x=12:y=24:w=160:h=20:color=blue@0.7:t=fill:enable='lt(t,3)',"
        "drawbox=x=188:y=24:w=160:h=20:color=orange@0.7:t=fill:enable='gte(t,3)',"
        f"subtitles='{ass_path}'[vc]")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", source,
        "-filter_complex", filters, "-map", "[vc]", "-map", "[a]", "-c:v", "libx264",
        "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", output]
    run(command, job / "cache/draft-render.log")
    repeat = job / "exports/synthetic-DRAFT-repeat.mp4"
    run([*command[:-1], repeat], job / "cache/repeat-render.log")
    probe = run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", output],
                job / "cache/probe.log")
    observed = json.loads(probe.stdout)
    video = next(s for s in observed["streams"] if s["codec_type"] == "video")
    if (video["width"], video["height"], video["nb_frames"]) != (360, 640, "180"):
        raise RuntimeError("Unexpected draft dimensions/frame count")
    write(job / "evidence/encoded-probe.json", observed)
    write(job / "work/graphic-treatment.json", {"synthetic": True, "selected_by_human": False,
        "renderer": "FFmpeg drawbox fixture, not Graphics_engine production",
        "draft_options": ["blue first / orange second", "monochrome segment bars"],
        "rendered_fixture_option": "blue first / orange second", "motion": "cut at output second 3",
        "production_taste_selection": False})
    caption_qa = json.loads(prefix.with_suffix(".qa.json").read_text(encoding="utf-8"))
    if caption_qa.get("status") != "pass":
        raise RuntimeError("Draft caption structural QA did not pass")
    caption_qa["synthetic_fixture"] = {"manually_timed": True, "forced_alignment": False,
        "human_approval": False, "publication_approved": False,
        "note": "Structural pass checks supplied test clocks only; there is no recorded speech."}
    write(prefix.with_suffix(".qa.json"), caption_qa)
    # Fresh hashes describe current toolkit bytes, but this context cannot supply genuine production evidence.
    context = json.loads((contracts / "examples/production-context.v1.example.json").read_text(encoding="utf-8"))
    context["project_id"] = "synthetic-clock-demo"
    context["objective"].update(primary_goal="Inspect a synthetic post-cut clock and authority refusals.",
        success_definition="Source 5.3 maps to output 3.3; production remains unauthorized.")
    context["deliverable"].update(width_px=360, height_px=640, target_duration_seconds=6)
    context["sources"] = [{"source_id": "test-pattern", "type": "video", "locator": str(source),
        "accessible": True, "usage_rights": "owned", "notes": "Generated pattern/tone, no speech; draft test only."}]
    for doc in context["governing_documents"]:
        doc["sha256"] = sha(ROOT / "Editing_OS" / doc["path"])
    context_path = write(job / "contracts/production-context.json", context)
    python_cli("Editing_OS/Video Editing/Contracts/validate.py", ["production-context", context_path],
               job / "cache/context-validation.log")
    # Shape-only samples retain simulated approval booleans required by their schemas. Never pass them to a gate.
    for sample in sorted((contracts / "examples").glob("*.example.json")):
        sample_path = write(job / "simulated-contracts" / ("SIMULATED-" + sample.name), json.loads(sample.read_text(encoding="utf-8")))
        kind = sample.name.split(".v1.example.json")[0]
        python_cli("Editing_OS/Video Editing/Contracts/validate.py", [kind, sample_path],
                   job / "cache" / (kind + "-shape-validation.log"))
    (job / "simulated-contracts/README.md").write_text(
        "# SIMULATED CONTRACT SHAPES ONLY\n\nAny approval/explicit_human_choice=true values are "
        "fictional schema examples. Hashes are placeholders, references are not authoritative. "
        "Never feed these files to production or claim forced alignment/review.\n", encoding="utf-8")
    adapter_path = "Editing_OS/Video Editing/Engines/Orchestration_adapter/adapter.py"
    python_cli(adapter_path, ["preflight", "--context", context_path, "--stage", "before-execution",
        "--output", job / "evidence/missing-authority.json"], job / "cache/missing-authority.log", expected=2, required_message="omits mode/feature-required evidence types")
    stale = json.loads(context_path.read_text(encoding="utf-8"))
    stale["governing_documents"][0]["sha256"] = "0" * 64
    stale_path = write(job / "contracts/stale-context.json", stale)
    python_cli(adapter_path, ["preflight", "--context", stale_path, "--stage", "before-execution",
        "--output", job / "evidence/stale-authority.json"], job / "cache/stale-authority.log", expected=2, required_message="SHA-256 mismatch")
    python_cli("Editing_OS/Video Editing/Engines/Captions_engine/engine.py",
        ["--words-json", job / "work/retimed_words.json", "--out-prefix", job / "work/refused-captions"],
        job / "cache/missing-caption-selection.log", expected=2, required_message="production captions require --taste-selection")
    # The actual encoded Quality Engine runs on both drafts. No spec/evidence/review: readiness must fail.
    qa = load_module("demo_quality", engines / "Quality_engine/qa.py")
    report = qa.run_quality_audit(output, compare_to=repeat, scan_scenes=False)
    quality_path = write(job / "evidence/quality-report.json", report)
    if not report["decode_integrity"]["passed"] or report["repeatability"]["status"] != "pass":
        raise RuntimeError("Encoded decode or repeat-render comparison failed")
    if report["ready"] or report["automated_gate_passed"]:
        raise RuntimeError("An unauthorised draft unexpectedly passed Quality")
    python_cli(adapter_path, ["assert-publishable", "--artifact", output, "--quality-report", quality_path],
               job / "cache/publication-refusal.log", expected=2, required_message="Quality Engine automated gate did not pass")
    summary = {"schema": "editing-pack-synthetic-walkthrough/v1", "synthetic": True,
        "publication_approved": False, "ready": False, "output_sha256": sha(output),
        "timing_conversion_checked": True, "encoded_frames": 180, "duration_s": 6,
        "decode_integrity_passed": True, "repeat_render_passed": True, "contract_shapes_validated": 7,
        "draft_caption_qa": str(prefix.with_suffix(".qa.json")),
        "refusals_checked": ["missing production authority", "stale governing hash",
                             "missing caption treatment selection", "unready artifact publication"],
        "quality_issue_codes": sorted({i["code"] for i in report["issues"]}),
        "scope": "Offline draft test; manual timing, FFmpeg fixture graphics, no genuine alignment/human approval/native editing."}
    write(job / "evidence/walkthrough-summary.json", summary)
    print(json.dumps({"job": str(job), "draft": str(output), "checks_passed": True,
                      "publication_approved": False, "ready": False}, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", default="synthetic-clock-demo")
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    try:
        runtime.configure_args(args)
        if runtime.root() != ROOT:
            raise ValueError("Run the walkthrough belonging to the configured toolkit root")
        if not args.job_name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.job_name):
            raise ValueError("Job name must contain only ASCII letters, numbers, dash or underscore")
        reserved = {"CON", "PRN", "AUX", "NUL", *[f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)]}
        if args.job_name.upper() in reserved:
            raise ValueError("Use a job name that is not a Windows reserved device name")
        job = runtime.output(runtime.workspace_root() / "jobs" / args.job_name, require_workspace=True)
        build(job)
    except (ValueError, OSError, RuntimeError, ImportError, subprocess.TimeoutExpired) as exc:
        print(f"Synthetic walkthrough stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

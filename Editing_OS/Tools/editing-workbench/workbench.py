"""Owned review-first finishing handoff. Run with Python 3.11+; no installs."""
from __future__ import annotations

# Resolve only this standalone toolkit's owned shared runtime module.
import sys as _runtime_sys
from pathlib import Path as _RuntimePath
for _runtime_parent in _RuntimePath(__file__).resolve().parents:
    if (_runtime_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_runtime_parent))
        break
import runtime_paths as runtime

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
import xml.etree.ElementTree as ET

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

KIT_REL = Path(".")


def toolkit_root() -> Path:
    return runtime.root()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, payload) -> None:
    runtime.output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never publish a partly written capability/verification file.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False, suffix=".tmp") as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    try:
        # Windows scanners/indexers can briefly hold an existing JSON file.
        for attempt in range(4):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if temporary.exists():
            temporary.unlink()


def run(args: list[str], timeout=180) -> str:
    result = subprocess.run(runtime.command(args), env=runtime.child_env(), **runtime.child_kwargs(), capture_output=True, encoding="utf-8", errors="replace",
                            timeout=timeout, check=False)
    if result.returncode:
        raise ValueError(f"{Path(args[0]).name} failed: {result.stderr[-1500:]}")
    return result.stdout


def doctor(scratch: Path, premiere=False) -> dict:
    runtime.output(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryFile(dir=scratch) as stream:
            stream.write(b"editing-workbench write test")
            stream.flush()
    except OSError as exc:
        raise ValueError("Folder write failed. Check Controlled Folder Access or move the job.") from exc
    windows = platform.system() == "Windows"
    installs = {
        "ffmpeg": "winget install --id Gyan.FFmpeg --exact" if windows else "brew install ffmpeg",
        "ffprobe": "winget install --id Gyan.FFmpeg --exact" if windows else "brew install ffmpeg",
        "uv": "winget install --id astral-sh.uv --exact" if windows else "brew install uv",
        "git": "winget install --id Git.Git --exact" if windows else "brew install git",
        "node": "winget install --id OpenJS.NodeJS.LTS --exact" if windows else "brew install node@22",
    }
    names = ["ffmpeg", "ffprobe", "uv", "git"] + (["node"] if premiere else [])
    tools = {}
    for name in names:
        path = runtime.tool(name, required=False)
        item = {"path": path, "available": bool(path), "install_if_approved": installs[name]}
        if path:
            flag = "-version" if name in {"ffmpeg", "ffprobe"} else "--version"
            item["version"] = run([path, flag]).splitlines()[0]
            if name == "node":
                item["available"] = int(item["version"].lstrip("v").split(".")[0]) >= 22
        tools[name] = item
    uv = shutil.which("uv")
    interpreter = None
    if uv:
        # Discovery must not trigger an implicit download/install.
        result = subprocess.run([uv, "python", "find", "3.11", "--no-python-downloads"],
                                capture_output=True, text=True, timeout=30, **runtime.child_kwargs())
        if result.returncode == 0:
            interpreter = result.stdout.strip()
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git/bin/bash.exe"
    return {"schema": "editing-machine-check/v1", "os": platform.system(),
            "write_test": "passed", "tools": tools, "uv_python_311": interpreter,
            "python_install_if_approved": None if interpreter else "uv python install 3.11",
            "git_bash": str(git_bash) if windows and git_bash.is_file() else None,
            "installed_anything": False,
            "whisper_cache": str(runtime.workspace_root() / "dependencies/model-cache") if runtime.workspace_root(required=False) else None,
            "note": "No system Python substitution; install commands require operator approval."}


def frame(seconds, fps: Fraction) -> int:
    value = Fraction(str(seconds)) * fps
    if value < 0:
        raise ValueError("Negative cut point")
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def timecode_frames(value: str, fps: Fraction) -> int:
    import re
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})", value)
    if not match:
        raise ValueError(f"Unsupported embedded timecode {value!r}")
    hh, mm, ss, separator, ff = match.groups()
    hh, mm, ss, ff = map(int, (hh, mm, ss, ff))
    nominal = round(fps)
    if hh > 23 or mm > 59 or ss > 59 or ff >= nominal:
        raise ValueError("Invalid embedded timecode")
    result = ((hh * 60 + mm) * 60 + ss) * nominal + ff
    if separator == ";":
        if fps not in {Fraction(30000, 1001), Fraction(60000, 1001)}:
            raise ValueError("Drop-frame timecode requires 29.97 or 59.94 fps")
        dropped = 2 if nominal == 30 else 4
        if mm % 10 and ss == 0 and ff < dropped:
            raise ValueError("Timecode refers to a dropped frame number")
        minutes = hh * 60 + mm
        result -= dropped * (minutes - minutes // 10)
    return result


def inspect(path: Path) -> dict:
    path = path.resolve(strict=True)
    probe = shutil.which("ffprobe")
    if not probe:
        raise ValueError("ffprobe is missing; run doctor")
    data = json.loads(run([probe, "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", str(path)]))
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("Source has no video stream")
    fps = Fraction(video["r_frame_rate"])
    if not 0 < fps <= 240:
        raise ValueError("Unsupported frame rate")
    frames = json.loads(run([probe, "-v", "error", "-select_streams", "v:0",
                             "-show_frames", "-show_entries", "frame=best_effort_timestamp_time",
                             "-of", "json", str(path)], timeout=600))["frames"]
    points = [Fraction(f["best_effort_timestamp_time"]) for f in frames
              if "best_effort_timestamp_time" in f]
    if len(points) != len(frames) or len(points) < 2:
        raise ValueError("Need at least two timestamped frames")
    interval = 1 / fps
    cfr = all(abs((right - left) - interval) <= Fraction(1, 10000)
              for left, right in zip(points, points[1:]))
    rotation = next((int(float(s.get("rotation", 0))) for s in video.get("side_data_list", [])
                     if "rotation" in s), 0) % 360
    width, height = video["width"], video["height"]
    tags = {}
    for stream in data["streams"]:
        tags.update(stream.get("tags", {}))
    tags.update(data.get("format", {}).get("tags", {}))
    tc = tags.get("timecode", "00:00:00:00")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    return {"path": str(path), "sha256": sha(path), "fps": str(fps),
            "width": width, "height": height, "rotation": rotation,
            "display_width": height if rotation in {90, 270} else width,
            "display_height": width if rotation in {90, 270} else height,
            "sample_aspect_ratio": video.get("sample_aspect_ratio", "1:1"),
            "frame_count": len(points), "constant_frame_rate": cfr,
            "first_pts": str(points[0]), "timecode": tc,
            "timecode_start_frame": timecode_frames(tc, fps),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
            "audio_channels": audio.get("channels", 0),
            "audio_sample_rate": audio.get("sample_rate"),
            "color_transfer": video.get("color_transfer", "unknown"),
            "transcript_cache_key": "sha256:" + sha(path),
            "note": "Cache reuse also requires model, language, aligner and correction identity."}


def adapter(kit: Path):
    path = kit / "Editing_OS/Video Editing/Engines/Orchestration_adapter/adapter.py"
    spec = importlib.util.spec_from_file_location("editing_owned_adapter", path)
    if spec is None or spec.loader is None:
        raise ValueError("Owned adapter unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def editorial(kit: Path):
    path = kit / "Editing_OS/Video Editing/Engines/Video editing engine/editorial.py"
    spec = importlib.util.spec_from_file_location("editing_owned_editorial", path)
    if spec is None or spec.loader is None:
        raise ValueError("Editorial validator unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_words(edl: dict) -> dict:
    words = edl.get("editorial", {}).get("source_words")
    if isinstance(words, list) and len(edl.get("sources", {})) == 1 and words:
        return {next(iter(edl["sources"])): words}
    if isinstance(words, dict) and set(words) == set(edl["sources"]):
        return words
    raise ValueError("Word-safe frame handoff requires source_words for every EDL source")


def snap_edl(kit: Path, path: Path) -> dict:
    payload = load(path)
    edl = copy.deepcopy(payload.get("edl", payload))
    words = source_words(edl)
    if len(words) != 1:
        raise ValueError("Draft snapping currently supports a single speech source")
    plan = make_plan(kit, path)
    for segment, clip in zip(edl["ranges"], plan["clips"]):
        segment.update(clip["normalized_seconds"])
        if "word_start_s" in segment:
            segment["pad_in_s"] = segment["word_start_s"] - segment["start"]
        if "word_end_s" in segment:
            segment["pad_out_s"] = segment["end"] - segment["word_end_s"]
    owner = editorial(kit)
    e = edl["editorial"]
    e["timeline_map"] = owner.build_timeline_map(edl["ranges"])
    e["retimed_words"] = owner.retime_words(next(iter(words.values())), edl["ranges"])
    edl["total_duration_s"] = sum(s["end"] - s["start"] for s in edl["ranges"])
    # Timing changed: discard proposals keyed to the old output clock. Replan downstream.
    for key in ("handoffs", "rhythm_plan", "qa_plan", "validation"):
        e.pop(key, None)
    if edl.get("overlays") or edl.get("subtitles"):
        raise ValueError("Snap a clean rough EDL before attaching timed overlays/subtitles")
    owner.assert_edl_valid(edl, words)
    # Paths were originally relative to the input EDL, not the destination.
    edl["sources"] = {key: info["path"] for key, info in plan["media"].items()}
    return edl


def normalize(edl: dict, media: dict, *, approved=False) -> dict:
    if not edl.get("ranges") or not edl.get("sources"):
        raise ValueError("Need existing EDL sources and ranges; cuts.json is reference-only")
    rates = {info["fps"] for info in media.values()}
    geometry = {(i["display_width"], i["display_height"]) for i in media.values()}
    if len(rates) != 1 or len(geometry) != 1:
        raise ValueError("Mixed rates or dimensions need a separately reviewed conform")
    if any(not i["constant_frame_rate"] or i["first_pts"] != "0" for i in media.values()):
        raise ValueError("VFR/non-zero PTS needs an explicit conform, realignment and EDL reapproval")
    fps = Fraction(next(iter(rates)))
    cursor, clips = 0, []
    for index, segment in enumerate(edl["ranges"]):
        source = str(segment["source"])
        info = media[source]
        start, end = frame(segment["start"], fps), frame(segment["end"], fps)
        if end <= start or end > info["frame_count"]:
            raise ValueError(f"Invalid range {index + 1}")
        snapped = {"start": float(Fraction(start, 1) / fps), "end": float(Fraction(end, 1) / fps)}
        if approved and any(abs(Fraction(str(segment[k])) - Fraction(str(snapped[k]))) >
                            Fraction(1, 1000000) for k in snapped):
            raise ValueError("EDL is off the frame grid. Review normalized ranges and reapprove the EDL.")
        clips.append({"id": segment.get("id", f"clip-{index + 1:04}"), "source": source,
                      "source_start_frame": start, "source_end_frame_exclusive": end,
                      "record_start_frame": cursor, "duration_frames": end - start,
                      "normalized_seconds": snapped})
        cursor += end - start
    width, height = next(iter(geometry))
    return {"schema": "editing-frame-handoff/v1", "fps": str(fps), "width": width,
            "height": height, "total_frames": cursor, "clips": clips, "media": media,
            "native_import_verified": False, "publishable": False,
            "status": "approved-timing" if approved else "draft-needs-edl-reapproval",
            "limitations": ["Rough cut only; selected treatments are not transferred.",
                             "EDL approval binds paths/timing, not the raw source bytes at review time.",
                             "Source hashes below guard subsequent handoffs; verify source identity at EDL review.",
                             "Native app import/playback and final Quality gate remain required."]}


def make_plan(kit: Path, edl_path: Path, authorization: Path | None = None) -> dict:
    auth = None
    if authorization:
        owner = adapter(kit)
        auth, _ = owner._verified_edl_authorization(authorization)
        bound = Path(auth["artifacts"]["edl"]["path"])
        if bound.resolve() != edl_path.resolve():
            raise ValueError("EDL path differs from adapter authorization")
        context = load(Path(auth["artifacts"]["production_context"]["path"]))
        owner.verify_governing_documents(context, editing_os_root=kit / "Editing_OS")
    payload = load(edl_path)
    edl = payload.get("edl", payload)
    if auth:
        editorial(kit).assert_edl_valid(edl, source_words(edl))
    media = {}
    for source, value in edl["sources"].items():
        path = Path(value)
        if not path.is_absolute():
            path = edl_path.parent / path
        media[source] = inspect(path)
    result = normalize(edl, media, approved=bool(auth))
    result["edl"] = {"path": str(edl_path.resolve()), "sha256": sha(edl_path)}
    if auth:
        result["authorization"] = {"path": str(authorization.resolve()), "sha256": sha(authorization)}
        result["project_id"] = auth["project_id"]
    return result


def verify_plan(plan: dict, kit: Path) -> None:
    if plan.get("schema") != "editing-frame-handoff/v1" or plan.get("status") != "approved-timing":
        raise ValueError("Export requires an approved frame handoff")
    auth = plan.get("authorization", {})
    if sha(Path(auth["path"])) != auth["sha256"]:
        raise ValueError("Authorization changed")
    rebuilt = make_plan(kit, Path(plan["edl"]["path"]), Path(auth["path"]))
    if rebuilt != plan:
        raise ValueError("Frame handoff changed or source/approval is stale")


def rational_time(frames: int, fps: Fraction) -> str:
    time = Fraction(frames, 1) / fps
    return f"{time.numerator}/{time.denominator}s"


def require_dtd_version(dtd: Path, version: str) -> None:
    expected = "FCPXMLv" + version.replace(".", "_") + ".dtd"
    if dtd.name.casefold() != expected.casefold():
        raise ValueError(f"FCPXML {version} requires the matching installed {expected}")


def fcpxml(plan: dict, name: str, library: Path, version="1.10") -> bytes:
    if version not in {"1.10", "1.11", "1.12", "1.13"}:
        raise ValueError("Unsupported FCPXML version; use an installed DTD")
    if not name.strip() or library.suffix != ".fcpbundle" or library.exists():
        raise ValueError("Use a named edit and a NEW .fcpbundle path")
    if any(i["rotation"] or i["sample_aspect_ratio"] not in {"1:1", "N/A"}
           for i in plan["media"].values()):
        raise ValueError("FCPXML rotation/non-square pixels need a reviewed conform")
    fps = Fraction(plan["fps"])
    root = ET.Element("fcpxml", version=version)
    options = ET.SubElement(root, "import-options")
    for key, value in [("library location", library.resolve().as_uri()),
                       ("copy assets", "0"), ("suppress warnings", "1")]:
        ET.SubElement(options, "option", key=key, value=value)
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="r1", frameDuration=rational_time(1, fps),
                  width=str(plan["width"]), height=str(plan["height"]))
    refs = {}
    for index, (source, info) in enumerate(sorted(plan["media"].items()), start=2):
        refs[source] = f"r{index}"
        attributes = {"id": refs[source], "name": Path(info["path"]).name, "format": "r1",
                      "start": rational_time(info["timecode_start_frame"], fps),
                      "duration": rational_time(info["frame_count"], fps), "hasVideo": "1"}
        if info["has_audio"]:
            attributes.update(hasAudio="1", audioSources="1",
                              audioChannels=str(info.get("audio_channels", 2)))
        asset = ET.SubElement(resources, "asset", attributes)
        ET.SubElement(asset, "media-rep", kind="original-media", src=Path(info["path"]).as_uri())
    event = ET.SubElement(ET.SubElement(root, "library"), "event", name=name)
    project = ET.SubElement(event, "project", name=name)
    sequence = ET.SubElement(project, "sequence", format="r1", tcStart="0s", tcFormat="NDF",
                            duration=rational_time(plan["total_frames"], fps))
    spine = ET.SubElement(sequence, "spine")
    for clip in plan["clips"]:
        info = plan["media"][clip["source"]]
        ET.SubElement(spine, "asset-clip", name=str(clip["id"]), ref=refs[clip["source"]],
                      offset=rational_time(clip["record_start_frame"], fps),
                      start=rational_time(info["timecode_start_frame"] + clip["source_start_frame"], fps),
                      duration=rational_time(clip["duration_frames"], fps))
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="utf-8")


def compare(plan: dict, actual: dict) -> dict:
    errors = []
    if actual.get("fps") != plan["fps"]:
        errors.append("Frame rate differs (use reduced rational fps)")
    if actual.get("total_frames") != plan["total_frames"]:
        errors.append("Total frame count differs")
    wanted, landed = plan["clips"], actual.get("clips", [])
    if len(wanted) != len(landed):
        errors.append("Clip count differs")
    for index, (left, right) in enumerate(zip(wanted, landed), 1):
        for field in ("source", "source_start_frame", "source_end_frame_exclusive",
                      "record_start_frame", "duration_frames"):
            if isinstance(right.get(field), bool) or right.get(field) != left[field]:
                errors.append(f"Clip {index}: {field} differs")
    return {"schema": "editing-handoff-readback/v1", "passed": not errors,
            "errors": errors, "publishable": False,
            "note": "Requires independently extracted native timeline data; this checks structure, not playback."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor")
    check.add_argument("--scratch", type=Path, default=None)
    check.add_argument("--premiere", action="store_true")
    check.add_argument("--out", type=Path, required=True)
    probe = commands.add_parser("inspect")
    probe.add_argument("source", type=Path)
    probe.add_argument("--out", type=Path, required=True)
    build = commands.add_parser("plan")
    build.add_argument("--edl", type=Path, required=True)
    build.add_argument("--authorization", type=Path)
    build.add_argument("--out", type=Path, required=True)
    snap = commands.add_parser("snap-edl", help="Create a word-safe frame-grid draft; MUST reapprove")
    snap.add_argument("--edl", type=Path, required=True)
    snap.add_argument("--out", type=Path, required=True)
    export = commands.add_parser("fcpxml")
    export.add_argument("--plan", type=Path, required=True)
    export.add_argument("--name", required=True)
    export.add_argument("--library", type=Path, required=True)
    export.add_argument("--version", default="1.10")
    export.add_argument("--dtd", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    diff = commands.add_parser("compare")
    diff.add_argument("--plan", type=Path, required=True)
    diff.add_argument("--readback", type=Path, required=True)
    diff.add_argument("--out", type=Path, required=True)
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    if args.kit:
        runtime.configure(toolkit_root=args.kit)
    args.kit = runtime.root()
    runtime.guard_args(args, ("out", "scratch"))
    try:
        if args.command == "doctor":
            result = doctor(args.scratch or runtime.output(runtime.workspace_root() / "cache/doctor", require_workspace=True), args.premiere)
        elif args.command == "inspect":
            result = inspect(args.source)
        elif args.command == "plan":
            result = make_plan(args.kit.resolve(), args.edl.resolve(), args.authorization)
        elif args.command == "snap-edl":
            if args.out.resolve() == args.edl.resolve() or args.out.exists():
                raise ValueError("Use a new output EDL path; do not overwrite the reviewed source")
            result = snap_edl(args.kit.resolve(), args.edl.resolve())
            write(args.out.with_name(args.out.stem + ".timeline_map.json"),
                  {"timeline_map": result["editorial"]["timeline_map"]})
            write(args.out.with_name(args.out.stem + ".retimed_words.json"),
                  {"retimed_words": result["editorial"]["retimed_words"]})
        elif args.command == "compare":
            plan = load(args.plan)
            verify_plan(plan, args.kit.resolve())
            result = compare(plan, load(args.readback))
        else:
            plan = load(args.plan)
            verify_plan(plan, args.kit.resolve())
            validator = shutil.which("xmllint")
            if not validator or not args.dtd.is_file():
                raise ValueError("FCPXML export requires xmllint and Final Cut's installed DTD")
            require_dtd_version(args.dtd, args.version)
            data = fcpxml(plan, args.name, args.library, args.version)
            # Validate before replacing any output; DTD copied to a path without spaces.
            with tempfile.TemporaryDirectory(prefix="fcpxml-", dir=Path(tempfile.gettempdir())) as tmp:
                tmp = Path(tmp)
                dtd = tmp / "fcpxml.dtd"
                xml = tmp / "edit.fcpxml"
                shutil.copyfile(args.dtd, dtd)
                xml.write_bytes(data)
                run([validator, "--nonet", "--noout", "--dtdvalid", str(dtd), str(xml)])
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(data)
            result = {"output": str(args.out.resolve()), "sha256": sha(args.out),
                      "dtd_sha256": sha(args.dtd), "dtd_validated": True,
                      "native_import_verified": False, "publishable": False}
            write(args.out.with_suffix(".handoff.json"), result)
            print(json.dumps(result, indent=2))
            return 0
        write(args.out, result)
        print(json.dumps({"output": str(args.out.resolve()), "status": result.get("status"),
                          "passed": result.get("passed"), "publishable": False}))
        return 1 if result.get("passed") is False else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

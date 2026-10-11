"""Production caption engine CLI.

Audio or aligned words -> semantic caption plan -> ARETE ASS + HyperFrames JSON
+ a machine-readable QA report.
"""

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
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import align
import emit
import validate
from phrasing import Config, PLATFORM_DEFAULTS, segment_words


EDITING_OS_DIR = Path(__file__).resolve().parents[3]


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json_value(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extract_array(payload, key):
    values = payload.get(key) if isinstance(payload, Mapping) else payload
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} must contain a non-empty array")
    if not all(isinstance(item, Mapping) for item in values):
        raise ValueError(f"{key} entries must be objects")
    return [dict(item) for item in values]


def _load_selected_treatment(path):
    source = Path(path).resolve()
    payload = _load_json_value(source)
    if not isinstance(payload, Mapping):
        raise ValueError("taste selection must be a JSON object")
    validator_path = EDITING_OS_DIR / "Video Editing" / "Contracts" / "validate.py"
    spec = importlib.util.spec_from_file_location(
        "arete_caption_contract_validation", validator_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load contract validator: {validator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors = module.validate_document("taste-selection", payload)
    if errors:
        rendered = "; ".join(
            f"{item.get('path', '$')}: {item.get('message', 'invalid')}"
            for item in errors[:20]
        )
        raise ValueError(f"taste-selection contract is invalid: {rendered}")
    selected_id = payload["selection"]["selected_option_id"]
    selected = next(
        (
            option for option in payload["options"]
            if option.get("option_id") == selected_id
        ),
        None,
    )
    if selected is None or selected.get("status") != "selected":
        raise ValueError("taste-selection does not contain its selected option")
    tokens = selected.get("treatment_tokens")
    if not isinstance(tokens, Mapping):
        raise ValueError(
            "Captions Engine requires embedded treatment_tokens; materialize a "
            "hash-bound treatment_artifact before rendering"
        )
    caption = tokens["captions"]
    typography = tokens["typography"]
    body_family = str(typography["body_family"])
    if body_family.casefold() not in {"arial", "inter"}:
        raise ValueError(
            "selected caption font is not available to the deterministic ASS "
            "renderer; use Windows Arial or the Editing OS bundled Inter family"
        )
    cfg_values = {
        "max_chars_per_line": int(caption["max_chars_per_line"]),
        "max_words_per_caption": int(caption["max_words_per_caption"]),
        "max_lines": int(caption["max_lines"]),
        "min_caption_dur": float(caption["minimum_exposure_ms"]) / 1000.0,
        "max_caption_dur": float(caption["maximum_caption_duration_ms"]) / 1000.0,
        "reading_behavior": str(caption["reading_behavior"]),
    }
    style_values = {
        "font": body_family,
        "font_size": float(caption["font_size_short_edge_px"]),
        "primary": str(caption["primary_color"]),
        "accent": str(caption["accent_color"]),
        "outline": str(caption["outline_color"]),
        "outline_px": float(caption["outline_px"]),
        "shadow_px": float(caption["shadow_px"]),
        "emphasis_scale": int(caption["emphasis_scale_percent"]),
        "entry_ms": int(caption["entry_ms"]),
        "exit_ms": int(caption["exit_ms"]),
        "motion": str(caption["motion"]),
    }
    provenance = {
        "source": "taste-selection/v1",
        "taste_selection_path": str(source),
        "taste_selection_sha256": _sha256_file(source),
        "selected_option_id": str(selected_id),
        "treatment_sha256": _canonical_sha256(tokens),
        "selected_by": str(payload["selection"]["selected_by"]),
        "selected_at": str(payload["selection"]["selected_at"]),
    }
    return cfg_values, style_values, provenance


def _post_cut_timing(
    forced_alignment_path,
    timeline_map_path,
    retimed_words_path,
    *,
    authorization_path=None,
    taste_selection_path=None,
):
    forced_path = Path(forced_alignment_path).resolve()
    timeline_path = Path(timeline_map_path).resolve()
    words_path = Path(retimed_words_path).resolve()
    timeline = _extract_array(_load_json_value(timeline_path), "timeline_map")
    words = _extract_array(_load_json_value(words_path), "retimed_words")
    timing = {
        "source_of_truth": "post-cut-retimed-words",
        "forced_alignment_sha256": _sha256_file(forced_path),
        "timeline_map_sha256": _sha256_file(timeline_path),
        "retimed_words_sha256": _sha256_file(words_path),
        "timeline_fingerprint": _canonical_sha256({
            "timeline_map": timeline,
            "retimed_words": words,
        }),
    }
    if authorization_path is not None:
        auth_path = Path(authorization_path).resolve()
        authorization = _load_json_value(auth_path)
        if not isinstance(authorization, Mapping):
            raise ValueError("caption render authorization must be an object")
        if (
            authorization.get("schema")
            != "arete-caption-render-authorization/v1"
            or authorization.get("status") != "pass"
        ):
            raise ValueError("caption render authorization did not pass")
        expected = {
            "timeline_map": (timeline_path, timing["timeline_map_sha256"]),
            "retimed_words": (words_path, timing["retimed_words_sha256"]),
        }
        for label, (path, digest) in expected.items():
            reference = authorization.get(label)
            if not isinstance(reference, Mapping):
                raise ValueError(f"caption authorization has no {label} identity")
            if Path(str(reference.get("path") or "")).resolve() != path:
                raise ValueError(f"caption authorization {label} path mismatch")
            if reference.get("sha256") != digest:
                raise ValueError(f"caption authorization {label} hash mismatch")
        forced = authorization.get("forced_alignment")
        if not isinstance(forced, Mapping) or (
            forced.get("sha256") != timing["forced_alignment_sha256"]
        ):
            raise ValueError("caption authorization forced-alignment hash mismatch")
        if authorization.get("timeline_fingerprint") != timing["timeline_fingerprint"]:
            raise ValueError("caption authorization timeline fingerprint mismatch")
        if taste_selection_path is None:
            raise ValueError("caption authorization requires taste-selection identity")
        taste_path = Path(taste_selection_path).resolve()
        taste = authorization.get("taste_selection")
        if not isinstance(taste, Mapping):
            raise ValueError("caption authorization has no taste-selection identity")
        if (
            Path(str(taste.get("path") or "")).resolve() != taste_path
            or taste.get("sha256") != _sha256_file(taste_path)
        ):
            raise ValueError("caption authorization taste-selection mismatch")
        timing["caption_render_authorization_sha256"] = _sha256_file(auth_path)
    return timing


def _atomic_write(path, content):
    path = Path(path)
    runtime.output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp",
    )
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _remove_render_artifacts(*paths):
    """Remove renderable artifacts before publishing a failing strict QA report."""
    for path in paths:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass


def load_words_json(path):
    """Load aligned words from a list, ``{words}``, ``{retimed_words}``, or segments."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        words = data
    elif isinstance(data, dict) and isinstance(data.get("words"), list):
        words = data["words"]
    elif isinstance(data, dict) and isinstance(data.get("retimed_words"), list):
        words = data["retimed_words"]
    elif isinstance(data, dict) and isinstance(data.get("segments"), list):
        words = [
            word
            for segment in data["segments"]
            for word in segment.get("words", [])
        ]
    else:
        raise align.AlignmentError(
            "words JSON must be a word list, {'words': [...]}, "
            "{'retimed_words': [...]}, or {'segments': [...]}"
        )
    return align.normalize_words(words, source="provided-aligned")


def run(
    audio=None,
    out_prefix="captions",
    script=None,
    model="base",
    backend="auto",
    playres=(1080, 1920),
    cfg=None,
    words=None,
    platform=None,
    style_overrides=None,
    treatment_provenance=None,
    post_cut_timing=None,
    strict=True,
):
    """Build all caption artifacts and return the semantic segments.

    ``words`` is the deterministic integration path for an upstream WhisperX
    stage.  Supplying it bypasses transcription but not normalization, optional
    corrected-script mapping, phrasing, style selection or QA.
    """
    runtime.output(out_prefix)
    if cfg is None:
        cfg = Config.for_platform(platform or "instagram-reels")
    elif platform and platform != cfg.platform:
        cfg = cfg.with_overrides(platform=platform)

    if words is None:
        if not audio:
            raise align.AlignmentError("audio or pre-aligned words are required")
        words = align.transcribe_words(audio, model=model, backend=backend)
    else:
        words = align.normalize_words(words, source="provided-aligned")

    if script:
        with open(script, encoding="utf-8") as handle:
            words = align.force_align_to_script(words, handle.read())

    segments = segment_words(words, cfg)
    profile = emit.get_style_profile(cfg.platform, playres, style_overrides)
    report = validate.build_qa_report(words, segments, cfg, profile)
    report["source_fingerprint"] = emit.source_fingerprint(segments, cfg, profile)
    if treatment_provenance is not None:
        report["treatment"] = dict(treatment_provenance)
    if post_cut_timing is not None:
        report["post_cut_timing"] = dict(post_cut_timing)

    ass_path = f"{out_prefix}.ass"
    json_path = f"{out_prefix}.captions.json"
    qa_path = f"{out_prefix}.qa.json"
    if strict and report["summary"]["errors"]:
        # A QA report describes one source fingerprint. Never leave older ASS or
        # JSON outputs beside it where an orchestrator could consume stale work.
        _remove_render_artifacts(ass_path, json_path)
        _atomic_write(qa_path, validate.dumps_report(report))
        validate.raise_for_errors(report)
    _atomic_write(qa_path, validate.dumps_report(report))

    ass_text = emit.to_ass(segments, cfg, playres, profile=profile)
    hyperframes = emit.to_hyperframes(segments, cfg, playres, profile=profile)
    hyperframes["qa"] = report["summary"]
    if treatment_provenance is not None:
        hyperframes["treatment"] = dict(treatment_provenance)
    if post_cut_timing is not None:
        hyperframes["post_cut_timing"] = dict(post_cut_timing)
    hyperframes_text = json.dumps(
        hyperframes, indent=2, ensure_ascii=False, sort_keys=True
    ) + "\n"
    _atomic_write(ass_path, ass_text)
    _atomic_write(json_path, hyperframes_text)

    print(
        f"words: {len(words)}  segments: {len(segments)}  "
        f"qa: {report['status']} ({report['summary']['warnings']} warnings)"
    )
    print(f"wrote: {ass_path}")
    print(f"wrote: {json_path}")
    print(f"wrote: {qa_path}")
    return segments


def _parser():
    parser = argparse.ArgumentParser(
        description="Word-aligned, semantic caption engine (ASS + HyperFrames + QA)."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--audio", help="input audio/video file")
    source.add_argument(
        "--words-json", help="pre-aligned word JSON from WhisperX/another forced aligner"
    )
    parser.add_argument(
        "--script",
        help=(
            "correction-only script for names/terminology; cannot omit aligned "
            "spoken words (perform cuts and realign first)"
        ),
    )
    parser.add_argument("--out-prefix", default="captions", help="output path prefix")
    parser.add_argument("--model", default="base", help="Whisper model name")
    parser.add_argument(
        "--backend", default="auto", choices=["auto", "whisperx", "whisper"],
        help=(
            "alignment backend: auto/whisperx require forced alignment; raw "
            "Whisper timestamps are lower-confidence and must be requested explicitly"
        ),
    )
    parser.add_argument(
        "--platform", default="instagram-reels", choices=sorted(PLATFORM_DEFAULTS),
        help="delivery geometry and safe-area profile",
    )
    parser.add_argument(
        "--taste-selection",
        help="validated taste-selection/v1 JSON whose selected tokens drive production captions",
    )
    parser.add_argument(
        "--forced-alignment-evidence",
        help="forced-alignment evidence envelope used to bind caption timing",
    )
    parser.add_argument(
        "--timeline-map",
        help="approved post-cut timeline-map JSON paired with --words-json",
    )
    parser.add_argument(
        "--caption-render-authorization",
        help="adapter-issued capability binding EDL approval, forced alignment, clock, and taste",
    )
    parser.add_argument(
        "--allow-unapproved-draft-treatment",
        action="store_true",
        help="permit historical platform defaults for an explicit non-production draft",
    )
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--max-chars", type=int, help="maximum characters per visual line")
    parser.add_argument("--max-words", type=int, help="maximum words per semantic caption")
    parser.add_argument("--max-dur", type=float, help="maximum spoken span per caption")
    parser.add_argument("--min-dur", type=float, help="minimum on-screen exposure")
    parser.add_argument(
        "--reading-behavior", choices=["auto", "full-reading", "skimming", "glancing"],
        default="auto",
    )
    parser.add_argument("--font", help="ASS/HyperFrames font-family override")
    parser.add_argument(
        "--font-size", type=float,
        help="font size at a 1080px short-edge reference (portrait or landscape)",
    )
    parser.add_argument("--accent", help="meaning-word accent as #RRGGBB")
    parser.add_argument(
        "--allow-qa-errors", action="store_true",
        help="write render artifacts despite QA errors (QA report is always written)",
    )
    parser.add_argument("--print-profiles", action="store_true", help="list platform profiles and exit")
    parser.add_argument("--selftest", action="store_true", help="run pure-Python tests and exit")
    return parser


def main(argv=None):
    parser = _parser()
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)

    if args.selftest:
        import test_engine

        return test_engine.run_all()
    if args.print_profiles:
        for platform in sorted(PLATFORM_DEFAULTS):
            profile = emit.STYLE_PROFILES[platform]
            print(f"{platform:18} {profile['name']:27} {profile['density']}")
        return 0
    if not args.audio and not args.words_json:
        parser.error("--audio or --words-json is required (or use --selftest/--print-profiles)")

    treatment_provenance = None
    post_cut_timing = None
    if args.taste_selection:
        if (
            not args.words_json
            or not args.forced_alignment_evidence
            or not args.timeline_map
            or not args.caption_render_authorization
        ):
            parser.error(
                "production captions require --words-json, "
                "--forced-alignment-evidence, --timeline-map, and "
                "--caption-render-authorization with --taste-selection"
            )
        manual_overrides = {
            "--max-chars": args.max_chars,
            "--max-words": args.max_words,
            "--max-dur": args.max_dur,
            "--min-dur": args.min_dur,
            "--font": args.font,
            "--font-size": args.font_size,
            "--accent": args.accent,
        }
        conflicts = [name for name, value in manual_overrides.items() if value is not None]
        if conflicts:
            parser.error(
                "selected treatment is immutable; remove manual overrides: "
                + ", ".join(conflicts)
            )
        cfg_values, style_overrides, treatment_provenance = (
            _load_selected_treatment(args.taste_selection)
        )
        cfg = Config.for_platform(args.platform, **cfg_values)
        post_cut_timing = _post_cut_timing(
            args.forced_alignment_evidence,
            args.timeline_map,
            args.words_json,
            authorization_path=args.caption_render_authorization,
            taste_selection_path=args.taste_selection,
        )
    else:
        if not args.allow_unapproved_draft_treatment:
            parser.error(
                "production captions require --taste-selection; use "
                "--allow-unapproved-draft-treatment only for an explicit draft"
            )
        cfg = Config.for_platform(
            args.platform,
            max_chars_per_line=args.max_chars,
            max_words_per_caption=args.max_words,
            max_caption_dur=args.max_dur,
            min_caption_dur=args.min_dur,
            reading_behavior=args.reading_behavior,
        )
        style_overrides = {
            "font": args.font,
            "font_size": args.font_size,
            "accent": args.accent,
        }
    try:
        runtime.guard_args(args, ("out_prefix",))
        words = load_words_json(args.words_json) if args.words_json else None
        run(
            audio=args.audio,
            out_prefix=args.out_prefix,
            script=args.script,
            model=args.model,
            backend=args.backend,
            playres=(args.width, args.height),
            cfg=cfg,
            words=words,
            style_overrides=style_overrides,
            treatment_provenance=treatment_provenance,
            post_cut_timing=post_cut_timing,
            strict=not args.allow_qa_errors,
        )
    except (
        align.AlignmentError,
        validate.CaptionValidationError,
        ValueError,
        OSError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        print(f"caption engine: {exc}", file=sys.stderr)
        if isinstance(exc, validate.CaptionValidationError):
            print("See the .qa.json report for exact failures.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import qa


def synthetic_video(path: Path, *, color_variant: bool = False,
                    with_audio: bool = True) -> None:
    video_filter = (
        "testsrc2=size=320x180:rate=30:duration=1.2"
        if not color_variant else
        "smptebars=size=320x180:rate=30:duration=1.2"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", video_filter,
    ]
    if with_audio:
        command.extend([
            "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=1.2",
        ])
    command.extend([
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ])
    if with_audio:
        command.extend(["-c:a", "aac", "-b:a", "128k", "-shortest"])
    else:
        command.append("-an")
    command.extend(["-movflags", "+faststart", str(path)])
    subprocess.run(command, check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def governing_documents() -> list[dict]:
    return [
        {"role": role, "path": f"C:/contracts/{role}.md", "sha256": "a" * 64}
        for role in sorted(qa.REQUIRED_GOVERNING_DOCUMENT_ROLES)
    ]


def write_context(
    root: Path,
    *,
    requirements: list[dict] | None = None,
    mode: str = "quick",
    artifact_type: str = "video_edit",
    name: str = "production-context.json",
) -> Path:
    default_requirements = [
        {
            "evidence_id": "quality-report",
            "evidence_type": "quality_report",
            "stage": "before-final-render",
            "schema_id": qa.SCHEMA,
            "expected_path": str((root / "quality-report.json").resolve()),
            "required": True,
        },
        {
            "evidence_id": "artifact-review",
            "evidence_type": "artifact_bound_human_review",
            "stage": "before-final-render",
            "schema_id": qa.REVIEW_SCHEMA,
            "expected_path": str((root / "human-review.json").resolve()),
            "required": True,
        },
    ]
    context = {
        "contract_type": qa.PRODUCTION_CONTEXT_TYPE,
        "schema_version": qa.PRODUCTION_CONTEXT_VERSION,
        "project_id": "quality-test",
        "created_at": "2026-07-28T00:00:00Z",
        "governing_documents": governing_documents(),
        "operating_mode": mode,
        "artifact_type": artifact_type,
        "content_archetype": "educational_explainer",
        "deliverable": {
            "platform": "internal",
            "aspect_ratio": "16:9",
            "width_px": 320,
            "height_px": 180,
            "fps": 30,
            "target_duration_seconds": 1.2,
            "language": "en",
        },
        "objective": {
            "primary_goal": "verify quality gate",
            "performance_objective": "inform",
            "success_definition": "all declared checks pass or fail closed",
        },
        "audience": {
            "description": "test runner",
            "awareness_level": "solution_aware",
            "entering_state": "needs proof that the gate is strict",
            "desired_transformation": "trusts deterministic validation",
            "desired_action": "inspect the report",
        },
        "sources": [
            {
                "source_id": "fixture-source",
                "type": "video",
                "locator": "generated:testsrc2",
                "accessible": True,
                "usage_rights": "owned",
                "notes": "Synthetic FFmpeg fixture",
            },
        ],
        "accessibility": {
            "captions_required": False,
            "caption_delivery": "not_applicable",
            "audio_description_required": False,
            "safe_zone_profile": "internal-test",
            "other_needs": [],
        },
        "required_evidence": [*(requirements or []), *default_requirements],
    }
    path = root / name
    path.write_text(json.dumps(context, indent=2, sort_keys=True), encoding="utf-8")
    return path


def evidence_requirement(
    evidence_id: str,
    evidence_type: str,
    stage: str,
    source_path: Path,
    source_schema: str,
) -> dict:
    return {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "stage": stage,
        "schema_id": source_schema,
        "expected_path": str(source_path.resolve()),
        "required": True,
    }


def evidence_envelope(
    root: Path,
    requirement: dict,
    source_path: Path,
    *,
    status: str = "pass",
    artifact_sha256: str | None = None,
    timeline_sha256: str | None = None,
    payload: dict | None = None,
    extra: dict | None = None,
) -> tuple[Path, dict]:
    envelope = {
        "schema": qa.EVIDENCE_SCHEMA,
        "evidence_id": requirement["evidence_id"],
        "evidence_type": requirement["evidence_type"],
        "stage": requirement["stage"],
        "producer": "quality-test",
        "producer_version": "1.0.0",
        "status": status,
        "source_path": str(source_path.resolve()),
        "source_sha256": sha256(source_path),
        "source_schema": requirement["schema_id"],
        "payload": payload or {"summary": "validated test evidence"},
    }
    if artifact_sha256:
        envelope["artifact_sha256"] = artifact_sha256
    else:
        envelope["timeline_sha256"] = timeline_sha256 or ("b" * 64)
    envelope.update(extra or {})
    path = root / f"{requirement['evidence_id']}.envelope.json"
    path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    declaration = {
        "id": requirement["evidence_id"],
        "evidence_type": requirement["evidence_type"],
        "stage": requirement["stage"],
        "schema": qa.EVIDENCE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "required": True,
    }
    return path, declaration


def determinism_waiver() -> dict:
    return {
        "schema": qa.DETERMINISM_WAIVER_SCHEMA,
        "waiver_id": "DET-WAIVER-TEST",
        "approved_by": "test owner",
        "approved_at": "2026-07-28T00:00:00Z",
        "reason": "Synthetic unit fixture does not need a second render.",
        "scope": "test fixture only",
        "risk_acceptance": "Decoded repeatability is not asserted for this test.",
        "alternative_verification": {
            "method": "single-render decoded fingerprint",
            "evidence": "encoded_fingerprints in quality report",
        },
    }


def base_spec(
    root: Path,
    *,
    audio_required: bool = True,
    requirements: list[dict] | None = None,
    evidence: list[dict] | None = None,
    mode: str = "quick",
    artifact_type: str = "video_edit",
    features: dict | None = None,
    context_name: str = "production-context.json",
) -> dict:
    context = write_context(
        root,
        requirements=requirements,
        mode=mode,
        artifact_type=artifact_type,
        name=context_name,
    )
    declared_features = {key: False for key in qa.REQUIRED_FEATURE_FLAGS}
    declared_features.update(features or {})
    return {
        "schema": qa.SPEC_SCHEMA,
        "production_context": {
            "path": str(context.resolve()),
            "sha256": sha256(context),
        },
        "features": declared_features,
        "delivery": {
            "width": 320,
            "height": 180,
            "aspect_ratio": "16:9",
            "fps": 30,
            "fps_tolerance": 0.01,
            "duration_s": 1.2,
            "duration_tolerance_s": 0.08,
            "video_codec": "h264",
            "pixel_format": "yuv420p",
            "alpha_allowed": False,
            "rotation_metadata_allowed": False,
            "audio_required": audio_required,
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "audio_channels": 1,
            "variable_frame_rate_allowed": False,
        },
        "audio": {
            "maximum_true_peak_dbtp": -0.1,
        },
        "determinism": {
            "determinism_required": False,
            "waiver": determinism_waiver(),
        },
        "thresholds": {
            "max_unacknowledged_black_s": 0.12,
            "max_unacknowledged_freeze_s": 0.55,
            "max_unacknowledged_silence_s": 1.5,
            "maximum_uninspected_span_s": 0.5,
            "scene_detection_threshold": 0.35,
        },
        "intentional_intervals": {
            "black": [],
            "freeze": [],
            "silence": [],
        },
        "intentional_endpoints": {
            "first": False,
            "last": False,
        },
        "review_times": {
            "caption_activation": [0.3],
            "graphic_anchor": [0.7],
            "animation_phase": [],
            "transition": [],
            "maximum_density": [0.9],
        },
        "evidence": evidence or [],
    }


def passing_review(artifact: Path, spec: dict) -> dict:
    review = qa.review_template(artifact, spec, scan_scenes=False)
    review["reviewer"] = "test reviewer"
    review["reviewed_at"] = "2026-07-28T00:00:00Z"
    review["complete_playback"] = {
        "watched_from_start_to_finish": True,
        "normal_speed": True,
        "audio_enabled": True,
        "target_device": "test display",
    }
    review["content_accuracy"]["verified"] = True
    review["content_accuracy"]["sources_checked"] = ["fixture-source"]
    for item in review["checks"]:
        item.update({"status": "pass", "notes": "verified"})
    for item in review["review_points"]:
        item.update({"status": "pass", "notes": "encoded frame inspected"})
    for item in review["scene_contracts"]:
        item.update({
            "entering_state": "viewer needs context",
            "promised_change": "viewer will understand the test",
            "delivered_change": "test contract is visible",
            "proof": "encoded fixture and report",
            "exit_state": "viewer understands",
            "failure_condition": "meaning is absent or contradicted",
            "status": "pass",
            "notes": "meaning change verified",
        })
    review["universal_criteria"] = {
        key: {"score": 4.5, "notes": f"{key} verified on the encoded fixture"}
        for key in qa.UNIVERSAL_CRITERIA
    }
    review["creative_scores"] = {
        key: 4.5 for key in qa.CREATIVE_SCORE_WEIGHTS
    }
    review["notes"] = "complete"
    return review


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "ffmpeg and ffprobe are required")
class QualityEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.first = cls.root / "first.mp4"
        cls.second = cls.root / "second.mp4"
        cls.different = cls.root / "different.mp4"
        cls.silent = cls.root / "silent.mp4"
        synthetic_video(cls.first)
        synthetic_video(cls.second)
        synthetic_video(cls.different, color_variant=True)
        synthetic_video(cls.silent, with_audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fresh_root(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(exist_ok=True)
        return path

    def test_fraction_parser(self):
        self.assertAlmostEqual(qa._fraction("30000/1001"), 29.97002997)
        self.assertEqual(qa._fraction("30/1"), 30.0)
        self.assertIsNone(qa._fraction("0/0"))

    def test_interval_acknowledgement_requires_full_coverage(self):
        interval = {"start": 2.0, "end": 3.0, "duration": 1.0}
        self.assertTrue(qa._interval_acknowledged(
            interval, [{"start": 1.95, "end": 3.05}]
        ))
        self.assertFalse(qa._interval_acknowledged(
            interval, [{"start": 2.2, "end": 3.0}]
        ))

    def test_interval_parser_handles_freezedetect_token_order(self):
        output = """
lavfi.freezedetect.freeze_start: 2.0
lavfi.freezedetect.freeze_duration: 0.75
lavfi.freezedetect.freeze_end: 2.75
lavfi.freezedetect.freeze_start: 4.0
"""
        self.assertEqual(
            qa._parse_intervals(output, "freeze"),
            [
                {"start": 2.0, "end": 2.75, "duration": 0.75},
                {"start": 4.0, "end": None, "duration": None},
            ],
        )

    def test_repeated_render_decoded_fingerprints_match(self):
        root = self.fresh_root("repeat-match")
        spec = base_spec(root)
        spec["determinism"] = {"determinism_required": True, "waiver": None}
        report = qa.run_quality_audit(
            self.first, spec=spec, compare_to=self.second, scan_scenes=False,
        )
        self.assertTrue(report["automated_gate_passed"], report["issues"])
        self.assertEqual(report["repeatability"]["status"], "pass")
        self.assertTrue(report["repeatability"]["video_match"])
        self.assertTrue(report["repeatability"]["audio_match"])
        self.assertFalse(report["ready"], "human review must remain required")

    def test_different_repeat_render_is_blocker_even_when_waived(self):
        root = self.fresh_root("repeat-different")
        report = qa.run_quality_audit(
            self.first,
            spec=base_spec(root),
            compare_to=self.different,
            scan_scenes=False,
        )
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("repeat_render_mismatch", codes)
        self.assertFalse(report["automated_gate_passed"])

    def test_missing_repeat_render_is_blocker_when_required(self):
        root = self.fresh_root("repeat-required")
        spec = base_spec(root)
        spec["determinism"] = {"determinism_required": True, "waiver": None}
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "repeat_render_not_supplied",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_missing_determinism_waiver_blocks(self):
        root = self.fresh_root("waiver-missing")
        spec = base_spec(root)
        spec["determinism"] = {"determinism_required": False, "waiver": None}
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "determinism_waiver_missing",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_delivery_mismatch_is_blocker(self):
        root = self.fresh_root("delivery")
        spec = base_spec(root)
        spec["delivery"].update({"width": 1080, "height": 1920, "aspect_ratio": "9:16"})
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("width_mismatch", codes)
        self.assertIn("height_mismatch", codes)
        self.assertIn("aspect_ratio_mismatch", codes)
        self.assertFalse(report["automated_gate_passed"])

    def test_required_audio_missing_is_blocker(self):
        root = self.fresh_root("audio-required")
        report = qa.run_quality_audit(
            self.silent, spec=base_spec(root, audio_required=True), scan_scenes=False,
        )
        self.assertIn("audio_stream_missing", {item["code"] for item in report["issues"]})
        self.assertFalse(report["automated_gate_passed"])

    def test_optional_audio_allows_silent_artifact(self):
        root = self.fresh_root("audio-optional")
        report = qa.run_quality_audit(
            self.silent, spec=base_spec(root, audio_required=False), scan_scenes=False,
        )
        self.assertNotIn("audio_stream_missing", {item["code"] for item in report["issues"]})
        self.assertTrue(report["automated_gate_passed"], report["issues"])

    def test_production_context_fingerprint_mismatch_blocks(self):
        root = self.fresh_root("context-hash")
        spec = base_spec(root)
        context = Path(spec["production_context"]["path"])
        context.write_text(context.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "production_context_fingerprint_mismatch",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_unnamed_source_blocks(self):
        root = self.fresh_root("source-invalid")
        spec = base_spec(root)
        context_path = Path(spec["production_context"]["path"])
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["sources"] = [{"source_id": "fixture-source"}]
        context_path.write_text(json.dumps(context), encoding="utf-8")
        spec["production_context"]["sha256"] = sha256(context_path)
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn("named_source_invalid", {item["code"] for item in report["issues"]})
        self.assertFalse(report["automated_gate_passed"])

    def test_empty_raw_or_unknown_evidence_is_rejected(self):
        root = self.fresh_root("evidence-empty")
        raw = root / "empty.json"
        raw.write_text("{}", encoding="utf-8")
        spec = base_spec(root)
        report = qa.run_quality_audit(
            self.first, spec=spec, evidence_paths=[raw], scan_scenes=False,
        )
        self.assertIn(
            "undeclared_evidence_rejected",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_failed_strict_evidence_envelope_blocks(self):
        root = self.fresh_root("evidence-fail")
        source = root / "forced-alignment.json"
        source.write_text(json.dumps({"schema": "arete-forced-alignment/v1", "status": "fail"}))
        req = evidence_requirement(
            "forced-alignment", "forced_alignment", "before-final-render",
            source, "arete-forced-alignment/v1",
        )
        _, declaration = evidence_envelope(root, req, source, status="fail")
        spec = base_spec(
            root,
            requirements=[req],
            evidence=[declaration],
        )
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "upstream_quality_gate_failed",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_evidence_source_fingerprint_mismatch_blocks(self):
        root = self.fresh_root("evidence-source-hash")
        source = root / "forced-alignment.json"
        source.write_text(json.dumps({"schema": "arete-forced-alignment/v1", "status": "pass"}))
        req = evidence_requirement(
            "forced-alignment", "forced_alignment", "before-final-render",
            source, "arete-forced-alignment/v1",
        )
        envelope_path, declaration = evidence_envelope(root, req, source)
        source.write_text(json.dumps({"schema": "arete-forced-alignment/v1", "status": "changed"}))
        spec = base_spec(root, requirements=[req], evidence=[declaration])
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "evidence_source_fingerprint_mismatch",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])
        self.assertTrue(envelope_path.exists())

    def test_feature_required_evidence_cannot_be_omitted_from_context(self):
        root = self.fresh_root("feature-evidence")
        spec = base_spec(root, features={"graphics": True})
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "context_feature_evidence_missing",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_treatment_evidence_must_match_selected_taste(self):
        root = self.fresh_root("treatment-binding")
        taste_source = root / "taste-selection.json"
        taste_source.write_text(json.dumps({
            "contract_type": "taste-selection",
            "schema_version": "1.0.0",
            "selection": {"selected_option_id": "calm-option"},
        }), encoding="utf-8")
        taste_req = evidence_requirement(
            "taste-selection", "taste_selection", "before-execution",
            taste_source, "https://arete.local/editing-os/contracts/taste-selection/v1",
        )
        _, taste_declaration = evidence_envelope(root, taste_req, taste_source)

        graphics_source = root / "graphics-qa.json"
        graphics_source.write_text(json.dumps({"automatedChecksPassed": True}))
        graphics_req = evidence_requirement(
            "graphics-qa", "graphics_qa", "before-final-render",
            graphics_source, "arete-graphics-qa/v1",
        )
        _, graphics_declaration = evidence_envelope(
            root,
            graphics_req,
            graphics_source,
            extra={
                "taste_selection_sha256": sha256(taste_source),
                "selected_option_id": "wrong-option",
                "treatment_sha256": "c" * 64,
            },
        )
        spec = base_spec(
            root,
            requirements=[taste_req, graphics_req],
            evidence=[taste_declaration, graphics_declaration],
            features={"graphics": True},
        )
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "treatment_taste_selection_mismatch",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_timeline_evidence_must_match_approved_edl(self):
        root = self.fresh_root("approved-timeline-binding")
        approved_edl_hash = "d" * 64
        context_placeholder = "e" * 64
        edl_source = root / "edl-approval.json"
        edl_source.write_text(json.dumps({
            "status": "approved",
            "production_context": {"path": "placeholder", "sha256": context_placeholder},
            "edl": {"path": "approved.edl.json", "sha256": approved_edl_hash},
            "approval": {
                "approved_edl_sha256": approved_edl_hash,
                "timeline_fingerprint": approved_edl_hash,
            },
        }), encoding="utf-8")
        edl_req = evidence_requirement(
            "edl-approval", "edl_approval", "before-execution",
            edl_source, "https://arete.local/editing-os/contracts/edl-approval/v1",
        )
        editorial_source = root / "editorial-intent.json"
        editorial_source.write_text(json.dumps({
            "contract_type": "editorial-intent",
            "schema_version": "1.0.0",
            "scenes": [{"scene_id": "scene-1"}],
        }), encoding="utf-8")
        editorial_req = evidence_requirement(
            "editorial-intent", "editorial_intent", "before-execution",
            editorial_source,
            "https://arete.local/editing-os/contracts/editorial-intent/v1",
        )
        # Build context first, then bind the approval source back to its exact hash.
        spec = base_spec(
            root,
            requirements=[edl_req, editorial_req],
            features={"timeline_edited": False},
        )
        context_hash = spec["production_context"]["sha256"]
        edl_payload = json.loads(edl_source.read_text(encoding="utf-8"))
        edl_payload["production_context"]["sha256"] = context_hash
        edl_source.write_text(json.dumps(edl_payload), encoding="utf-8")
        _, edl_declaration = evidence_envelope(
            root, edl_req, edl_source, timeline_sha256=approved_edl_hash,
        )
        _, editorial_declaration = evidence_envelope(
            root, editorial_req, editorial_source, timeline_sha256="c" * 64,
        )
        spec["evidence"] = [edl_declaration, editorial_declaration]
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "evidence_approved_timeline_mismatch",
            {item["code"] for item in report["issues"]},
        )
        self.assertIn(
            "feature_evidence_contradiction",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_render_log_requires_strict_envelope_and_scans_source(self):
        root = self.fresh_root("render-log")
        source = root / "render.log"
        source.write_text("console: media loaded\nERROR missing texture\n", encoding="utf-8")
        req = evidence_requirement(
            "render-log", "render_log", "before-final-render",
            source, "text/render-log-v1",
        )
        _, declaration = evidence_envelope(root, req, source)
        spec = base_spec(
            root,
            requirements=[req],
            evidence=[declaration],
            features={"browser_rendered": True},
        )
        report = qa.run_quality_audit(self.first, spec=spec, scan_scenes=False)
        self.assertIn(
            "render_or_media_error_logged",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["automated_gate_passed"])

    def test_review_is_bound_to_exact_artifact(self):
        root = self.fresh_root("review-hash")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["artifact_sha256"] = "0" * 64
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn(
            "human_review_artifact_mismatch",
            {item["code"] for item in report["issues"]},
        )
        self.assertTrue(report["automated_gate_passed"])
        self.assertFalse(report["ready"])

    def test_complete_review_can_make_artifact_ready_with_waiver(self):
        root = self.fresh_root("ready")
        spec = base_spec(root)
        report = qa.run_quality_audit(
            self.first,
            spec=spec,
            review=passing_review(self.first, spec),
            scan_scenes=False,
        )
        self.assertTrue(report["automated_gate_passed"], report["issues"])
        self.assertEqual(report["repeatability"]["status"], "waived")
        self.assertEqual(report["human_review"]["status"], "pass")
        self.assertEqual(report["human_review"]["creative_score"]["total"], 90.0)
        self.assertEqual(report["human_review"]["universal_criteria"]["status"], "pass")
        self.assertTrue(report["ready"], report["issues"])

    def test_missing_generated_review_point_blocks_ready(self):
        root = self.fresh_root("review-point")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["review_points"] = review["review_points"][:-1]
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn("review_point_missing", {item["code"] for item in report["issues"]})
        self.assertFalse(report["ready"])

    def test_universal_criterion_floor_is_independent_of_craft_score(self):
        root = self.fresh_root("universal-score")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["universal_criteria"]["emotion"]["score"] = 2
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn(
            "universal_criterion_below_floor",
            {item["code"] for item in report["issues"]},
        )
        self.assertEqual(report["human_review"]["creative_score"]["status"], "pass")
        self.assertFalse(report["ready"])

    def test_failed_creative_category_cannot_hide_behind_total(self):
        root = self.fresh_root("craft-score")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["creative_scores"]["typography"] = 2
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn(
            "creative_category_below_floor",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["ready"])

    def test_missing_review_check_is_major(self):
        root = self.fresh_root("review-check")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["checks"] = review["checks"][:-1]
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertEqual(
            len([item for item in report["issues"]
                 if item["code"] == "human_review_check_missing"]),
            1,
        )
        self.assertFalse(report["ready"])

    def test_standard_video_requires_editorial_intent_and_scene_review(self):
        root = self.fresh_root("scene-contract")
        source = root / "editorial-intent.json"
        source.write_text(json.dumps({
            "contract_type": "editorial-intent",
            "schema_version": "1.0.0",
            "scene_contracts": [{"scene_id": "scene-hook"}],
        }), encoding="utf-8")
        req = evidence_requirement(
            "editorial-intent", "editorial_intent", "before-execution",
            source, "editorial-intent/1.0.0",
        )
        _, declaration = evidence_envelope(root, req, source)
        spec = base_spec(
            root,
            requirements=[req],
            evidence=[declaration],
            mode="standard",
            artifact_type="video_edit",
        )
        review = passing_review(self.first, spec)
        self.assertEqual(review["scene_contracts"][0]["scene_id"], "scene-hook")
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertTrue(report["ready"], report["issues"])
        review["scene_contracts"][0]["proof"] = ""
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn(
            "scene_contract_review_failed",
            {item["code"] for item in report["issues"]},
        )
        self.assertFalse(report["ready"])

    def test_content_review_must_name_every_context_source(self):
        root = self.fresh_root("content-source")
        spec = base_spec(root)
        review = passing_review(self.first, spec)
        review["content_accuracy"]["sources_checked"] = []
        report = qa.run_quality_audit(
            self.first, spec=spec, review=review, scan_scenes=False,
        )
        self.assertIn("content_accuracy_unverified", {item["code"] for item in report["issues"]})
        self.assertFalse(report["ready"])

    def test_report_is_byte_stable_for_same_inputs(self):
        root = self.fresh_root("stable")
        spec = base_spec(root)
        first = qa.run_quality_audit(
            self.first, spec=spec, compare_to=self.second, scan_scenes=False,
        )
        second = qa.run_quality_audit(
            self.first, spec=spec, compare_to=self.second, scan_scenes=False,
        )
        self.assertEqual(qa._dump(first), qa._dump(second))

    def test_review_template_contains_every_required_check_and_point(self):
        root = self.fresh_root("template")
        spec = base_spec(root)
        template = qa.review_template(self.first, spec, scan_scenes=False)
        self.assertEqual(template["schema"], qa.REVIEW_SCHEMA)
        self.assertEqual(
            {item["id"] for item in template["checks"]},
            set(qa.REQUIRED_REVIEW_CHECKS),
        )
        self.assertTrue(template["review_points"])
        self.assertEqual(
            set(template["creative_scores"]),
            set(qa.CREATIVE_SCORE_WEIGHTS),
        )
        self.assertEqual(
            set(template["universal_criteria"]),
            set(qa.UNIVERSAL_CRITERIA),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

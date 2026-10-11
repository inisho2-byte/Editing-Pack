from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1] / "Contracts"
EXAMPLES = CONTRACTS / "examples"

SPEC = importlib.util.spec_from_file_location("arete_orchestration_adapter", HERE / "adapter.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


SCHEMA_IDS = {
    "editorial_intent": "https://arete.local/editing-os/contracts/editorial-intent/v1",
    "taste_selection": "https://arete.local/editing-os/contracts/taste-selection/v1",
    "edl_approval": "https://arete.local/editing-os/contracts/edl-approval/v1",
    "forced_alignment": "arete-forced-alignment/v1",
    "caption_qa": "arete-caption-qa/v1",
    "graphics_qa": "arete-graphics-qa/v1",
    "audio_plan": "https://arete.local/editing-os/contracts/audio-plan/v1",
    "audio_qa": "arete-audio-qa/v1",
    "render_log": "arete-render-log/v1",
}


def read_example(kind: str) -> dict:
    filename = f"{kind}.v1.example.json"
    return json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def sha(path: Path) -> str:
    return adapter._sha256_file(path)


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        project_id: str,
        artifact_type: str,
        archetype: str,
        captions_required: bool,
    ) -> None:
        self.root = root
        self.project_id = project_id
        self.editing_os = root / "Editing_OS"
        self.contract_dir = root / "contracts"
        self.evidence_dir = root / "evidence"
        self.source_dir = root / "sources"
        self.context_path = self.contract_dir / "production-context.json"
        self.contracts: dict[str, Path] = {}
        self.envelopes: dict[str, Path] = {}
        self.requirements: list[dict] = []
        self._make_authorities()
        self.context = self._context(
            artifact_type=artifact_type,
            archetype=archetype,
            captions_required=captions_required,
        )

    def _make_authorities(self) -> None:
        for index, relative in enumerate(adapter.GOVERNING_DOCUMENTS.values(), start=1):
            path = self.editing_os / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"governing authority {index}\n", encoding="utf-8")

    def _context(
        self,
        *,
        artifact_type: str,
        archetype: str,
        captions_required: bool,
    ) -> dict:
        governing = []
        for role, relative in adapter.GOVERNING_DOCUMENTS.items():
            path = self.editing_os / relative
            governing.append(
                {"role": role, "path": relative, "sha256": sha(path)}
            )
        return {
            "contract_type": "production-context",
            "schema_version": "1.0.0",
            "project_id": self.project_id,
            "created_at": "2026-07-28T15:00:00Z",
            "governing_documents": governing,
            "operating_mode": "standard",
            "artifact_type": artifact_type,
            "content_archetype": archetype,
            "deliverable": {
                "platform": "instagram_reels",
                "aspect_ratio": "9:16",
                "width_px": 1080,
                "height_px": 1920,
                "fps": 30,
                "target_duration_seconds": 35,
                "language": "en-US",
                "deadline": None,
            },
            "objective": {
                "primary_goal": "Prove the owned orchestration gate.",
                "performance_objective": "inform",
                "success_definition": "The intended viewer can explain the workflow.",
            },
            "audience": {
                "description": "Creators testing the Editing OS.",
                "awareness_level": "problem_aware",
                "entering_state": "Unsure which clock controls production.",
                "desired_transformation": "Understands the post-cut source of truth.",
                "desired_action": "Use the approved production path.",
            },
            "sources": [
                {
                    "source_id": "source-main",
                    "type": "video",
                    "locator": "sources/main.mp4",
                    "accessible": True,
                    "usage_rights": "owned",
                    "notes": "Synthetic contract fixture.",
                }
            ],
            "accessibility": {
                "captions_required": captions_required,
                "caption_delivery": "burned_in" if captions_required else "not_applicable",
                "audio_description_required": False,
                "safe_zone_profile": "instagram-reels-2026-07",
                "other_needs": [],
            },
            "required_evidence": self.requirements,
        }

    def add_contract(self, kind: str, payload: dict | None = None) -> Path:
        payload = copy.deepcopy(payload or read_example(kind))
        payload["project_id"] = self.project_id
        path = write_json(self.contract_dir / f"{kind}.json", payload)
        self.contracts[kind] = path
        return path

    def add_legacy_evidence(
        self,
        evidence_type: str,
        payload: dict,
        *,
        stage: str,
        evidence_id: str | None = None,
        subject_hash: str = "a" * 64,
    ) -> tuple[Path, Path]:
        evidence_id = evidence_id or f"{evidence_type}-main"
        source = write_json(
            self.source_dir / f"{evidence_type}.json",
            payload,
        )
        requirement = {
            "evidence_id": evidence_id,
            "evidence_type": evidence_type,
            "stage": stage,
            "schema_id": SCHEMA_IDS[evidence_type],
            "expected_path": str(source.resolve()),
            "required": True,
        }
        self.requirements.append(requirement)
        treatment_kwargs = {}
        if evidence_type in adapter.TREATMENT_SENSITIVE_EVIDENCE_TYPES:
            taste_path = self.contracts["taste-selection"]
            taste_payload = json.loads(taste_path.read_text(encoding="utf-8"))
            selected = next(
                item for item in taste_payload["options"]
                if item["option_id"] == taste_payload["selection"]["selected_option_id"]
            )
            if "treatment_tokens" in selected:
                treatment_hash = adapter._canonical_sha256(
                    selected["treatment_tokens"]
                )
            else:
                treatment_hash = selected["treatment_artifact"]["sha256"]
            treatment_kwargs = {
                "taste_selection_sha256": sha(taste_path),
                "selected_option_id": selected["option_id"],
                "treatment_sha256": treatment_hash,
            }
        envelope = adapter.wrap_evidence(
            source_path=source,
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            stage=stage,
            schema_id=SCHEMA_IDS[evidence_type],
            producer_name=f"fixture-{evidence_type}",
            producer_version="1.0.0",
            passed=True,
            timeline_sha256=subject_hash,
            **treatment_kwargs,
        )
        envelope_path = write_json(
            self.evidence_dir / f"{evidence_type}.envelope.json",
            envelope,
        )
        self.envelopes[evidence_type] = envelope_path
        return source, envelope_path

    def add_contract_evidence(
        self,
        kind: str,
        *,
        stage: str,
        subject_hash: str = "a" * 64,
    ) -> Path:
        evidence_type = kind.replace("-", "_")
        path = self.contracts[kind]
        requirement = {
            "evidence_id": f"{evidence_type}-main",
            "evidence_type": evidence_type,
            "stage": stage,
            "schema_id": SCHEMA_IDS[evidence_type],
            "expected_path": str(path.resolve()),
            "required": True,
        }
        self.requirements.append(requirement)
        envelope = adapter.wrap_evidence(
            source_path=path,
            evidence_id=requirement["evidence_id"],
            evidence_type=evidence_type,
            stage=stage,
            schema_id=requirement["schema_id"],
            producer_name="owned-contracts",
            producer_version="1.0.0",
            passed=True,
            timeline_sha256=subject_hash,
        )
        envelope_path = write_json(
            self.evidence_dir / f"{evidence_type}.envelope.json",
            envelope,
        )
        self.envelopes[evidence_type] = envelope_path
        return envelope_path

    def rebind_envelope(self, evidence_type: str, timeline_hash: str) -> None:
        path = self.envelopes[evidence_type]
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["timeline_sha256"] = timeline_hash
        write_json(path, envelope)

    def finalize_context(self) -> Path:
        # The context retains the list object assigned at construction.
        write_json(self.context_path, self.context)
        context_hash = sha(self.context_path)
        for kind, path in self.contracts.items():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "production_context" in payload:
                payload["production_context"] = {
                    "path": str(self.context_path.resolve()),
                    "sha256": context_hash,
                }
            if kind == "taste-selection":
                payload["taste_profile_sha256"] = sha(
                    self.editing_os / adapter.GOVERNING_DOCUMENTS["taste_profile"]
                )
            write_json(path, payload)

        taste_path = self.contracts.get("taste-selection")
        taste_payload = (
            json.loads(taste_path.read_text(encoding="utf-8"))
            if taste_path else None
        )
        selected = None
        if taste_payload:
            selected = next(
                item for item in taste_payload["options"]
                if item["option_id"] == taste_payload["selection"]["selected_option_id"]
            )
        for evidence_type, envelope_path in self.envelopes.items():
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            source_path = Path(envelope["source_path"])
            envelope["source_sha256"] = sha(source_path)
            try:
                envelope["payload"] = json.loads(source_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
            if (
                evidence_type in adapter.TREATMENT_SENSITIVE_EVIDENCE_TYPES
                and taste_path is not None
                and selected is not None
            ):
                envelope["taste_selection_sha256"] = sha(taste_path)
                envelope["selected_option_id"] = selected["option_id"]
                envelope["treatment_sha256"] = (
                    adapter._canonical_sha256(selected["treatment_tokens"])
                    if "treatment_tokens" in selected
                    else selected["treatment_artifact"]["sha256"]
                )
            write_json(envelope_path, envelope)
        return self.context_path

    def contract_args(self, *kinds: str) -> list[tuple[str, Path]]:
        return [(kind, self.contracts[kind]) for kind in kinds]


class OrchestrationAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _taste_and_editorial(self, fixture: Fixture) -> tuple[Path, Path]:
        taste = read_example("taste-selection")
        editorial = read_example("editorial-intent")
        taste["project_id"] = fixture.project_id
        editorial["project_id"] = fixture.project_id
        taste_path = fixture.add_contract("taste-selection", taste)
        editorial_path = fixture.add_contract("editorial-intent", editorial)
        fixture.add_contract_evidence("taste-selection", stage="before-execution")
        fixture.add_contract_evidence("editorial-intent", stage="before-execution")
        return taste_path, editorial_path

    def test_vertical_talking_head_caption_chain_approval_and_publish(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="vertical-talk-001",
            artifact_type="video_edit",
            archetype="educational_explainer",
            captions_required=True,
        )
        taste_path, _ = self._taste_and_editorial(fixture)
        audio_plan = read_example("audio-plan")
        audio_plan["project_id"] = fixture.project_id
        fixture.add_contract("audio-plan", audio_plan)
        fixture.add_contract_evidence("audio-plan", stage="before-execution")

        timeline_path = write_json(
            self.root / "timing" / "timeline-map.json",
            {
                "timeline_map": [
                    {
                        "range_id": "range-001",
                        "source_start": 2.0,
                        "source_end": 3.0,
                        "output_start": 0.0,
                        "output_end": 1.0,
                    }
                ]
            },
        )
        words_path = write_json(
            self.root / "timing" / "retimed-words.json",
            {
                "retimed_words": [
                    {"text": "One", "start": 0.0, "end": 0.3},
                    {"text": "clock.", "start": 0.35, "end": 0.8},
                ]
            },
        )
        timeline = json.loads(timeline_path.read_text())["timeline_map"]
        words = json.loads(words_path.read_text())["retimed_words"]
        fingerprint = adapter.caption_timeline_fingerprint(timeline, words)
        fixture.rebind_envelope("taste_selection", fingerprint)
        fixture.rebind_envelope("editorial_intent", fingerprint)
        fixture.rebind_envelope("audio_plan", fingerprint)

        _, forced_envelope_path = fixture.add_legacy_evidence(
            "forced_alignment",
            {
                "schema": "arete-forced-alignment/v1",
                "status": "pass",
                "provenance": {"method": "whisperx", "forced": True},
                "words": [{"text": "One", "start": 2.0, "end": 2.3}],
            },
            stage="before-final-render",
            subject_hash=fingerprint,
        )
        forced_envelope_hash = sha(forced_envelope_path)
        _, caption_envelope_path = fixture.add_legacy_evidence(
            "caption_qa",
            {
                "schema": "arete-caption-qa/v1",
                "status": "pass",
                "taste_binding": {
                    "selected_option_id": "option-calm-tech",
                    "taste_selection_sha256": sha(taste_path),
                },
                "post_cut_timing": {
                    "source_of_truth": "post-cut-retimed-words",
                    "forced_alignment_sha256": forced_envelope_hash,
                    "timeline_map_sha256": sha(timeline_path),
                    "retimed_words_sha256": sha(words_path),
                    "timeline_fingerprint": fingerprint,
                },
            },
            stage="before-final-render",
            subject_hash=fingerprint,
        )

        fixture.finalize_context()
        edl_path = write_json(
            self.root / "edit" / "approved-edl.json",
            {"ranges": [], "grade": "none"},
        )
        preview_path = self.root / "previews" / "approved.mp4"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_bytes(b"synthetic preview bytes")
        approval = read_example("edl-approval")
        approval["project_id"] = fixture.project_id
        approval["production_context"] = {
            "path": str(fixture.context_path),
            "sha256": sha(fixture.context_path),
        }
        approval["edl"] = {"path": str(edl_path), "sha256": sha(edl_path)}
        approval["preview"] = {"path": str(preview_path), "sha256": sha(preview_path)}
        approval["timeline_map"] = {
            "path": str(timeline_path),
            "sha256": sha(timeline_path),
        }
        approval["retimed_words"] = {
            "path": str(words_path),
            "sha256": sha(words_path),
        }
        approval["approval"]["approved_edl_sha256"] = sha(edl_path)
        approval["approval"]["timeline_fingerprint"] = fingerprint
        approval["approval"]["selected_taste_selection_sha256"] = sha(taste_path)
        approval_path = fixture.add_contract("edl-approval", approval)
        fixture.add_contract_evidence(
            "edl-approval",
            stage="before-final-render",
            subject_hash=fingerprint,
        )
        # The new requirement must be persisted after the first context write.
        fixture.finalize_context()
        # Approval binds to the final context bytes, so refresh it and its envelope.
        approval["production_context"]["sha256"] = sha(fixture.context_path)
        approval["approval"]["selected_taste_selection_sha256"] = sha(taste_path)
        approval_path = write_json(approval_path, approval)
        fixture.envelopes["edl_approval"] = write_json(
            fixture.envelopes["edl_approval"],
            adapter.wrap_evidence(
                source_path=approval_path,
                evidence_id="edl_approval-main",
                evidence_type="edl_approval",
                stage="before-final-render",
                schema_id=SCHEMA_IDS["edl_approval"],
                producer_name="owned-contracts",
                producer_version="1.0.0",
                passed=True,
                timeline_sha256=fingerprint,
            ),
        )

        preflight = adapter.run_preflight(
            fixture.context_path,
            stage="before-final-render",
            contracts=fixture.contract_args(
                "taste-selection", "editorial-intent", "audio-plan", "edl-approval"
            ),
            evidence_paths=fixture.envelopes.values(),
            editing_os_root=fixture.editing_os,
        )
        self.assertEqual(preflight["status"], "pass")
        self.assertFalse(preflight["publishable"])

        approval_report = adapter.check_edl_approval(
            approval_path,
            edl_path=edl_path,
            taste_selection_path=taste_path,
        )
        self.assertEqual(approval_report["status"], "pass")

        edl_authorization_path = write_json(
            self.root / "edit" / "edl-render-authorization.json",
            approval_report,
        )
        caption_authorization = adapter.authorize_caption_render(
            edl_authorization_path=edl_authorization_path,
            forced_alignment_path=forced_envelope_path,
            timeline_map_path=timeline_path,
            retimed_words_path=words_path,
            taste_selection_path=taste_path,
        )
        self.assertEqual(
            caption_authorization["timeline_fingerprint"],
            fingerprint,
        )

        engine_stub = self.root / "engine-stub.py"
        engine_stub.write_text("# owned adapter test stub\n", encoding="utf-8")
        commands: list[list[str]] = []

        def fake_runner(command, check):
            self.assertTrue(check)
            commands.append(list(command))
            if "--out" in command:
                target = Path(command[command.index("--out") + 1])
            else:
                target = Path(command[-1])
            target.write_bytes(b"encoded by authorized test path")

        authorized_output = self.root / "delivery" / "authorized.mp4"
        render_manifest = adapter.apply_approved_edl(
            edl_authorization_path,
            authorized_output,
            engine_path=engine_stub,
            runner=fake_runner,
        )
        self.assertEqual(render_manifest["status"], "pass")
        self.assertEqual(len(commands), 2)
        self.assertTrue(authorized_output.is_file())

        caption_report = adapter.check_caption_timing(
            forced_alignment_path=forced_envelope_path,
            caption_evidence_path=caption_envelope_path,
            timeline_map_path=timeline_path,
            retimed_words_path=words_path,
        )
        self.assertEqual(caption_report["timeline_fingerprint"], fingerprint)

        artifact = self.root / "delivery" / "final.mp4"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"synthetic encoded artifact fixture")
        quality_report = write_json(
            self.root / "quality" / "report.json",
            {
                "schema": "arete-video-quality-report/v2",
                "artifact": {"path": str(artifact.resolve()), "sha256": sha(artifact)},
                "automated_gate_passed": True,
                "human_review": {"status": "pass"},
                "ready": True,
            },
        )
        publication = adapter.assert_publishable(artifact, quality_report)
        self.assertTrue(publication["publishable"])

    def test_interview_requires_diarization_audio_plan_and_audio_evidence(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="interview-001",
            artifact_type="video_edit",
            archetype="podcast_interview",
            captions_required=True,
        )
        self._taste_and_editorial(fixture)
        # These final-render requirements are planned now but not due at the
        # before-execution preflight.
        fixture.add_contract("edl-approval")
        fixture.add_contract_evidence("edl-approval", stage="before-final-render")
        fixture.add_legacy_evidence(
            "forced_alignment",
            {
                "schema": "arete-forced-alignment/v1",
                "status": "pass",
                "provenance": {"method": "whisperx", "forced": True},
            },
            stage="before-final-render",
        )
        fixture.add_legacy_evidence(
            "caption_qa",
            {"schema": "arete-caption-qa/v1", "status": "pass"},
            stage="before-final-render",
        )
        audio_plan = read_example("audio-plan")
        audio_plan["project_id"] = fixture.project_id
        audio_plan["diarization"] = {
            "required": True,
            "rationale": "Two visible speakers alternate throughout the interview.",
            "speakers": [
                {
                    "speaker_id": "speaker-host",
                    "label": "Host",
                    "source_evidence": "Host is visible on the left channel.",
                },
                {
                    "speaker_id": "speaker-guest",
                    "label": "Guest",
                    "source_evidence": "Guest is visible on the right channel.",
                },
            ],
        }
        fixture.add_contract("audio-plan", audio_plan)
        fixture.add_contract_evidence("audio-plan", stage="before-execution")
        fixture.add_legacy_evidence(
            "audio_qa",
            {"schema": "arete-audio-qa/v1", "status": "pass", "dialogue": "clear"},
            stage="before-execution",
        )
        fixture.finalize_context()

        report = adapter.run_preflight(
            fixture.context_path,
            stage="before-execution",
            contracts=fixture.contract_args(
                "taste-selection", "editorial-intent", "audio-plan"
            ),
            evidence_paths=[
                fixture.envelopes["taste_selection"],
                fixture.envelopes["editorial_intent"],
                fixture.envelopes["audio_plan"],
                fixture.envelopes["audio_qa"],
            ],
            editing_os_root=fixture.editing_os,
        )
        self.assertEqual(report["status"], "pass")
        audio_payload = json.loads(fixture.contracts["audio-plan"].read_text())
        self.assertTrue(audio_payload["diarization"]["required"])
        self.assertEqual(len(audio_payload["diarization"]["speakers"]), 2)

    def test_motion_graphics_without_dialogue_does_not_require_caption_evidence(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="motion-explainer-001",
            artifact_type="motion_graphic",
            archetype="educational_explainer",
            captions_required=False,
        )
        self._taste_and_editorial(fixture)
        taste_path = fixture.contracts["taste-selection"]
        fixture.add_legacy_evidence(
            "graphics_qa",
            {
                "schema": "arete-graphics-qa/v1",
                "status": "pass",
                "layout": "verified",
                "taste_binding": {
                    "selected_option_id": "option-calm-tech",
                    "taste_selection_sha256": sha(taste_path),
                },
            },
            stage="before-execution",
        )
        fixture.finalize_context()
        report = adapter.run_preflight(
            fixture.context_path,
            stage="before-execution",
            contracts=fixture.contract_args("taste-selection", "editorial-intent"),
            evidence_paths=fixture.envelopes.values(),
            editing_os_root=fixture.editing_os,
        )
        self.assertEqual(report["status"], "pass")
        evidence_types = {
            item["evidence_type"] for item in report["required_evidence"]
        }
        self.assertEqual(
            evidence_types,
            {"taste_selection", "editorial_intent", "graphics_qa"},
        )
        self.assertNotIn("forced_alignment", evidence_types)
        self.assertNotIn("caption_qa", evidence_types)

    def test_video_edit_without_taste_selection_fails(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="no-taste-001",
            artifact_type="video_edit",
            archetype="educational_explainer",
            captions_required=False,
        )
        fixture.add_contract("editorial-intent")
        # Declarations satisfy feature planning so the failure is specifically
        # the missing validated taste-selection contract.
        audio_source = write_json(
            fixture.source_dir / "audio-plan.json",
            {"status": "pass"},
        )
        fixture.requirements.append(
            {
                "evidence_id": "audio_plan-main",
                "evidence_type": "audio_plan",
                "stage": "before-execution",
                "schema_id": SCHEMA_IDS["audio_plan"],
                "expected_path": str(audio_source),
                "required": True,
            }
        )
        for kind in ("editorial-intent", "taste-selection", "edl-approval"):
            if kind == "editorial-intent":
                fixture.add_contract_evidence(kind, stage="before-execution")
            else:
                source = write_json(
                    fixture.source_dir / f"{kind}.json",
                    {"status": "pass"},
                )
                fixture.requirements.append(
                    {
                        "evidence_id": f"{kind.replace('-', '_')}-main",
                        "evidence_type": kind.replace("-", "_"),
                        "stage": "before-final-render",
                        "schema_id": SCHEMA_IDS[kind.replace("-", "_")],
                        "expected_path": str(source),
                        "required": True,
                    }
                )
        fixture.finalize_context()
        with self.assertRaisesRegex(adapter.AdapterError, "taste-selection"):
            adapter.run_preflight(
                fixture.context_path,
                stage="before-execution",
                contracts=fixture.contract_args("editorial-intent"),
                evidence_paths=[fixture.envelopes["editorial_intent"]],
                editing_os_root=fixture.editing_os,
            )

    def test_implicit_subtle_grade_is_rejected(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="subtle-default-001",
            artifact_type="motion_graphic",
            archetype="educational_explainer",
            captions_required=False,
        )
        taste = read_example("taste-selection")
        taste["project_id"] = fixture.project_id
        selected = next(
            item for item in taste["options"] if item["status"] == "selected"
        )
        selected["treatment_tokens"]["color_grade"]["look_description"] = "subtle"
        fixture.add_contract("taste-selection", taste)
        fixture.add_contract("editorial-intent")
        fixture.add_contract_evidence("taste-selection", stage="before-execution")
        fixture.add_contract_evidence("editorial-intent", stage="before-execution")
        fixture.add_legacy_evidence(
            "graphics_qa",
            {
                "schema": "arete-graphics-qa/v1",
                "status": "pass",
                "taste_binding": {
                    "selected_option_id": "option-calm-tech",
                    "taste_selection_sha256": sha(fixture.contracts["taste-selection"]),
                },
            },
            stage="before-execution",
        )
        fixture.finalize_context()
        with self.assertRaisesRegex(adapter.AdapterError, "implicit grade token"):
            adapter.run_preflight(
                fixture.context_path,
                stage="before-execution",
                contracts=fixture.contract_args(
                    "taste-selection", "editorial-intent"
                ),
                evidence_paths=fixture.envelopes.values(),
                editing_os_root=fixture.editing_os,
            )

    def test_generated_video_requires_and_accepts_graphics_and_render_evidence(self) -> None:
        fixture = Fixture(
            self.root,
            project_id="generated-video-001",
            artifact_type="generated_video",
            archetype="product_launch",
            captions_required=False,
        )
        self._taste_and_editorial(fixture)
        fixture.add_legacy_evidence(
            "graphics_qa",
            {"schema": "arete-graphics-qa/v1", "status": "pass"},
            stage="before-execution",
        )
        fixture.finalize_context()
        with self.assertRaisesRegex(adapter.AdapterError, "render_log"):
            adapter.run_preflight(
                fixture.context_path,
                stage="before-execution",
                contracts=fixture.contract_args(
                    "taste-selection", "editorial-intent"
                ),
                evidence_paths=fixture.envelopes.values(),
                editing_os_root=fixture.editing_os,
            )
        fixture.add_legacy_evidence(
            "render_log",
            {"schema": "arete-render-log/v1", "status": "pass", "events": ["complete"]},
            stage="before-execution",
        )
        fixture.finalize_context()
        report = adapter.run_preflight(
            fixture.context_path,
            stage="before-execution",
            contracts=fixture.contract_args("taste-selection", "editorial-intent"),
            evidence_paths=fixture.envelopes.values(),
            editing_os_root=fixture.editing_os,
        )
        self.assertEqual(report["status"], "pass")

    def test_publish_rejects_report_for_other_artifact(self) -> None:
        artifact = self.root / "final.mp4"
        artifact.write_bytes(b"one")
        report = write_json(
            self.root / "quality.json",
            {
                "schema": "arete-video-quality-report/v2",
                "artifact": {"path": str(artifact), "sha256": "0" * 64},
                "automated_gate_passed": True,
                "human_review": {"status": "pass"},
                "ready": True,
            },
        )
        with self.assertRaisesRegex(adapter.AdapterError, "exact artifact"):
            adapter.assert_publishable(artifact, report)

    def test_legacy_failure_cannot_be_relabelled_with_passed_flag(self) -> None:
        source = write_json(
            self.root / "failed-qa.json",
            {"schema": "legacy/v1", "status": "fail", "passed": False},
        )
        with self.assertRaisesRegex(adapter.AdapterError, "failure signals"):
            adapter.wrap_evidence(
                source_path=source,
                evidence_id="graphics-qa-main",
                evidence_type="graphics_qa",
                stage="before-final-render",
                schema_id="legacy/v1",
                producer_name="legacy",
                producer_version="1.0",
                passed=True,
                timeline_sha256="a" * 64,
                taste_selection_sha256="b" * 64,
                selected_option_id="option-main",
                treatment_sha256="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()

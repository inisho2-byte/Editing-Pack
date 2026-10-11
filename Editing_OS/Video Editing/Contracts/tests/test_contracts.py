from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "editing_os_contract_validator",
    CONTRACTS_ROOT / "validate.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR_MODULE)

SCHEMA_FILES = VALIDATOR_MODULE.SCHEMA_FILES
validate_document = VALIDATOR_MODULE.validate_document


def load_example(kind: str) -> dict:
    filename = SCHEMA_FILES[kind].replace(".schema.json", ".example.json")
    with (CONTRACTS_ROOT / "examples" / filename).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ContractSchemaTests(unittest.TestCase):
    def test_every_schema_is_valid_draft_2020_12(self) -> None:
        for filename in SCHEMA_FILES.values():
            with self.subTest(schema=filename):
                with (CONTRACTS_ROOT / "schemas" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    Draft202012Validator.check_schema(json.load(handle))

    def test_all_examples_validate(self) -> None:
        for kind in SCHEMA_FILES:
            with self.subTest(kind=kind):
                self.assertEqual(validate_document(kind, load_example(kind)), [])

    def test_unknown_top_level_property_fails_closed(self) -> None:
        payload = load_example("production-context")
        payload["surprise"] = "schema drift"
        errors = validate_document("production-context", payload)
        self.assertTrue(errors)
        self.assertTrue(any(error["validator"] == "additionalProperties" for error in errors))

    def test_missing_governing_document_fails(self) -> None:
        payload = load_example("production-context")
        payload["governing_documents"].pop()
        self.assertTrue(validate_document("production-context", payload))

    def test_duplicate_evidence_type_fails_semantically(self) -> None:
        payload = load_example("production-context")
        duplicate = copy.deepcopy(payload["required_evidence"][0])
        duplicate["evidence_id"] = "editorial-intent-copy"
        payload["required_evidence"].append(duplicate)
        errors = validate_document("production-context", payload)
        self.assertTrue(any(error["validator"] == "semantic" for error in errors))

    def test_scene_loop_reference_must_exist(self) -> None:
        payload = load_example("editorial-intent")
        payload["scenes"][0]["open_loops"]["opened"] = ["loop-does-not-exist"]
        errors = validate_document("editorial-intent", payload)
        self.assertTrue(any("unknown loop_id" in error["message"] for error in errors))

    def test_scene_order_must_be_contiguous(self) -> None:
        payload = load_example("editorial-intent")
        payload["scenes"][2]["order"] = 4
        errors = validate_document("editorial-intent", payload)
        self.assertTrue(any("contiguous" in error["message"] for error in errors))

    def test_selected_taste_option_must_match_status(self) -> None:
        payload = load_example("taste-selection")
        payload["selection"]["selected_option_id"] = "option-editorial-warm"
        errors = validate_document("taste-selection", payload)
        self.assertTrue(any("exactly one option" in error["message"] for error in errors))

    def test_taste_option_requires_executable_treatment(self) -> None:
        payload = load_example("taste-selection")
        del payload["options"][0]["treatment_tokens"]
        errors = validate_document("taste-selection", payload)
        self.assertTrue(errors)

    def test_taste_option_rejects_two_treatment_sources(self) -> None:
        payload = load_example("taste-selection")
        payload["options"][0]["treatment_artifact"] = {
            "path": "treatments/duplicate.json",
            "sha256": "f" * 64,
        }
        errors = validate_document("taste-selection", payload)
        self.assertTrue(errors)

    def test_treatment_motion_range_must_be_ordered(self) -> None:
        payload = load_example("taste-selection")
        motion = payload["options"][0]["treatment_tokens"]["motion"]
        motion["minimum_duration_ms"] = 900
        motion["maximum_duration_ms"] = 200
        errors = validate_document("taste-selection", payload)
        self.assertTrue(any("minimum_duration_ms" in error["message"] for error in errors))

    def test_treatment_palette_cannot_rely_on_renderer_fallbacks(self) -> None:
        payload = load_example("taste-selection")
        del payload["options"][0]["treatment_tokens"]["palette"]["surface"]
        errors = validate_document("taste-selection", payload)
        self.assertTrue(any("surface" in error["message"] for error in errors))

    def test_caption_treatment_cannot_rely_on_platform_style_defaults(self) -> None:
        payload = load_example("taste-selection")
        del payload["options"][0]["treatment_tokens"]["captions"]["accent_color"]
        errors = validate_document("taste-selection", payload)
        self.assertTrue(any("accent_color" in error["message"] for error in errors))

    def test_edl_approval_hash_must_match_edl(self) -> None:
        payload = load_example("edl-approval")
        payload["approval"]["approved_edl_sha256"] = "f" * 64
        errors = validate_document("edl-approval", payload)
        self.assertTrue(any("approved EDL hash" in error["message"] for error in errors))

    def test_approved_edl_cannot_have_unresolved_decisions(self) -> None:
        payload = load_example("edl-approval")
        payload["unresolved_decision_ids"] = ["decision-open-01"]
        errors = validate_document("edl-approval", payload)
        self.assertTrue(errors)

    def test_experiment_baseline_must_match_primary_metric(self) -> None:
        payload = load_example("short-form-experiment")
        payload["baseline"]["metric"] = "completion_rate"
        errors = validate_document("short-form-experiment", payload)
        self.assertTrue(any("baseline metric" in error["message"] for error in errors))

    def test_complete_experiment_requires_results(self) -> None:
        payload = load_example("short-form-experiment")
        payload["status"] = "complete"
        errors = validate_document("short-form-experiment", payload)
        self.assertTrue(any("require a result" in error["message"] for error in errors))

    def test_taste_profile_cannot_be_updated_without_consent(self) -> None:
        payload = load_example("post-publish-learning")
        payload["taste_update"]["applied"] = True
        payload["taste_update"]["profile_after_sha256"] = "f" * 64
        errors = validate_document("post-publish-learning", payload)
        self.assertTrue(errors)
        self.assertTrue(any("granted" in error["message"] for error in errors))

    def test_granted_consent_always_names_the_person_and_time(self) -> None:
        payload = load_example("post-publish-learning")
        payload["taste_update"]["explicit_consent"]["status"] = "granted"
        errors = validate_document("post-publish-learning", payload)
        self.assertTrue(errors)

    def test_audio_sync_pass_flag_must_match_measurement(self) -> None:
        payload = load_example("audio-plan")
        payload["sync_evidence"]["measured_offset_ms"] = 90
        errors = validate_document("audio-plan", payload)
        self.assertTrue(any("passes must reflect" in error["message"] for error in errors))

    def test_audio_masking_checks_cover_every_scene(self) -> None:
        payload = load_example("audio-plan")
        payload["masking_intelligibility_checks"].pop()
        errors = validate_document("audio-plan", payload)
        self.assertTrue(any("cover exactly" in error["message"] for error in errors))

    def test_audio_none_issue_is_exclusive(self) -> None:
        payload = load_example("audio-plan")
        payload["source_assessment"][0]["issues"] = ["none", "noise"]
        errors = validate_document("audio-plan", payload)
        self.assertTrue(any("cannot be combined" in error["message"] for error in errors))

    def test_unknown_kind_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            validate_document("not-a-contract", {})


if __name__ == "__main__":
    unittest.main()

"""Validate Editing OS production contracts.

Stable integration API:

    validate_document(kind: str, payload: Mapping[str, Any])
        -> list[dict[str, str]]

An empty list means the payload is structurally and semantically valid.  This
module deliberately validates document content only.  Callers remain
responsible for resolving artifact paths and verifying declared SHA-256 values
against live bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


CONTRACTS_ROOT = Path(__file__).resolve().parent
SCHEMAS_ROOT = CONTRACTS_ROOT / "schemas"

SCHEMA_FILES: dict[str, str] = {
    "production-context": "production-context.v1.schema.json",
    "editorial-intent": "editorial-intent.v1.schema.json",
    "taste-selection": "taste-selection.v1.schema.json",
    "edl-approval": "edl-approval.v1.schema.json",
    "short-form-experiment": "short-form-experiment.v1.schema.json",
    "post-publish-learning": "post-publish-learning.v1.schema.json",
    "audio-plan": "audio-plan.v1.schema.json",
}

ValidationIssue = dict[str, str]


def _json_path(parts: Any) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _issue(
    path: str,
    message: str,
    validator: str = "semantic",
    schema_path: str = "$semantic",
) -> ValidationIssue:
    return {
        "path": path,
        "message": message,
        "validator": validator,
        "schema_path": schema_path,
    }


@lru_cache(maxsize=None)
def _load_schema(kind: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[kind]
    except KeyError as exc:
        choices = ", ".join(sorted(SCHEMA_FILES))
        raise ValueError(f"unknown contract kind {kind!r}; choose one of: {choices}") from exc

    with (SCHEMAS_ROOT / filename).open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def _duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _unique_field(
    records: list[Mapping[str, Any]],
    field: str,
    path: str,
) -> list[ValidationIssue]:
    values = [record[field] for record in records]
    duplicates = sorted(_duplicates(values), key=str)
    if not duplicates:
        return []
    return [_issue(path, f"{field} values must be unique; duplicates: {duplicates}")]


def _validate_production_context(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues += _unique_field(payload["governing_documents"], "role", "$.governing_documents")
    issues += _unique_field(payload["sources"], "source_id", "$.sources")
    issues += _unique_field(payload["required_evidence"], "evidence_id", "$.required_evidence")
    evidence_types = [item["evidence_type"] for item in payload["required_evidence"]]
    duplicates = sorted(_duplicates(evidence_types))
    if duplicates:
        issues.append(
            _issue(
                "$.required_evidence",
                f"evidence_type values must be unique; duplicates: {duplicates}",
            )
        )
    return issues


def _validate_editorial_intent(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    scenes = payload["scenes"]
    loops = payload["open_loop_ledger"]
    issues += _unique_field(scenes, "scene_id", "$.scenes")
    issues += _unique_field(scenes, "order", "$.scenes")
    issues += _unique_field(loops, "loop_id", "$.open_loop_ledger")

    orders = sorted(scene["order"] for scene in scenes)
    expected_orders = list(range(1, len(scenes) + 1))
    if orders != expected_orders:
        issues.append(
            _issue("$.scenes", f"scene order must be contiguous from 1; got {orders}")
        )

    ordered_scenes = sorted(scenes, key=lambda scene: scene["order"])
    previous_end = 0.0
    scene_ids = {scene["scene_id"] for scene in scenes}
    scene_order = {scene["scene_id"]: scene["order"] for scene in scenes}
    for index, scene in enumerate(ordered_scenes):
        timing = scene["timing"]
        start = timing["planned_start_seconds"]
        end = timing["planned_end_seconds"]
        path = f"$.scenes[{index}].timing"
        if end <= start:
            issues.append(_issue(path, "planned_end_seconds must be greater than start"))
        if start < previous_end:
            issues.append(
                _issue(path, "semantic scenes must not overlap on the planned timeline")
            )
        previous_end = max(previous_end, end)

    points = payload["emotional_curve"]
    positions = [point["position"] for point in points]
    if positions != sorted(positions):
        issues.append(_issue("$.emotional_curve", "positions must be ascending"))
    if positions[0] != 0 or positions[-1] != 1:
        issues.append(
            _issue("$.emotional_curve", "the curve must explicitly start at 0 and end at 1")
        )

    loop_ids = {loop["loop_id"] for loop in loops}
    for index, loop in enumerate(loops):
        base = f"$.open_loop_ledger[{index}]"
        opened = loop["opened_scene_id"]
        payoff = loop["payoff_scene_id"]
        if opened not in scene_ids:
            issues.append(_issue(f"{base}.opened_scene_id", f"unknown scene_id {opened!r}"))
        if payoff not in scene_ids:
            issues.append(_issue(f"{base}.payoff_scene_id", f"unknown scene_id {payoff!r}"))
        if opened in scene_order and payoff in scene_order:
            if scene_order[payoff] <= scene_order[opened]:
                issues.append(
                    _issue(base, "payoff_scene_id must occur after opened_scene_id")
                )

    opened_by_scene: dict[str, set[str]] = {}
    closed_by_scene: dict[str, set[str]] = {}
    for index, scene in enumerate(scenes):
        for action in ("opened", "advanced", "closed"):
            for loop_id in scene["open_loops"][action]:
                if loop_id not in loop_ids:
                    issues.append(
                        _issue(
                            f"$.scenes[{index}].open_loops.{action}",
                            f"unknown loop_id {loop_id!r}",
                        )
                    )
        opened_by_scene[scene["scene_id"]] = set(scene["open_loops"]["opened"])
        closed_by_scene[scene["scene_id"]] = set(scene["open_loops"]["closed"])

    for index, loop in enumerate(loops):
        loop_id = loop["loop_id"]
        opened_scene = loop["opened_scene_id"]
        payoff_scene = loop["payoff_scene_id"]
        if opened_scene in opened_by_scene and loop_id not in opened_by_scene[opened_scene]:
            issues.append(
                _issue(
                    f"$.open_loop_ledger[{index}]",
                    "ledger loop must appear in its opened scene's opened list",
                )
            )
        if payoff_scene in closed_by_scene and loop_id not in closed_by_scene[payoff_scene]:
            issues.append(
                _issue(
                    f"$.open_loop_ledger[{index}]",
                    "ledger loop must appear in its payoff scene's closed list",
                )
            )
    return issues


def _validate_taste_selection(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    options = payload["options"]
    issues = _unique_field(options, "option_id", "$.options")
    selected_id = payload["selection"]["selected_option_id"]
    option_ids = {option["option_id"] for option in options}
    status_selected = [
        option["option_id"] for option in options if option["status"] == "selected"
    ]
    if selected_id not in option_ids:
        issues.append(
            _issue("$.selection.selected_option_id", f"unknown option_id {selected_id!r}")
        )
    if status_selected != [selected_id]:
        issues.append(
            _issue(
                "$.options",
                "exactly one option must have status selected and match selected_option_id",
            )
        )
    for index, option in enumerate(options):
        tokens = option.get("treatment_tokens")
        if tokens is not None:
            motion = tokens["motion"]
            if motion["minimum_duration_ms"] > motion["maximum_duration_ms"]:
                issues.append(
                    _issue(
                        f"$.options[{index}].treatment_tokens.motion",
                        "minimum_duration_ms must not exceed maximum_duration_ms",
                    )
                )
    return issues


def _validate_edl_approval(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    issues = _unique_field(payload["resolved_decisions"], "decision_id", "$.resolved_decisions")
    if payload["status"] == "approved":
        approval = payload["approval"]
        if approval["approved_edl_sha256"] != payload["edl"]["sha256"]:
            issues.append(
                _issue(
                    "$.approval.approved_edl_sha256",
                    "approved EDL hash must equal the reviewed edl.sha256",
                )
            )
    return issues


def _validate_short_form_experiment(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    variants = payload["variants"]
    issues = _unique_field(variants, "variant_id", "$.variants")
    issues += _unique_field(
        [{"sha256": variant["artifact"]["sha256"]} for variant in variants],
        "sha256",
        "$.variants",
    )
    if payload["baseline"]["metric"] != payload["primary_metric"]:
        issues.append(
            _issue("$.baseline.metric", "baseline metric must match primary_metric")
        )
    if payload["primary_metric"] in payload["guardrail_metrics"]:
        issues.append(
            _issue(
                "$.guardrail_metrics",
                "primary_metric must not be duplicated as a guardrail metric",
            )
        )
    if payload["status"] == "planned":
        if any(variant["result"] is not None for variant in variants):
            issues.append(
                _issue("$.variants", "planned experiments cannot contain results")
            )
    if payload["status"] == "complete":
        for index, variant in enumerate(variants):
            result = variant["result"]
            if result is None:
                issues.append(
                    _issue(
                        f"$.variants[{index}].result",
                        "complete experiments require a result for every variant",
                    )
                )
            elif result["metric"] != payload["primary_metric"]:
                issues.append(
                    _issue(
                        f"$.variants[{index}].result.metric",
                        "variant result metric must match primary_metric",
                    )
                )
    return issues


def _validate_post_publish_learning(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues += _unique_field(payload["baseline_metrics"], "metric", "$.baseline_metrics")
    issues += _unique_field(payload["observed_metrics"], "metric", "$.observed_metrics")
    issues += _unique_field(payload["variant_outcomes"], "variant_id", "$.variant_outcomes")
    update = payload["taste_update"]
    if update["proposed"] and not update["suggested_changes"]:
        issues.append(
            _issue(
                "$.taste_update.suggested_changes",
                "a proposed taste update requires at least one suggested change",
            )
        )
    if update["proposed"] and not update["rationale"]:
        issues.append(
            _issue(
                "$.taste_update.rationale",
                "a proposed taste update requires evidence-based rationale",
            )
        )
    return issues


def _validate_audio_plan(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_keys = [
        f"{item['source_id']}::{item['track_id']}" for item in payload["source_assessment"]
    ]
    duplicates = sorted(_duplicates(source_keys))
    if duplicates:
        issues.append(
            _issue(
                "$.source_assessment",
                f"source_id/track_id pairs must be unique; duplicates: {duplicates}",
            )
        )
    for index, source in enumerate(payload["source_assessment"]):
        if "none" in source["issues"] and len(source["issues"]) != 1:
            issues.append(
                _issue(
                    f"$.source_assessment[{index}].issues",
                    "'none' cannot be combined with diagnosed source issues",
                )
            )
    issues += _unique_field(payload["scene_audio_roles"], "scene_id", "$.scene_audio_roles")
    issues += _unique_field(
        payload["masking_intelligibility_checks"],
        "scene_id",
        "$.masking_intelligibility_checks",
    )
    role_scene_ids = {item["scene_id"] for item in payload["scene_audio_roles"]}
    check_scene_ids = {
        item["scene_id"] for item in payload["masking_intelligibility_checks"]
    }
    if role_scene_ids != check_scene_ids:
        issues.append(
            _issue(
                "$.masking_intelligibility_checks",
                "masking checks must cover exactly the declared scene_audio_roles",
            )
        )
    sync = payload["sync_evidence"]
    expected_pass = sync["measured_offset_ms"] <= sync["maximum_offset_ms"]
    if sync["passes"] != expected_pass:
        issues.append(
            _issue(
                "$.sync_evidence.passes",
                "passes must reflect measured_offset_ms <= maximum_offset_ms",
            )
        )
    return issues


SEMANTIC_VALIDATORS: dict[
    str, Callable[[Mapping[str, Any]], list[ValidationIssue]]
] = {
    "production-context": _validate_production_context,
    "editorial-intent": _validate_editorial_intent,
    "taste-selection": _validate_taste_selection,
    "edl-approval": _validate_edl_approval,
    "short-form-experiment": _validate_short_form_experiment,
    "post-publish-learning": _validate_post_publish_learning,
    "audio-plan": _validate_audio_plan,
}


def validate_document(
    kind: str,
    payload: Mapping[str, Any],
) -> list[ValidationIssue]:
    """Return all structural and semantic validation errors for ``payload``.

    ``kind`` must be one of :data:`SCHEMA_FILES`.  The function raises
    ``ValueError`` for an unknown kind or a top-level non-object payload.  It
    does not read paths or compare artifact hashes; the orchestration boundary
    owns those stateful checks.
    """

    if kind not in SCHEMA_FILES:
        _load_schema(kind)  # raises the stable, descriptive ValueError
    if not isinstance(payload, Mapping):
        raise ValueError("contract payload must be a JSON object")

    schema = _load_schema(kind)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    structural_errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    issues = [
        _issue(
            _json_path(error.absolute_path),
            error.message,
            str(error.validator),
            _json_path(error.absolute_schema_path),
        )
        for error in structural_errors
    ]
    if issues:
        return issues
    return SEMANTIC_VALIDATORS[kind](payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(SCHEMA_FILES))
    parser.add_argument("file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        with args.file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        errors = validate_document(args.kind, payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1
    print(json.dumps({"valid": True, "kind": args.kind, "file": str(args.file)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

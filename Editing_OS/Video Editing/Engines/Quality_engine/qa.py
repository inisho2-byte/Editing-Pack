"""ARETE encoded-video quality gate.

This module audits the object that will actually ship.  It complements the
editorial, caption, and graphics engines; it does not replace their semantic
checks.  The gate is intentionally split into:

1. automated encoded-artifact checks;
2. a structured human review of content, motion, layout, and full playback.

Automated success never sets ``ready`` on its own.
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
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # reported as a blocker by _validate_local_schema
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]


SCHEMA = "arete-video-quality-report/v2"
SPEC_SCHEMA = "arete-video-quality-spec/v2"
REVIEW_SCHEMA = "arete-human-video-review/v2"
EVIDENCE_SCHEMA = "arete-evidence-envelope/v1"
DETERMINISM_WAIVER_SCHEMA = "arete-determinism-waiver/v1"
PRODUCTION_CONTEXT_TYPE = "production-context"
PRODUCTION_CONTEXT_VERSION = "1.0.0"

EVIDENCE_STAGES = {"before-execution", "before-final-render"}
KNOWN_EVIDENCE_TYPES = {
    "editorial_intent",
    "taste_selection",
    "edl_approval",
    "forced_alignment",
    "caption_qa",
    "graphics_qa",
    "audio_plan",
    "audio_qa",
    "color_approval",
    "render_log",
    "short_form_experiment",
}
SELF_PRODUCED_EVIDENCE_TYPES = {
    "quality_report",
    "artifact_bound_human_review",
    "post_publish_learning",
}
FEATURE_EVIDENCE = {
    "timeline_edited": {"editorial_intent", "edl_approval"},
    "captions": {"taste_selection", "forced_alignment", "caption_qa"},
    "graphics": {"taste_selection", "graphics_qa"},
    "audio_design": {"taste_selection", "audio_plan", "audio_qa"},
    "color_grade": {"taste_selection", "color_approval"},
    "browser_rendered": {"render_log"},
    "short_form_experiment": {"short_form_experiment"},
}
EVIDENCE_FEATURE_SIGNALS = {
    "edl_approval": "timeline_edited",
    "forced_alignment": "captions",
    "caption_qa": "captions",
    "graphics_qa": "graphics",
    "audio_qa": "audio_design",
    "color_approval": "color_grade",
    "short_form_experiment": "short_form_experiment",
}
TREATMENT_SENSITIVE_EVIDENCE_TYPES = {
    "caption_qa", "graphics_qa", "color_approval", "audio_qa",
}
REQUIRED_FEATURE_FLAGS = tuple(FEATURE_EVIDENCE)
REQUIRED_CONTEXT_FIELDS = (
    "contract_type",
    "schema_version",
    "project_id",
    "created_at",
    "governing_documents",
    "operating_mode",
    "artifact_type",
    "content_archetype",
    "deliverable",
    "objective",
    "audience",
    "sources",
    "accessibility",
    "required_evidence",
)
REQUIRED_GOVERNING_DOCUMENT_ROLES = {
    "master_prompt",
    "taste_profile",
    "tool_routing",
    "quality_standard",
    "editing_handbook",
}

SEVERITY_ORDER = {"suggestion": 0, "minor": 1, "major": 2, "blocker": 3}
BLOCKING_SEVERITIES = {"blocker", "major"}
ALPHA_PIXEL_FORMATS = {
    "argb", "abgr", "rgba", "bgra", "rgba64be", "rgba64le",
    "bgra64be", "bgra64le", "gbrap", "gbrap10be", "gbrap10le",
    "gbrap12be", "gbrap12le", "gbrap16be", "gbrap16le",
    "yuva420p", "yuva422p", "yuva444p", "yuva420p9be", "yuva420p9le",
    "yuva422p9be", "yuva422p9le", "yuva444p9be", "yuva444p9le",
    "yuva420p10be", "yuva420p10le", "yuva422p10be", "yuva422p10le",
    "yuva444p10be", "yuva444p10le", "yuva420p16be", "yuva420p16le",
    "yuva422p16be", "yuva422p16le", "yuva444p16be", "yuva444p16le",
}

CREATIVE_SCORE_WEIGHTS = {
    "story_and_clarity": 18,
    "visual_hierarchy_and_layout": 14,
    "typography": 10,
    "motion_and_choreography": 14,
    "timing_and_pacing": 14,
    "visual_consistency": 10,
    "audio_design": 10,
    "captions_and_accessibility": 10,
}

UNIVERSAL_CRITERIA = {
    "clarity": "The viewer can understand the intended message and change.",
    "story": "The sequence creates meaningful progression and payoff.",
    "emotion": "The intended feeling is created rather than merely described.",
    "retention": "Attention is earned and renewed without harming comprehension.",
    "memorability": "A distinctive idea, image, phrase, proof, or feeling remains.",
}
UNIVERSAL_CRITERIA_FLOOR = 3

# These checks require eyes, ears, and editorial judgment.  They are deliberately
# explicit so a reviewer cannot replace the uninterrupted watch with thumbnails.
REQUIRED_REVIEW_CHECKS = {
    "complete_playback": "blocker",
    "content_accuracy": "blocker",
    "first_frame": "major",
    "last_frame": "major",
    "scene_boundaries": "major",
    "transitions": "major",
    "major_animation_phases": "major",
    "maximum_density_frames": "major",
    "layout_and_safe_areas": "major",
    "typography_and_copy": "major",
    "motion_purpose_and_coherence": "major",
    "pacing_and_reading_time": "major",
    "caption_sync_and_placement": "major",
    "audio_clarity_and_sync": "major",
    "visual_consistency": "major",
    "accessibility_and_flashing": "blocker",
    "target_device_and_platform_ui": "major",
}

ERROR_LOG_PATTERNS = (
    re.compile(r"\b(error|fatal|uncaught|exception|failed|failure)\b", re.I),
    re.compile(r"\b(404|net::err_|media.*not.*loaded|decode error)\b", re.I),
)


class QualityAuditError(RuntimeError):
    """Raised for invalid inputs or unavailable required tools."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def _run(args: Sequence[str], *, check: bool = False) -> CommandResult:
    result = subprocess.run(
        runtime.command(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=runtime.child_env(), **runtime.child_kwargs(),
    )
    command = CommandResult(tuple(str(value) for value in args), result.returncode,
                            result.stdout, result.stderr)
    if check and result.returncode != 0:
        tail = (result.stderr or result.stdout)[-4000:]
        raise QualityAuditError(f"{args[0]} failed with exit {result.returncode}:\n{tail}")
    return command


def _load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityAuditError(f"cannot read JSON {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise QualityAuditError(f"JSON root must be an object: {source}")
    return data


LOCAL_SCHEMA_FILES = {
    SPEC_SCHEMA: "quality-spec.v2.schema.json",
    REVIEW_SCHEMA: "human-review.v2.schema.json",
    EVIDENCE_SCHEMA: "evidence-envelope.v1.schema.json",
    DETERMINISM_WAIVER_SCHEMA: "determinism-waiver.v1.schema.json",
}


@lru_cache(maxsize=None)
def _local_validator(schema_id: str) -> Any:
    if Draft202012Validator is None or FormatChecker is None:
        raise ImportError("jsonschema>=4.20 is required")
    filename = LOCAL_SCHEMA_FILES[schema_id]
    schema_path = Path(__file__).resolve().parent / "schemas" / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_local_schema(schema_id: str, data: Mapping[str, Any]) -> list[dict[str, str]]:
    try:
        validator = _local_validator(schema_id)
    except Exception as exc:
        schema_path = Path(__file__).resolve().parent / "schemas" / LOCAL_SCHEMA_FILES[schema_id]
        return [{"path": "$", "message": f"cannot load local schema {schema_path}: {exc}"}]
    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: (
            ".".join(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    results: list[dict[str, str]] = []
    for error in errors:
        path = "$"
        for part in error.absolute_path:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        results.append({"path": path, "message": error.message})
    return results


@lru_cache(maxsize=1)
def _production_context_validator() -> Any:
    validator_path = (
        Path(__file__).resolve().parents[2] / "Contracts" / "validate.py"
    )
    if not validator_path.is_file():
        raise ImportError(f"canonical contract validator is missing: {validator_path}")
    module_spec = importlib.util.spec_from_file_location(
        "arete_contract_validation", validator_path,
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load {validator_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module.validate_document


def _validate_production_context_contract(
    data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Use the canonical Contracts validator instead of duplicating its schema."""
    try:
        result = _production_context_validator()("production-context", data)
    except Exception as exc:  # dependency/import failures must fail closed
        return [{
            "path": "$",
            "message": f"canonical contract validation could not run: {exc}",
        }]
    return list(result)


def _fraction(value: Any) -> float | None:
    if value in (None, "", "0/0"):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float) and math.isfinite(value):
        return round(value, digits)
    return value


def _issue(severity: str, code: str, message: str, *,
           stage: str = "encoded-artifact", evidence: Any = None,
           mandatory: bool = True) -> dict[str, Any]:
    if severity not in SEVERITY_ORDER:
        raise ValueError(f"unknown severity: {severity}")
    item = {
        "severity": severity,
        "code": code,
        "stage": stage,
        "message": message,
        "mandatory": bool(mandatory),
    }
    if evidence is not None:
        item["evidence"] = evidence
    return item


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _is_nonempty(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes)):
        return len(value) > 0
    return True


def _source_identity(source: Mapping[str, Any]) -> str | None:
    for key in ("source_id", "id"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_name(source: Mapping[str, Any]) -> str | None:
    for key in ("name", "title", "label"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _require_nonempty_fields(
    data: Mapping[str, Any],
    fields: Iterable[str],
    *,
    code: str,
    label: str,
    stage: str,
    issues: list[dict[str, Any]],
) -> bool:
    missing = sorted(key for key in fields if not _is_nonempty(data.get(key)))
    if missing:
        issues.append(_issue(
            "blocker", code,
            f"{label} is missing required field(s): {', '.join(missing)}.",
            stage=stage, evidence={"missing_fields": missing},
        ))
        return False
    return True


def _load_production_context(
    spec: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and minimally validate the immutable production-context contract."""
    reference = spec.get("production_context")
    summary = {
        "path": None,
        "expected_sha256": None,
        "observed_sha256": None,
        "valid": False,
        "project_id": None,
        "source_ids": [],
    }
    if not isinstance(reference, Mapping):
        issues.append(_issue(
            "blocker", "production_context_reference_missing",
            "Quality spec must reference an immutable production-context contract.",
            stage="requirements",
        ))
        return {}, summary
    path_value = reference.get("path")
    expected_hash = reference.get("sha256")
    if not isinstance(path_value, str) or not path_value.strip() or not _is_sha256(expected_hash):
        issues.append(_issue(
            "blocker", "production_context_reference_invalid",
            "production_context requires a non-empty path and lowercase/uppercase SHA-256.",
            stage="requirements",
        ))
        return {}, summary
    path = Path(path_value).resolve()
    summary.update({"path": str(path), "expected_sha256": str(expected_hash).lower()})
    if not path.is_file():
        issues.append(_issue(
            "blocker", "production_context_missing",
            f"Referenced production context does not exist: {path}",
            stage="requirements",
        ))
        return {}, summary
    observed_hash = _artifact_sha256(path)
    summary["observed_sha256"] = observed_hash
    if observed_hash.lower() != str(expected_hash).lower():
        issues.append(_issue(
            "blocker", "production_context_fingerprint_mismatch",
            "Production context changed after the quality spec was authored.",
            stage="requirements",
            evidence={"expected": str(expected_hash).lower(), "observed": observed_hash},
        ))
    try:
        context = _load_json(path)
    except QualityAuditError as exc:
        issues.append(_issue(
            "blocker", "production_context_invalid_json", str(exc),
            stage="requirements",
        ))
        return {}, summary
    complete = _require_nonempty_fields(
        context, (key for key in REQUIRED_CONTEXT_FIELDS if key != "required_evidence"),
        code="production_context_incomplete", label="Production context",
        stage="requirements", issues=issues,
    )
    if not isinstance(context.get("required_evidence"), list):
        complete = False
        issues.append(_issue(
            "blocker", "production_context_incomplete",
            "Production context required_evidence must be a list, including an "
            "explicit empty list when no upstream evidence applies.",
            stage="requirements",
        ))
    if context.get("contract_type") != PRODUCTION_CONTEXT_TYPE:
        complete = False
        issues.append(_issue(
            "blocker", "production_context_type_invalid",
            f"contract_type must be {PRODUCTION_CONTEXT_TYPE!r}.",
            stage="requirements",
        ))
    if str(context.get("schema_version")) != PRODUCTION_CONTEXT_VERSION:
        complete = False
        issues.append(_issue(
            "blocker", "production_context_version_invalid",
            f"schema_version must be {PRODUCTION_CONTEXT_VERSION!r}.",
            stage="requirements",
        ))
    contract_errors = _validate_production_context_contract(context)
    if contract_errors:
        complete = False
        issues.append(_issue(
            "blocker", "production_context_schema_invalid",
            "Production context does not satisfy the canonical v1 contract.",
            stage="requirements", evidence={"errors": contract_errors[:50]},
        ))

    governing = context.get("governing_documents")
    roles: set[str] = set()
    if isinstance(governing, list):
        for item in governing:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip()
            path_text = str(item.get("path") or "").strip()
            fingerprint = item.get("sha256")
            if role:
                roles.add(role)
            if not role or not path_text or not _is_sha256(fingerprint):
                complete = False
                issues.append(_issue(
                    "blocker", "governing_document_invalid",
                    "Every governing document needs role, path, and SHA-256.",
                    stage="requirements", evidence=dict(item),
                ))
    else:
        complete = False
    missing_roles = sorted(REQUIRED_GOVERNING_DOCUMENT_ROLES - roles)
    if missing_roles:
        complete = False
        issues.append(_issue(
            "blocker", "governing_documents_incomplete",
            f"Production context is missing governing role(s): {', '.join(missing_roles)}.",
            stage="requirements", evidence={"observed_roles": sorted(roles)},
        ))

    sources = context.get("sources")
    source_ids: list[str] = []
    if not isinstance(sources, list) or not sources:
        complete = False
        issues.append(_issue(
            "blocker", "named_sources_missing",
            "Production context must name at least one content/source-of-truth item.",
            stage="requirements",
        ))
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, Mapping):
                complete = False
                issues.append(_issue(
                    "blocker", "named_source_invalid",
                    f"Source at index {index} must be an object.",
                    stage="requirements",
                ))
                continue
            source_id = _source_identity(source)
            locator = source.get("locator")
            if not source_id or not _is_nonempty(locator):
                complete = False
                issues.append(_issue(
                    "blocker", "named_source_invalid",
                    "Every source requires a stable source_id/id and a named locator.",
                    stage="requirements", evidence={"index": index, "source": dict(source)},
                ))
                continue
            source_ids.append(source_id)
        if len(source_ids) != len(set(source_ids)):
            complete = False
            issues.append(_issue(
                "blocker", "named_source_id_duplicate",
                "Production-context source IDs must be unique.",
                stage="requirements",
            ))

    summary["project_id"] = context.get("project_id")
    summary["source_ids"] = sorted(set(source_ids))
    summary["valid"] = (
        complete
        and observed_hash.lower() == str(expected_hash).lower()
        and not any(
            item["stage"] == "requirements" and item["severity"] == "blocker"
            for item in issues
        )
    )
    return context, summary


def _validate_quality_spec(
    spec: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    schema_errors = _validate_local_schema(SPEC_SCHEMA, spec)
    if schema_errors:
        issues.append(_issue(
            "blocker", "quality_spec_schema_validation_failed",
            "Quality spec does not satisfy the complete v2 JSON Schema.",
            stage="requirements", evidence={"errors": schema_errors[:50]},
        ))
    if spec.get("schema") != SPEC_SCHEMA:
        issues.append(_issue(
            "blocker", "quality_spec_schema_invalid",
            f"Quality spec schema must be {SPEC_SCHEMA!r}.",
            stage="requirements",
        ))
    required_sections = (
        "production_context", "features", "delivery", "audio", "determinism",
        "thresholds", "intentional_intervals", "intentional_endpoints",
        "review_times", "evidence",
    )
    missing_sections = sorted(key for key in required_sections if key not in spec)
    if missing_sections:
        issues.append(_issue(
            "blocker", "quality_spec_incomplete",
            f"Quality spec is missing section(s): {', '.join(missing_sections)}.",
            stage="requirements",
        ))
    features = spec.get("features")
    if not isinstance(features, Mapping):
        issues.append(_issue(
            "blocker", "quality_spec_features_invalid",
            "features must be an object containing explicit booleans.",
            stage="requirements",
        ))
    else:
        missing = sorted(key for key in REQUIRED_FEATURE_FLAGS if key not in features)
        non_boolean = sorted(
            key for key in REQUIRED_FEATURE_FLAGS
            if key in features and not isinstance(features.get(key), bool)
        )
        if missing or non_boolean:
            issues.append(_issue(
                "blocker", "quality_spec_features_incomplete",
                "Every supported feature flag must be declared as true or false.",
                stage="requirements",
                evidence={"missing": missing, "non_boolean": non_boolean},
            ))

    delivery = spec.get("delivery")
    delivery_fields = (
        "width", "height", "aspect_ratio", "fps", "fps_tolerance",
        "variable_frame_rate_allowed", "duration_s", "duration_tolerance_s",
        "video_codec", "pixel_format", "alpha_allowed",
        "rotation_metadata_allowed", "audio_required",
    )
    if not isinstance(delivery, Mapping):
        issues.append(_issue(
            "blocker", "delivery_spec_invalid",
            "delivery must be a complete object.", stage="requirements",
        ))
    else:
        # False is a valid explicit policy for boolean delivery fields.
        missing = sorted(key for key in delivery_fields if key not in delivery)
        if missing:
            issues.append(_issue(
                "blocker", "delivery_spec_incomplete",
                f"Delivery spec is missing field(s): {', '.join(missing)}.",
                stage="requirements",
            ))
        if delivery.get("audio_required") is True:
            audio_fields = ("audio_codec", "audio_sample_rate", "audio_channels")
            missing_audio = sorted(key for key in audio_fields if not _is_nonempty(delivery.get(key)))
            if missing_audio:
                issues.append(_issue(
                    "blocker", "delivery_audio_spec_incomplete",
                    f"Audio delivery is missing field(s): {', '.join(missing_audio)}.",
                    stage="requirements",
                ))


def _validate_determinism_contract(
    spec: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None]:
    determinism = spec.get("determinism")
    if not isinstance(determinism, Mapping) or not isinstance(
        determinism.get("determinism_required"), bool
    ):
        issues.append(_issue(
            "blocker", "determinism_policy_missing",
            "determinism.determinism_required must be explicitly true or false.",
            stage="determinism",
        ))
        return True, None
    required = bool(determinism["determinism_required"])
    waiver = determinism.get("waiver")
    if required:
        if waiver not in (None, {}):
            issues.append(_issue(
                "blocker", "determinism_waiver_not_allowed",
                "A waiver cannot be attached when determinism_required is true.",
                stage="determinism",
            ))
        return True, None
    if not isinstance(waiver, Mapping):
        issues.append(_issue(
            "blocker", "determinism_waiver_missing",
            "determinism_required=false is valid only with a complete approved waiver.",
            stage="determinism",
        ))
        return False, None
    required_fields = (
        "schema", "waiver_id", "approved_by", "approved_at", "reason",
        "scope", "risk_acceptance", "alternative_verification",
    )
    valid = _require_nonempty_fields(
        waiver, required_fields,
        code="determinism_waiver_incomplete", label="Determinism waiver",
        stage="determinism", issues=issues,
    )
    if waiver.get("schema") != DETERMINISM_WAIVER_SCHEMA:
        valid = False
        issues.append(_issue(
            "blocker", "determinism_waiver_schema_invalid",
            f"Waiver schema must be {DETERMINISM_WAIVER_SCHEMA!r}.",
            stage="determinism",
        ))
    waiver_schema_errors = _validate_local_schema(DETERMINISM_WAIVER_SCHEMA, waiver)
    if waiver_schema_errors:
        valid = False
        issues.append(_issue(
            "blocker", "determinism_waiver_schema_validation_failed",
            "Determinism waiver does not satisfy its complete JSON Schema.",
            stage="determinism", evidence={"errors": waiver_schema_errors[:50]},
        ))
    alternative = waiver.get("alternative_verification")
    if not isinstance(alternative, Mapping) or not all(
        _is_nonempty(alternative.get(key)) for key in ("method", "evidence")
    ):
        valid = False
        issues.append(_issue(
            "blocker", "determinism_waiver_alternative_invalid",
            "Waiver alternative_verification requires method and evidence.",
            stage="determinism",
        ))
    return False, dict(waiver) if valid else None


def _probe(path: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        (
            "format=duration,size,bit_rate,format_name:"
            "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,"
            "sample_aspect_ratio,display_aspect_ratio,r_frame_rate,avg_frame_rate,"
            "nb_frames,sample_rate,channels,channel_layout,color_space,color_transfer,"
            "color_primaries,duration,bit_rate:stream_tags=rotate:"
            "stream_side_data=rotation"
        ),
        "-of", "json", str(path),
    ])
    if result.returncode != 0:
        raise QualityAuditError(f"ffprobe could not read {path}:\n{result.stderr[-4000:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QualityAuditError(f"ffprobe returned invalid JSON for {path}") from exc


def _stream(probe: Mapping[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (dict(item) for item in probe.get("streams", [])
         if item.get("codec_type") == kind),
        None,
    )


def _rotation(video: Mapping[str, Any]) -> float:
    tag_value = (video.get("tags") or {}).get("rotate")
    values: list[Any] = [tag_value]
    values.extend(
        side.get("rotation")
        for side in video.get("side_data_list", [])
        if isinstance(side, Mapping)
    )
    for value in values:
        try:
            if value is not None:
                return float(value) % 360
        except (TypeError, ValueError):
            continue
    return 0.0


def _duration(probe: Mapping[str, Any]) -> float:
    try:
        return float((probe.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        return 0.0


def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decoded_fingerprint(path: Path, selector: str) -> str | None:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-map", selector, "-f", "framemd5", "-",
    ])
    if result.returncode != 0:
        if "matches no streams" in result.stderr.lower():
            return None
        raise QualityAuditError(
            f"could not fingerprint {selector} in {path}: {result.stderr[-2000:]}"
        )
    normalized = "\n".join(
        line.strip() for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("#")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _decode_integrity(path: Path) -> dict[str, Any]:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror",
        "-err_detect", "explode", "-i", str(path), "-map", "0:v:0?",
        "-map", "0:a:0?", "-f", "null", "NUL",
    ])
    return {
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "errors": [line for line in result.stderr.splitlines() if line.strip()][-30:],
    }


def _parse_intervals(text: str, prefix: str) -> list[dict[str, float | None]]:
    intervals: list[dict[str, float | None]] = []
    token_re = re.compile(
        rf"{re.escape(prefix)}_(start|end|duration):\s*([0-9.]+)"
    )
    current: dict[str, float] = {}

    def flush() -> None:
        nonlocal current
        if "start" not in current:
            current = {}
            return
        start = current["start"]
        end = current.get("end")
        duration = current.get("duration")
        if end is None and duration is not None:
            end = start + duration
        if duration is None and end is not None:
            duration = max(0.0, end - start)
        intervals.append({
            "start": _round(start),
            "end": _round(end) if end is not None else None,
            "duration": _round(duration) if duration is not None else None,
        })
        current = {}

    for line in text.splitlines():
        for match in token_re.finditer(line):
            key, raw_value = match.groups()
            if key == "start" and "start" in current:
                flush()
            current[key] = float(raw_value)
    flush()
    return intervals


def _scan_black(path: Path) -> list[dict[str, float | None]]:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-vf", "blackdetect=d=0.08:pix_th=0.10:pic_th=0.985",
        "-an", "-f", "null", "NUL",
    ])
    return _parse_intervals(result.stderr, "black")


def _scan_freeze(path: Path, duration_s: float | None = None) -> list[dict[str, float | None]]:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-vf", "freezedetect=n=-60dB:d=0.5", "-an", "-f", "null", "NUL",
    ])
    intervals = _parse_intervals(result.stderr, "freeze")
    if intervals and intervals[-1].get("end") is None and duration_s is not None:
        start = float(intervals[-1]["start"])
        intervals[-1]["end"] = _round(duration_s)
        intervals[-1]["duration"] = _round(max(0.0, duration_s - start))
    return intervals


def _scan_silence(path: Path, duration_s: float | None = None) -> list[dict[str, float | None]]:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-af", "silencedetect=noise=-50dB:d=0.7", "-vn", "-f", "null", "NUL",
    ])
    intervals = _parse_intervals(result.stderr, "silence")
    if intervals and intervals[-1].get("end") is None and duration_s is not None:
        start = float(intervals[-1]["start"])
        intervals[-1]["end"] = _round(duration_s)
        intervals[-1]["duration"] = _round(max(0.0, duration_s - start))
    return intervals


def _scan_scenes(path: Path, threshold: float) -> list[float]:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "NUL",
    ])
    times = [
        float(match.group(1))
        for match in re.finditer(r"pts_time:([0-9.]+)", result.stderr)
    ]
    return sorted({_round(value, 3) for value in times})


def _frame_metrics(path: Path, at_s: float, width: int = 160,
                   height: int = 90) -> dict[str, Any]:
    result = subprocess.run([
        runtime.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", str(max(0.0, at_s)),
        "-i", str(path), "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ], capture_output=True, env=runtime.child_env(), **runtime.child_kwargs())
    pixels = result.stdout
    if result.returncode != 0 or not pixels:
        return {"at_s": _round(at_s, 3), "readable": False}
    count = len(pixels)
    mean = sum(pixels) / count
    variance = sum((value - mean) ** 2 for value in pixels) / count
    stddev = math.sqrt(variance)
    active = sum(1 for value in pixels if abs(value - mean) >= 8) / count
    return {
        "at_s": _round(at_s, 3),
        "readable": True,
        "mean_luma": _round(mean, 3),
        "luma_stddev": _round(stddev, 3),
        "active_pixel_ratio": _round(active, 5),
        "near_uniform": stddev < 2.0 and active < 0.005,
        "near_black_blank": mean < 8.0 and stddev < 4.0 and active < 0.005,
    }


def _audio_loudness(path: Path) -> dict[str, Any] | None:
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-map", "0:a:0", "-af",
        "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-f", "null", "NUL",
    ])
    if "matches no streams" in result.stderr.lower():
        return None
    candidates = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.S)
    if not candidates:
        return {"measured": False, "error": result.stderr[-2000:]}
    try:
        raw = json.loads(candidates[-1])
    except json.JSONDecodeError:
        return {"measured": False, "error": candidates[-1]}
    parsed: dict[str, Any] = {"measured": True}
    mapping = {
        "input_i": "integrated_lufs",
        "input_tp": "true_peak_dbtp",
        "input_lra": "loudness_range_lu",
        "input_thresh": "threshold_lufs",
    }
    for source, target in mapping.items():
        try:
            parsed[target] = float(raw[source])
        except (KeyError, TypeError, ValueError):
            parsed[target] = None
    return parsed


def _interval_acknowledged(interval: Mapping[str, Any],
                           acknowledged: Iterable[Mapping[str, Any]],
                           tolerance: float = 0.08) -> bool:
    start = float(interval.get("start", 0))
    end_value = interval.get("end")
    if end_value is None:
        end_value = start + float(interval.get("duration", 0))
    end = float(end_value)
    for allowed in acknowledged:
        try:
            allowed_start = float(allowed["start"])
            allowed_end = float(allowed["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start >= allowed_start - tolerance and end <= allowed_end + tolerance:
            return True
    return False


def _check_delivery(probe: Mapping[str, Any], spec: Mapping[str, Any],
                    issues: list[dict[str, Any]]) -> dict[str, Any]:
    delivery = dict(spec.get("delivery") or {})
    video = _stream(probe, "video")
    audio = _stream(probe, "audio")
    observed: dict[str, Any] = {
        "video_present": video is not None,
        "audio_present": audio is not None,
        "duration_s": _round(_duration(probe)),
    }
    if video is None:
        issues.append(_issue("blocker", "video_stream_missing",
                             "Encoded artifact has no video stream."))
        return observed

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    avg_fps = _fraction(video.get("avg_frame_rate"))
    nominal_fps = _fraction(video.get("r_frame_rate"))
    rotation = _rotation(video)
    observed.update({
        "width": width,
        "height": height,
        "aspect_ratio": _round(width / height if height else 0),
        "codec": video.get("codec_name"),
        "profile": video.get("profile"),
        "pixel_format": video.get("pix_fmt"),
        "average_fps": _round(avg_fps),
        "nominal_fps": _round(nominal_fps),
        "sample_aspect_ratio": video.get("sample_aspect_ratio"),
        "display_aspect_ratio": video.get("display_aspect_ratio"),
        "rotation_degrees": _round(rotation),
        "color_space": video.get("color_space"),
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
    })
    if audio:
        observed["audio"] = {
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
            "channel_layout": audio.get("channel_layout"),
        }

    def expected_int(key: str) -> int | None:
        value = delivery.get(key)
        return int(value) if value is not None else None

    expected_width = expected_int("width")
    expected_height = expected_int("height")
    if expected_width is not None and width != expected_width:
        issues.append(_issue(
            "blocker", "width_mismatch",
            f"Width is {width}px; requested {expected_width}px.",
            evidence={"observed": width, "expected": expected_width},
        ))
    if expected_height is not None and height != expected_height:
        issues.append(_issue(
            "blocker", "height_mismatch",
            f"Height is {height}px; requested {expected_height}px.",
            evidence={"observed": height, "expected": expected_height},
        ))
    expected_aspect = delivery.get("aspect_ratio")
    if expected_aspect:
        try:
            if isinstance(expected_aspect, str) and ":" in expected_aspect:
                left, right = expected_aspect.split(":", 1)
                expected_ratio = float(left) / float(right)
            else:
                expected_ratio = float(expected_aspect)
            observed_ratio = width / height
            if abs(observed_ratio - expected_ratio) > 0.002:
                issues.append(_issue(
                    "blocker", "aspect_ratio_mismatch",
                    f"Display ratio {observed_ratio:.5f} does not match requested "
                    f"{expected_ratio:.5f}.",
                    evidence={"observed": observed_ratio, "expected": expected_ratio},
                ))
        except (TypeError, ValueError, ZeroDivisionError):
            issues.append(_issue("blocker", "invalid_expected_aspect_ratio",
                                 f"Invalid aspect ratio in spec: {expected_aspect!r}",
                                 stage="requirements"))

    expected_fps = delivery.get("fps")
    fps_tolerance = float(delivery.get("fps_tolerance", 0.01))
    if expected_fps is not None and (
        avg_fps is None or abs(avg_fps - float(expected_fps)) > fps_tolerance
    ):
        issues.append(_issue(
            "blocker", "frame_rate_mismatch",
            f"Average frame rate is {avg_fps}; requested {expected_fps}.",
            evidence={"observed": avg_fps, "expected": expected_fps,
                      "tolerance": fps_tolerance},
        ))
    if (
        not delivery.get("variable_frame_rate_allowed", False)
        and avg_fps is not None and nominal_fps is not None
        and abs(avg_fps - nominal_fps) > max(0.05, fps_tolerance)
    ):
        issues.append(_issue(
            "major", "variable_or_incoherent_frame_rate",
            f"Nominal frame rate ({nominal_fps:.5f}) and average frame rate "
            f"({avg_fps:.5f}) disagree.",
            evidence={"nominal": nominal_fps, "average": avg_fps},
        ))

    expected_codec = delivery.get("video_codec")
    if expected_codec and str(video.get("codec_name")).lower() != str(expected_codec).lower():
        issues.append(_issue(
            "blocker", "video_codec_mismatch",
            f"Video codec is {video.get('codec_name')}; requested {expected_codec}.",
        ))
    expected_pix_fmt = delivery.get("pixel_format")
    if expected_pix_fmt and video.get("pix_fmt") != expected_pix_fmt:
        issues.append(_issue(
            "major", "pixel_format_mismatch",
            f"Pixel format is {video.get('pix_fmt')}; requested {expected_pix_fmt}.",
        ))
    pix_fmt = str(video.get("pix_fmt") or "")
    if pix_fmt in ALPHA_PIXEL_FORMATS and not delivery.get("alpha_allowed", False):
        issues.append(_issue(
            "major", "unintended_alpha_channel",
            f"Delivery pixel format {pix_fmt} contains alpha, but transparency is not allowed.",
        ))
    if rotation not in (0.0, 360.0) and not delivery.get("rotation_metadata_allowed", False):
        issues.append(_issue(
            "major", "rotation_metadata_present",
            f"Video relies on {rotation:g}° rotation metadata; bake orientation into pixels.",
        ))
    sample_aspect = video.get("sample_aspect_ratio")
    if sample_aspect not in (None, "1:1", "N/A", "0:1"):
        issues.append(_issue(
            "major", "non_square_pixels",
            f"Sample aspect ratio is {sample_aspect}; delivery should use square pixels.",
        ))

    expected_duration = delivery.get("duration_s")
    if expected_duration is not None:
        tolerance = float(delivery.get("duration_tolerance_s", 0.12))
        delta = abs(_duration(probe) - float(expected_duration))
        observed["duration_delta_s"] = _round(delta)
        if delta > tolerance:
            issues.append(_issue(
                "blocker", "duration_mismatch",
                f"Duration differs from the requested timeline by {delta:.3f}s "
                f"(tolerance {tolerance:.3f}s).",
                evidence={"observed": _duration(probe), "expected": expected_duration,
                          "delta": delta, "tolerance": tolerance},
            ))

    audio_required = bool(delivery.get("audio_required", True))
    if audio_required and audio is None:
        issues.append(_issue("blocker", "audio_stream_missing",
                             "Delivery requires audio, but no audio stream is present."))
    if audio is not None:
        expected_audio_codec = delivery.get("audio_codec")
        if expected_audio_codec and (
            str(audio.get("codec_name")).lower() != str(expected_audio_codec).lower()
        ):
            issues.append(_issue(
                "major", "audio_codec_mismatch",
                f"Audio codec is {audio.get('codec_name')}; requested {expected_audio_codec}.",
            ))
        expected_rate = delivery.get("audio_sample_rate")
        if expected_rate and int(audio.get("sample_rate") or 0) != int(expected_rate):
            issues.append(_issue(
                "major", "audio_sample_rate_mismatch",
                f"Audio sample rate is {audio.get('sample_rate')}Hz; requested {expected_rate}Hz.",
            ))
        expected_channels = delivery.get("audio_channels")
        if expected_channels and int(audio.get("channels") or 0) != int(expected_channels):
            issues.append(_issue(
                "major", "audio_channel_mismatch",
                f"Audio has {audio.get('channels')} channels; requested {expected_channels}.",
            ))
    return observed


def _check_scan_intervals(
    scan_name: str,
    intervals: list[dict[str, Any]],
    spec: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    intentional = (spec.get("intentional_intervals") or {}).get(scan_name, [])
    thresholds = {
        "black": float((spec.get("thresholds") or {}).get(
            "max_unacknowledged_black_s", 0.12)),
        "freeze": float((spec.get("thresholds") or {}).get(
            "max_unacknowledged_freeze_s", 0.55)),
        "silence": float((spec.get("thresholds") or {}).get(
            "max_unacknowledged_silence_s", 1.5)),
    }
    severities = {"black": "major", "freeze": "major", "silence": "major"}
    for interval in intervals:
        duration = float(interval.get("duration") or 0)
        if duration <= thresholds[scan_name]:
            continue
        if _interval_acknowledged(interval, intentional):
            interval["acknowledged"] = True
            continue
        interval["acknowledged"] = False
        issues.append(_issue(
            severities[scan_name],
            f"unacknowledged_{scan_name}_interval",
            f"Detected {duration:.3f}s {scan_name} interval at "
            f"{interval.get('start')}–{interval.get('end')}s.",
            evidence=interval,
        ))


def _feature_required_evidence_types(
    context: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> set[str]:
    features = spec.get("features") if isinstance(spec.get("features"), Mapping) else {}
    required: set[str] = set()
    for feature, evidence_types in FEATURE_EVIDENCE.items():
        if features.get(feature) is True:
            required.update(evidence_types)
    mode = str(context.get("operating_mode") or "").strip().lower()
    artifact_type = str(context.get("artifact_type") or "").strip().lower()
    if mode in {"standard", "flagship"} and artifact_type in {
        "video_edit", "generated_video", "motion_graphic", "hybrid",
    }:
        required.add("editorial_intent")
    return required


def _context_evidence_requirements(
    context: Mapping[str, Any],
    spec: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    raw = context.get("required_evidence")
    requirements: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, list):
        issues.append(_issue(
            "blocker", "context_evidence_requirements_invalid",
            "production-context required_evidence must be a list.",
            stage="evidence",
        ))
        return requirements
    seen_types: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            issues.append(_issue(
                "blocker", "context_evidence_requirement_invalid",
                f"Evidence requirement at index {index} must be an object.",
                stage="evidence",
            ))
            continue
        required_fields = (
            "evidence_id", "evidence_type", "stage", "schema_id",
            "expected_path", "required",
        )
        if not all(key in item and _is_nonempty(item.get(key)) for key in required_fields):
            issues.append(_issue(
                "blocker", "context_evidence_requirement_incomplete",
                f"Evidence requirement at index {index} is incomplete.",
                stage="evidence", evidence=dict(item),
            ))
            continue
        evidence_id = str(item["evidence_id"])
        evidence_type = str(item["evidence_type"])
        stage = str(item["stage"])
        if evidence_id in requirements:
            issues.append(_issue(
                "blocker", "context_evidence_id_duplicate",
                f"Duplicate required evidence ID: {evidence_id}.",
                stage="evidence",
            ))
            continue
        if evidence_type not in KNOWN_EVIDENCE_TYPES | SELF_PRODUCED_EVIDENCE_TYPES:
            issues.append(_issue(
                "blocker", "context_evidence_type_unknown",
                f"Unknown required evidence type: {evidence_type}.",
                stage="evidence",
            ))
            continue
        if stage not in EVIDENCE_STAGES:
            issues.append(_issue(
                "blocker", "context_evidence_stage_invalid",
                f"Evidence {evidence_id} has invalid stage {stage!r}.",
                stage="evidence",
            ))
            continue
        if item.get("required") is not True:
            issues.append(_issue(
                "blocker", "context_evidence_required_flag_invalid",
                f"Required evidence {evidence_id} must declare required=true.",
                stage="evidence",
            ))
            continue
        requirements[evidence_id] = dict(item)
        seen_types.add(evidence_type)
    missing_feature_types = sorted(
        _feature_required_evidence_types(context, spec) - seen_types
    )
    if missing_feature_types:
        issues.append(_issue(
            "blocker", "context_feature_evidence_missing",
            "Production context does not require all evidence implied by the "
            f"selected mode/features: {', '.join(missing_feature_types)}.",
            stage="evidence",
        ))
    return requirements


def _canonical_payload_sha256(payload: Any) -> str:
    normalized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _extract_scene_contract_ids(source: Mapping[str, Any]) -> list[str]:
    raw = source.get("scene_contracts")
    if not isinstance(raw, list):
        raw = source.get("scenes")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for index, scene in enumerate(raw):
        if not isinstance(scene, Mapping):
            continue
        value = scene.get("scene_id", scene.get("id", f"scene-{index + 1}"))
        if _is_nonempty(value):
            ids.append(str(value))
    return ids


def _check_evidence(
    spec: Mapping[str, Any],
    context: Mapping[str, Any],
    artifact_sha256: str,
    additional_paths: Iterable[str | Path],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Validate realized evidence declarations and strict evidence envelopes."""
    grouped: dict[str, list[dict[str, Any]]] = {
        "before_execution": [],
        "before_final_render": [],
    }
    requirements = _context_evidence_requirements(context, spec, issues)
    raw_declarations = spec.get("evidence")
    if not isinstance(raw_declarations, list):
        issues.append(_issue(
            "blocker", "realized_evidence_invalid",
            "Quality spec evidence must be a list of realized envelope declarations.",
            stage="evidence",
        ))
        raw_declarations = []
    declarations: dict[str, dict[str, Any]] = {}
    declared_paths: set[str] = set()
    for index, item in enumerate(raw_declarations):
        if not isinstance(item, Mapping):
            issues.append(_issue(
                "blocker", "realized_evidence_declaration_invalid",
                f"Realized evidence declaration at index {index} must be an object.",
                stage="evidence",
            ))
            continue
        required_fields = (
            "id", "evidence_type", "stage", "schema", "path", "sha256", "required",
        )
        if not all(key in item and _is_nonempty(item.get(key)) for key in required_fields):
            issues.append(_issue(
                "blocker", "realized_evidence_declaration_incomplete",
                f"Realized evidence declaration at index {index} is incomplete.",
                stage="evidence", evidence=dict(item),
            ))
            continue
        evidence_id = str(item["id"])
        if evidence_id in declarations:
            issues.append(_issue(
                "blocker", "realized_evidence_id_duplicate",
                f"Duplicate realized evidence ID: {evidence_id}.", stage="evidence",
            ))
            continue
        if item.get("required") is not True:
            issues.append(_issue(
                "blocker", "realized_evidence_required_flag_invalid",
                f"Realized evidence {evidence_id} must declare required=true.",
                stage="evidence",
            ))
        if item.get("schema") != EVIDENCE_SCHEMA:
            issues.append(_issue(
                "blocker", "realized_evidence_schema_invalid",
                f"Evidence declaration {evidence_id} must use {EVIDENCE_SCHEMA!r}.",
                stage="evidence",
            ))
        path = Path(str(item["path"])).resolve()
        declared_paths.add(str(path))
        declarations[evidence_id] = {**dict(item), "_path": path}

    for value in additional_paths:
        path = str(Path(value).resolve())
        if path not in declared_paths:
            issues.append(_issue(
                "blocker", "undeclared_evidence_rejected",
                f"CLI evidence is not declared and fingerprinted in the quality spec: {path}",
                stage="evidence",
            ))

    features = spec.get("features") if isinstance(spec.get("features"), Mapping) else {}
    for declaration in declarations.values():
        evidence_type = str(declaration.get("evidence_type") or "")
        feature = EVIDENCE_FEATURE_SIGNALS.get(evidence_type)
        if feature and features.get(feature) is not True:
            issues.append(_issue(
                "blocker",
                "feature_evidence_contradiction",
                f"Evidence {evidence_type!r} proves feature {feature!r} was used, "
                "but the Quality spec declares it false.",
                stage="evidence",
            ))

    for evidence_id, requirement in requirements.items():
        if (
            requirement["evidence_type"] in SELF_PRODUCED_EVIDENCE_TYPES
            or requirement.get("required") is not True
        ):
            continue
        if evidence_id not in declarations:
            issues.append(_issue(
                "blocker", "required_evidence_missing",
                f"Required evidence has no realized envelope: {evidence_id}.",
                stage="evidence", evidence=requirement,
            ))

    timeline_hashes: set[str] = set()
    timeline_bound_results: list[tuple[str, dict[str, Any]]] = []
    approved_timeline_sha256: str | None = None
    scene_contract_ids: list[str] = []
    taste_selection_identity: dict[str, str] | None = None
    treatment_bindings: list[dict[str, Any]] = []
    for evidence_id, declaration in declarations.items():
        evidence_type = str(declaration.get("evidence_type"))
        evidence_stage = str(declaration.get("stage"))
        path = declaration["_path"]
        result = {
            "id": evidence_id,
            "evidence_type": evidence_type,
            "stage": evidence_stage,
            "path": str(path),
            "exists": path.is_file(),
            "passed": False,
        }
        target_group = (
            grouped["before_execution"]
            if evidence_stage == "before-execution"
            else grouped["before_final_render"]
        )
        target_group.append(result)
        if evidence_type not in KNOWN_EVIDENCE_TYPES:
            issues.append(_issue(
                "blocker", "realized_evidence_type_unknown",
                f"Unknown or self-produced evidence cannot be supplied as an envelope: "
                f"{evidence_type}.",
                stage="evidence",
            ))
            continue
        if evidence_stage not in EVIDENCE_STAGES:
            issues.append(_issue(
                "blocker", "realized_evidence_stage_invalid",
                f"Evidence {evidence_id} has invalid stage {evidence_stage!r}.",
                stage="evidence",
            ))
            continue
        requirement = requirements.get(evidence_id)
        if requirement is None:
            issues.append(_issue(
                "blocker", "undeclared_evidence_requirement",
                f"Evidence {evidence_id} was not required by production context.",
                stage="evidence",
            ))
            continue
        for field, observed in (
            ("evidence_type", evidence_type),
            ("stage", evidence_stage),
        ):
            if str(requirement.get(field)) != observed:
                issues.append(_issue(
                    "blocker", "evidence_requirement_mismatch",
                    f"Evidence {evidence_id} {field} does not match production context.",
                    stage="evidence",
                    evidence={"expected": requirement.get(field), "observed": observed},
                ))
        if not path.is_file():
            issues.append(_issue(
                "blocker", "required_evidence_missing",
                f"Evidence envelope does not exist: {path}", stage="evidence",
            ))
            continue
        observed_envelope_hash = _artifact_sha256(path)
        result["sha256"] = observed_envelope_hash
        if not _is_sha256(declaration.get("sha256")) or (
            observed_envelope_hash.lower() != str(declaration.get("sha256")).lower()
        ):
            issues.append(_issue(
                "blocker", "evidence_envelope_fingerprint_mismatch",
                f"Evidence envelope {evidence_id} changed after the quality spec was authored.",
                stage="evidence",
                evidence={"expected": declaration.get("sha256"),
                          "observed": observed_envelope_hash},
            ))
            continue
        try:
            envelope = _load_json(path)
        except QualityAuditError as exc:
            issues.append(_issue(
                "blocker", "evidence_envelope_invalid", str(exc), stage="evidence",
            ))
            continue
        envelope_schema_errors = _validate_local_schema(EVIDENCE_SCHEMA, envelope)
        if envelope_schema_errors:
            issues.append(_issue(
                "blocker", "evidence_envelope_schema_validation_failed",
                f"Evidence envelope {evidence_id} does not satisfy its JSON Schema.",
                stage="evidence", evidence={"errors": envelope_schema_errors[:50]},
            ))
            continue
        envelope_fields = (
            "schema", "evidence_id", "evidence_type", "stage", "producer",
            "producer_version", "status", "source_path", "source_sha256",
            "source_schema",
        )
        if not all(_is_nonempty(envelope.get(key)) for key in envelope_fields):
            issues.append(_issue(
                "blocker", "evidence_envelope_incomplete",
                f"Evidence envelope {evidence_id} is missing identity/provenance fields.",
                stage="evidence",
            ))
            continue
        identity_expected = {
            "schema": EVIDENCE_SCHEMA,
            "evidence_id": evidence_id,
            "evidence_type": evidence_type,
            "stage": evidence_stage,
        }
        identity_mismatch = {
            key: {"expected": expected, "observed": envelope.get(key)}
            for key, expected in identity_expected.items()
            if envelope.get(key) != expected
        }
        if identity_mismatch:
            issues.append(_issue(
                "blocker", "evidence_envelope_identity_mismatch",
                f"Evidence envelope identity does not match declaration {evidence_id}.",
                stage="evidence", evidence=identity_mismatch,
            ))
            continue
        if envelope.get("status") != "pass":
            issues.append(_issue(
                "blocker", "upstream_quality_gate_failed",
                f"Evidence {evidence_id} status is {envelope.get('status')!r}, not 'pass'.",
                stage="evidence",
            ))
            continue
        source_path = Path(str(envelope["source_path"])).resolve()
        expected_source_path = Path(str(requirement["expected_path"])).resolve()
        if source_path != expected_source_path:
            issues.append(_issue(
                "blocker", "evidence_source_path_mismatch",
                f"Evidence {evidence_id} wraps a different source than production context.",
                stage="evidence",
                evidence={"expected": str(expected_source_path), "observed": str(source_path)},
            ))
            continue
        if envelope.get("source_schema") != requirement.get("schema_id"):
            issues.append(_issue(
                "blocker", "evidence_source_schema_mismatch",
                f"Evidence {evidence_id} source schema does not match production context.",
                stage="evidence",
                evidence={"expected": requirement.get("schema_id"),
                          "observed": envelope.get("source_schema")},
            ))
            continue
        if not source_path.is_file():
            issues.append(_issue(
                "blocker", "evidence_source_missing",
                f"Evidence source does not exist: {source_path}", stage="evidence",
            ))
            continue
        observed_source_hash = _artifact_sha256(source_path)
        if not _is_sha256(envelope.get("source_sha256")) or (
            observed_source_hash.lower() != str(envelope.get("source_sha256")).lower()
        ):
            issues.append(_issue(
                "blocker", "evidence_source_fingerprint_mismatch",
                f"Wrapped evidence source changed: {source_path}",
                stage="evidence",
                evidence={"expected": envelope.get("source_sha256"),
                          "observed": observed_source_hash},
            ))
            continue

        artifact_binding = envelope.get("artifact_sha256")
        timeline_binding = envelope.get("timeline_sha256")
        if not _is_sha256(artifact_binding) and not _is_sha256(timeline_binding):
            issues.append(_issue(
                "blocker", "evidence_subject_binding_missing",
                f"Evidence {evidence_id} needs artifact_sha256 or timeline_sha256.",
                stage="evidence",
            ))
            continue
        if _is_sha256(artifact_binding) and str(artifact_binding).lower() != artifact_sha256.lower():
            issues.append(_issue(
                "blocker", "evidence_artifact_fingerprint_mismatch",
                f"Evidence {evidence_id} is bound to a different encoded artifact.",
                stage="evidence",
            ))
            continue
        if _is_sha256(timeline_binding):
            normalized_timeline_hash = str(timeline_binding).lower()
            timeline_hashes.add(normalized_timeline_hash)
            timeline_bound_results.append((normalized_timeline_hash, result))

        payload_present = "payload" in envelope and _is_nonempty(envelope.get("payload"))
        payload_hash = envelope.get("payload_sha256")
        if not payload_present and not _is_sha256(payload_hash):
            issues.append(_issue(
                "blocker", "evidence_payload_missing",
                f"Evidence {evidence_id} needs non-empty payload or payload_sha256.",
                stage="evidence",
            ))
            continue
        if payload_present:
            calculated_payload_hash = _canonical_payload_sha256(envelope["payload"])
            if payload_hash is not None and (
                not _is_sha256(payload_hash)
                or str(payload_hash).lower() != calculated_payload_hash
            ):
                issues.append(_issue(
                    "blocker", "evidence_payload_fingerprint_mismatch",
                    f"Evidence {evidence_id} payload fingerprint is invalid.",
                    stage="evidence",
                ))
                continue
            result["payload_sha256"] = calculated_payload_hash

        if evidence_type == "render_log":
            text = source_path.read_text(encoding="utf-8", errors="replace")
            matches = sorted({
                line.strip()
                for line in text.splitlines()
                if any(pattern.search(line) for pattern in ERROR_LOG_PATTERNS)
            })
            if matches:
                issues.append(_issue(
                    "blocker", "render_or_media_error_logged",
                    f"Render log contains {len(matches)} error-like line(s): {source_path}",
                    stage="render", evidence=matches[:20],
                ))
                continue
        elif evidence_type == "editorial_intent":
            try:
                scene_contract_ids.extend(_extract_scene_contract_ids(_load_json(source_path)))
            except QualityAuditError:
                # The strict source schema remains the adapter's responsibility;
                # no scene IDs means the human scene review will fail closed.
                pass
        elif evidence_type == "edl_approval":
            try:
                approval_source = _load_json(source_path)
            except QualityAuditError:
                approval_source = {}
            edl_reference = approval_source.get("edl")
            approval = approval_source.get("approval")
            context_reference = approval_source.get("production_context")
            edl_hash = (
                edl_reference.get("sha256")
                if isinstance(edl_reference, Mapping) else None
            )
            approved_hash = (
                approval.get("approved_edl_sha256")
                if isinstance(approval, Mapping) else None
            )
            timeline_fingerprint = (
                approval.get("timeline_fingerprint")
                if isinstance(approval, Mapping) else None
            )
            context_hash = (
                context_reference.get("sha256")
                if isinstance(context_reference, Mapping) else None
            )
            expected_context_hash = (
                spec.get("production_context", {}).get("sha256")
                if isinstance(spec.get("production_context"), Mapping) else None
            )
            if (
                approval_source.get("status") != "approved"
                or not _is_sha256(edl_hash)
                or approved_hash != edl_hash
                or not _is_sha256(timeline_fingerprint)
                or str(context_hash).lower() != str(expected_context_hash).lower()
            ):
                issues.append(_issue(
                    "blocker", "edl_approval_binding_invalid",
                    "EDL approval must be approved, bind the exact production context, "
                    "repeat the approved EDL SHA-256, and bind the approved "
                    "timeline fingerprint.",
                    stage="evidence",
                ))
                continue
            approved_timeline_sha256 = str(timeline_fingerprint).lower()
        elif evidence_type == "taste_selection":
            try:
                taste_source = _load_json(source_path)
                selection = taste_source.get("selection")
                selected_option_id = (
                    selection.get("selected_option_id")
                    if isinstance(selection, Mapping) else None
                )
            except QualityAuditError:
                selected_option_id = None
            if not _is_nonempty(selected_option_id):
                issues.append(_issue(
                    "blocker", "taste_selection_identity_missing",
                    "Taste-selection evidence does not name selection.selected_option_id.",
                    stage="evidence",
                ))
                continue
            taste_selection_identity = {
                "sha256": observed_source_hash,
                "selected_option_id": str(selected_option_id),
            }

        if evidence_type in TREATMENT_SENSITIVE_EVIDENCE_TYPES:
            taste_hash = envelope.get("taste_selection_sha256")
            option_id = envelope.get("selected_option_id")
            treatment_hash = envelope.get("treatment_sha256")
            if (
                not _is_sha256(taste_hash)
                or not _is_nonempty(option_id)
                or not _is_sha256(treatment_hash)
            ):
                issues.append(_issue(
                    "blocker", "treatment_evidence_binding_missing",
                    f"Evidence {evidence_id} must bind taste_selection_sha256, "
                    "selected_option_id, and treatment_sha256.",
                    stage="evidence",
                ))
                continue
            treatment_bindings.append({
                "evidence_id": evidence_id,
                "taste_selection_sha256": str(taste_hash).lower(),
                "selected_option_id": str(option_id),
                "treatment_sha256": str(treatment_hash).lower(),
                "_result": result,
            })

        result.update({
            "passed": True,
            "producer": envelope.get("producer"),
            "producer_version": envelope.get("producer_version"),
            "source_path": str(source_path),
            "source_sha256": observed_source_hash,
            "source_schema": envelope.get("source_schema"),
            "artifact_sha256": artifact_binding,
            "timeline_sha256": timeline_binding,
        })

    for binding in treatment_bindings:
        if taste_selection_identity is None:
            binding["_result"]["passed"] = False
            issues.append(_issue(
                "blocker", "treatment_taste_selection_missing",
                f"Treatment-sensitive evidence {binding['evidence_id']} has no "
                "validated taste-selection evidence.",
                stage="evidence",
            ))
            continue
        if (
            binding["taste_selection_sha256"] != taste_selection_identity["sha256"]
            or binding["selected_option_id"] != taste_selection_identity["selected_option_id"]
        ):
            binding["_result"]["passed"] = False
            issues.append(_issue(
                "blocker", "treatment_taste_selection_mismatch",
                f"Treatment-sensitive evidence {binding['evidence_id']} is bound to "
                "a different taste selection or option.",
                stage="evidence",
                evidence={
                    "expected": taste_selection_identity,
                    "observed": {
                        key: value for key, value in binding.items() if key != "_result"
                    },
                },
            ))
    if len(timeline_hashes) > 1:
        issues.append(_issue(
            "blocker", "evidence_timeline_fingerprint_conflict",
            "Evidence envelopes refer to more than one timeline fingerprint.",
            stage="evidence", evidence={"timeline_sha256": sorted(timeline_hashes)},
        ))
    if approved_timeline_sha256 is not None:
        mismatched_results = [
            result for timeline_hash, result in timeline_bound_results
            if timeline_hash != approved_timeline_sha256
        ]
        if mismatched_results:
            for result in mismatched_results:
                result["passed"] = False
            issues.append(_issue(
                "blocker", "evidence_approved_timeline_mismatch",
                "Timeline-bound evidence does not match the human-approved "
                "timeline_map + retimed_words fingerprint.",
                stage="evidence",
                evidence={
                    "approved_timeline_fingerprint": approved_timeline_sha256,
                    "mismatched_evidence_ids": sorted(
                        result["id"] for result in mismatched_results
                    ),
                },
            ))
    for values in grouped.values():
        values.sort(key=lambda item: (item["evidence_type"], item["id"]))
    return grouped, sorted(set(scene_contract_ids))


def _check_render_logs(paths: Iterable[str | Path],
                       issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for value in paths:
        path = Path(value).resolve()
        results.append({
            "path": str(path),
            "exists": path.exists(),
            "accepted": False,
        })
        issues.append(_issue(
            "blocker", "unwrapped_render_log_rejected",
            "Raw --render-log inputs are not trusted. Wrap the log in a declared, "
            "fingerprinted render_log evidence envelope.",
            stage="render", evidence={"path": str(path)},
        ))
    return results


def _sample_plan(duration_s: float, fps: float, scene_times: Sequence[float],
                 spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    frame = 1.0 / max(1.0, fps)
    last = max(0.0, duration_s - frame)
    samples: dict[float, set[str]] = {
        0.0: {"first-frame"},
        round(last, 3): {"last-frame"},
    }

    def add(time_s: float, reason: str) -> None:
        bounded = round(min(max(0.0, float(time_s)), last), 3)
        samples.setdefault(bounded, set()).add(reason)

    for boundary in scene_times:
        add(boundary - frame, "scene-boundary-before")
        add(boundary, "scene-boundary")
        add(boundary + frame, "scene-boundary-after")
    review_times = spec.get("review_times") or {}
    for key, values in review_times.items():
        for value in values or []:
            add(float(value), str(key))
    # Interior coverage never replaces authored cue times, but prevents a long
    # scene from being represented only by its endpoints.
    regular_interval = float((spec.get("thresholds") or {}).get(
        "maximum_uninspected_span_s", 5.0))
    cursor = regular_interval
    while cursor < last:
        add(cursor, "intermediate")
        cursor += regular_interval
    plan: list[dict[str, Any]] = []
    for time_s, reasons in sorted(samples.items()):
        sorted_reasons = sorted(reasons)
        identity = f"{time_s:.3f}|{'|'.join(sorted_reasons)}"
        point_id = "rp-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        plan.append({
            "id": point_id,
            "at_s": time_s,
            "reasons": sorted_reasons,
        })
    return plan


def _score_creative(review: Mapping[str, Any],
                    issues: list[dict[str, Any]]) -> dict[str, Any]:
    scores = review.get("creative_scores")
    if not isinstance(scores, Mapping):
        return {
            "status": "pending",
            "total": None,
            "threshold": 80,
            "category_floor": 3,
            "weights": CREATIVE_SCORE_WEIGHTS,
        }
    weighted_total = 0.0
    normalized: dict[str, float | None] = {}
    for key, weight in CREATIVE_SCORE_WEIGHTS.items():
        try:
            value = float(scores[key])
        except (KeyError, TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value) or value < 0 or value > 5:
            normalized[key] = None
            issues.append(_issue(
                "major", "creative_score_missing_or_invalid",
                f"Creative score {key!r} must be between 0 and 5.",
                stage="human-review",
            ))
            continue
        normalized[key] = round(value, 2)
        weighted_total += weight * value / 5.0
        if value < 3:
            issues.append(_issue(
                "major", "creative_category_below_floor",
                f"Creative category {key!r} scored {value:.1f}/5; floor is 3/5.",
                stage="human-review",
            ))
    total = round(weighted_total, 1)
    if total < 80:
        issues.append(_issue(
            "major", "creative_score_below_threshold",
            f"Creative quality score is {total}/100; delivery threshold is 80/100.",
            stage="human-review",
        ))
    return {
        "status": "pass" if total >= 80 and all(
            value is not None and value >= 3 for value in normalized.values()
        ) else "fail",
        "total": total,
        "threshold": 80,
        "category_floor": 3,
        "scores": normalized,
        "weights": CREATIVE_SCORE_WEIGHTS,
    }


def _score_universal_criteria(
    review: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    values = review.get("universal_criteria")
    normalized: dict[str, dict[str, Any]] = {}
    if not isinstance(values, Mapping):
        values = {}
    for criterion in UNIVERSAL_CRITERIA:
        item = values.get(criterion)
        if not isinstance(item, Mapping):
            item = {}
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            score = math.nan
        rationale = str(item.get("notes") or "").strip()
        if not math.isfinite(score) or score < 0 or score > 5:
            normalized[criterion] = {"score": None, "notes": rationale}
            issues.append(_issue(
                "major", "universal_criterion_missing_or_invalid",
                f"Universal criterion {criterion!r} must be scored from 0 to 5.",
                stage="human-review",
            ))
            continue
        normalized[criterion] = {"score": round(score, 2), "notes": rationale}
        if not rationale:
            issues.append(_issue(
                "major", "universal_criterion_rationale_missing",
                f"Universal criterion {criterion!r} requires an artifact-specific rationale.",
                stage="human-review",
            ))
        if score < UNIVERSAL_CRITERIA_FLOOR:
            issues.append(_issue(
                "major", "universal_criterion_below_floor",
                f"Universal criterion {criterion!r} scored {score:.1f}/5; "
                f"floor is {UNIVERSAL_CRITERIA_FLOOR}/5.",
                stage="human-review",
            ))
    scores = [item["score"] for item in normalized.values() if item["score"] is not None]
    passed = (
        len(scores) == len(UNIVERSAL_CRITERIA)
        and all(value >= UNIVERSAL_CRITERIA_FLOOR for value in scores)
        and all(item["notes"] for item in normalized.values())
    )
    return {
        "status": "pass" if passed else "fail",
        "floor": UNIVERSAL_CRITERIA_FLOOR,
        "average": round(sum(scores) / len(scores), 2) if scores else None,
        "criteria": normalized,
    }


def _scene_contract_review_required(context: Mapping[str, Any]) -> bool:
    mode = str(context.get("operating_mode") or "").strip().lower()
    artifact_type = str(context.get("artifact_type") or "").strip().lower()
    return mode in {"standard", "flagship"} and artifact_type in {
        "video_edit", "generated_video", "motion_graphic", "hybrid",
    }


def _required_review_checks(context: Mapping[str, Any]) -> dict[str, str]:
    checks = dict(REQUIRED_REVIEW_CHECKS)
    if _scene_contract_review_required(context):
        checks["scene_contracts"] = "major"
    return checks


def _check_review_points(
    review: Mapping[str, Any],
    sample_plan: Sequence[Mapping[str, Any]],
    accepted_minor_codes: set[str],
    issues: list[dict[str, Any]],
) -> bool:
    raw = review.get("review_points")
    if not isinstance(raw, list):
        raw = []
    point_map: dict[str, Mapping[str, Any]] = {}
    duplicates: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or not _is_nonempty(item.get("id")):
            continue
        point_id = str(item["id"])
        if point_id in point_map:
            duplicates.add(point_id)
        point_map[point_id] = item
    for point_id in sorted(duplicates):
        issues.append(_issue(
            "major", "review_point_duplicate",
            f"Generated review point has multiple dispositions: {point_id}.",
            stage="human-review",
        ))
    expected_ids = {str(item["id"]) for item in sample_plan}
    unknown = sorted(set(point_map) - expected_ids)
    if unknown:
        issues.append(_issue(
            "major", "review_point_unknown",
            "Human review contains points not generated for this artifact/spec.",
            stage="human-review", evidence={"unknown_ids": unknown},
        ))
    disposed = True
    for expected in sample_plan:
        point_id = str(expected["id"])
        item = point_map.get(point_id)
        if item is None:
            disposed = False
            issues.append(_issue(
                "major", "review_point_missing",
                f"Generated review point has no disposition: {point_id}.",
                stage="human-review", evidence=dict(expected),
            ))
            continue
        try:
            at_matches = abs(float(item.get("at_s")) - float(expected["at_s"])) <= 0.0005
        except (TypeError, ValueError):
            at_matches = False
        reasons_match = sorted(item.get("reasons") or []) == sorted(expected["reasons"])
        if not at_matches or not reasons_match:
            disposed = False
            issues.append(_issue(
                "major", "review_point_identity_mismatch",
                f"Review point {point_id} time/reasons do not match the generated plan.",
                stage="human-review",
            ))
            continue
        status = str(item.get("status") or "").lower()
        notes = str(item.get("notes") or "").strip()
        if status == "pass":
            continue
        if status == "na" and notes:
            continue
        if status == "accepted-minor":
            code = str(item.get("issue_code") or "")
            if code and code in accepted_minor_codes and notes:
                issues.append(_issue(
                    "minor", code,
                    f"Reviewer accepted minor issue at {point_id}: {notes}",
                    stage="human-review",
                ))
                continue
        disposed = False
        issues.append(_issue(
            "major", "review_point_not_disposed",
            f"Review point {point_id} requires pass, explained na, or accepted-minor.",
            stage="human-review",
        ))
    return disposed and not duplicates and not unknown


def _check_scene_contracts(
    review: Mapping[str, Any],
    context: Mapping[str, Any],
    expected_scene_ids: Sequence[str],
    issues: list[dict[str, Any]],
) -> bool:
    if not _scene_contract_review_required(context):
        return True
    if not expected_scene_ids:
        issues.append(_issue(
            "major", "scene_contract_source_missing",
            "Standard/Flagship video review requires scene IDs from editorial-intent evidence.",
            stage="human-review",
        ))
        return False
    raw = review.get("scene_contracts")
    if not isinstance(raw, list):
        raw = []
    scene_map = {
        str(item.get("scene_id")): item
        for item in raw
        if isinstance(item, Mapping) and _is_nonempty(item.get("scene_id"))
    }
    required_fields = (
        "entering_state", "promised_change", "delivered_change", "proof",
        "exit_state", "failure_condition",
    )
    passed = True
    for scene_id in expected_scene_ids:
        item = scene_map.get(scene_id)
        if item is None:
            passed = False
            issues.append(_issue(
                "major", "scene_contract_review_missing",
                f"Scene contract has no human disposition: {scene_id}.",
                stage="human-review",
            ))
            continue
        missing = [key for key in required_fields if not _is_nonempty(item.get(key))]
        if missing or item.get("status") != "pass":
            passed = False
            issues.append(_issue(
                "major", "scene_contract_review_failed",
                f"Scene {scene_id} lacks a complete passing meaning/change review.",
                stage="human-review",
                evidence={"missing_fields": missing, "status": item.get("status")},
            ))
    unknown = sorted(set(scene_map) - set(expected_scene_ids))
    if unknown:
        passed = False
        issues.append(_issue(
            "major", "scene_contract_review_unknown",
            "Scene review contains IDs not present in editorial-intent evidence.",
            stage="human-review", evidence={"unknown_scene_ids": unknown},
        ))
    return passed


def _check_human_review(
    review: Mapping[str, Any] | None,
    artifact_sha256: str,
    *,
    context: Mapping[str, Any],
    sample_plan: Sequence[Mapping[str, Any]],
    expected_scene_ids: Sequence[str],
    audio_present: bool,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    required_checks = _required_review_checks(context)
    if review is None:
        return {
            "status": "pending",
            "schema": REVIEW_SCHEMA,
            "required_checks": sorted(required_checks),
            "content_accuracy_verified": False,
            "complete_playback_watched": False,
            "review_points_disposed": False,
            "scene_contracts_reviewed": False,
            "universal_criteria": {
                "status": "pending", "floor": UNIVERSAL_CRITERIA_FLOOR,
                "average": None, "criteria": {},
            },
            "creative_score": {
                "status": "pending", "total": None, "threshold": 80,
                "category_floor": 3, "weights": CREATIVE_SCORE_WEIGHTS,
            },
        }
    review_schema_errors = _validate_local_schema(REVIEW_SCHEMA, review)
    if review_schema_errors:
        issues.append(_issue(
            "blocker", "human_review_schema_validation_failed",
            "Human review does not satisfy the complete v2 JSON Schema.",
            stage="human-review", evidence={"errors": review_schema_errors[:50]},
        ))
    if review.get("schema") != REVIEW_SCHEMA:
        issues.append(_issue(
            "blocker", "human_review_schema_invalid",
            f"Review schema must be {REVIEW_SCHEMA!r}.", stage="human-review",
        ))
    review_hash = review.get("artifact_sha256")
    if review_hash != artifact_sha256:
        issues.append(_issue(
            "blocker", "human_review_artifact_mismatch",
            "Human review was not completed against this exact encoded artifact.",
            stage="human-review",
            evidence={"review_hash": review_hash, "artifact_hash": artifact_sha256},
        ))
    if not _is_nonempty(review.get("reviewer")) or not _is_nonempty(review.get("reviewed_at")):
        issues.append(_issue(
            "blocker", "human_review_identity_missing",
            "Human review requires reviewer and reviewed_at.",
            stage="human-review",
        ))

    checks = review.get("checks")
    check_map: dict[str, Mapping[str, Any]] = {}
    if isinstance(checks, list):
        check_map = {
            str(item.get("id")): item for item in checks
            if isinstance(item, Mapping) and item.get("id")
        }
    accepted_minor_codes = set(review.get("accepted_minor_issue_codes") or [])
    for check_id, severity in required_checks.items():
        item = check_map.get(check_id)
        if item is None:
            issues.append(_issue(
                severity, "human_review_check_missing",
                f"Required review check is missing: {check_id}.",
                stage="human-review", evidence={"check_id": check_id},
            ))
            continue
        status = str(item.get("status") or "").lower()
        notes = str(item.get("notes") or "").strip()
        if status == "pass":
            continue
        if status == "na" and notes:
            continue
        if status == "accepted-minor":
            code = str(item.get("issue_code") or "")
            if code and code in accepted_minor_codes:
                issues.append(_issue(
                    "minor", code,
                    f"Reviewer accepted minor issue in {check_id}: {notes}",
                    stage="human-review",
                ))
                continue
        issues.append(_issue(
            severity, f"human_review_{check_id}_failed",
            f"Human review check {check_id!r} did not pass: {notes or status or 'no status'}.",
            stage="human-review",
        ))

    accuracy = review.get("content_accuracy") or {}
    content_verified = bool(accuracy.get("verified"))
    unsupported = list(accuracy.get("unsupported_or_unverified") or [])
    source_ids = set(
        source_id for source_id in (
            _source_identity(source)
            for source in context.get("sources", [])
            if isinstance(source, Mapping)
        ) if source_id
    )
    checked_source_ids = {
        str(item) for item in (accuracy.get("sources_checked") or [])
        if _is_nonempty(item)
    }
    missing_source_ids = sorted(source_ids - checked_source_ids)
    if not content_verified or unsupported or missing_source_ids:
        issues.append(_issue(
            "blocker", "content_accuracy_unverified",
            "Names, claims, numbers, labels, captions, and represented interfaces "
            "must be verified against every named production-context source.",
            stage="human-review", evidence={"verified": content_verified,
                                            "unsupported_or_unverified": unsupported,
                                            "missing_source_ids": missing_source_ids},
        ))
    playback = review.get("complete_playback") or {}
    playback_keys = ["watched_from_start_to_finish", "normal_speed"]
    if audio_present:
        playback_keys.append("audio_enabled")
    playback_watched = all(bool(playback.get(key)) for key in playback_keys)
    target_device = str(playback.get("target_device") or "").strip()
    playback_watched = playback_watched and bool(target_device)
    if not playback_watched:
        issues.append(_issue(
            "blocker", "complete_playback_not_documented",
            "The exact export must be watched start-to-finish at normal speed on a "
            "named target device, with audio when present.",
            stage="human-review",
        ))

    review_points_disposed = _check_review_points(
        review, sample_plan, accepted_minor_codes, issues,
    )
    scene_contracts_reviewed = _check_scene_contracts(
        review, context, expected_scene_ids, issues,
    )
    universal_criteria = _score_universal_criteria(review, issues)
    creative_score = _score_creative(review, issues)
    has_blocking_review_issue = any(
        item["stage"] == "human-review" and item["severity"] in BLOCKING_SEVERITIES
        for item in issues
    )
    return {
        "status": "fail" if has_blocking_review_issue else "pass",
        "schema": REVIEW_SCHEMA,
        "reviewer": review.get("reviewer"),
        "reviewed_at": review.get("reviewed_at"),
        "content_accuracy_verified": (
            content_verified and not unsupported and not missing_source_ids
        ),
        "complete_playback_watched": playback_watched,
        "review_points_disposed": review_points_disposed,
        "scene_contracts_reviewed": scene_contracts_reviewed,
        "accepted_minor_issue_codes": sorted(accepted_minor_codes),
        "universal_criteria": universal_criteria,
        "creative_score": creative_score,
    }


def _summary(issues: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for item in issues:
        severity = str(item.get("severity"))
        if severity in counts:
            counts[severity] += 1
    return {
        "issue_counts": counts,
        "blockers_or_majors": counts["blocker"] + counts["major"],
        "mandatory_failures": sum(
            1 for item in issues
            if item.get("mandatory") and item.get("severity") in BLOCKING_SEVERITIES
        ),
    }


def run_quality_audit(
    artifact: str | Path,
    *,
    spec: Mapping[str, Any] | None = None,
    compare_to: str | Path | None = None,
    review: Mapping[str, Any] | None = None,
    evidence_paths: Iterable[str | Path] = (),
    render_logs: Iterable[str | Path] = (),
    scan_scenes: bool = True,
) -> dict[str, Any]:
    """Audit one encoded video and return a deterministic JSON-ready report.

    ``generated_at`` is intentionally omitted: the report fingerprint must not
    change because a clock advanced.  A human review may record its own date.
    """
    artifact_path = Path(artifact).resolve()
    spec_data = dict(spec or {})
    issues: list[dict[str, Any]] = []
    if not artifact_path.is_file():
        raise QualityAuditError(f"video does not exist: {artifact_path}")
    if not runtime.tool("ffmpeg", required=False) or not runtime.tool("ffprobe", required=False):
        raise QualityAuditError("ffmpeg and ffprobe are required")
    if not spec_data:
        issues.append(_issue(
            "blocker", "quality_spec_missing",
            "A complete Quality v2 spec and immutable production context are required.",
            stage="requirements",
        ))
    _validate_quality_spec(spec_data, issues)
    production_context, production_context_summary = _load_production_context(
        spec_data, issues,
    )
    determinism_required, determinism_waiver = _validate_determinism_contract(
        spec_data, issues,
    )

    artifact_hash = _artifact_sha256(artifact_path)
    try:
        probe = _probe(artifact_path)
    except QualityAuditError as exc:
        return {
            "schema": SCHEMA,
            "artifact": {"path": str(artifact_path), "sha256": artifact_hash},
            "spec": spec_data,
            "issues": [_issue("blocker", "artifact_unreadable", str(exc))],
            "summary": {
                "issue_counts": {"suggestion": 0, "minor": 0, "major": 0, "blocker": 1},
                "blockers_or_majors": 1,
                "mandatory_failures": 1,
            },
            "automated_gate_passed": False,
            "ready": False,
        }

    observed = _check_delivery(probe, spec_data, issues)
    decode = _decode_integrity(artifact_path)
    if not decode["passed"]:
        issues.append(_issue(
            "blocker", "decode_integrity_failed",
            "FFmpeg could not decode the complete encoded artifact without errors.",
            evidence=decode["errors"],
        ))

    video = _stream(probe, "video")
    audio = _stream(probe, "audio")
    avg_fps = _fraction((video or {}).get("avg_frame_rate")) or 30.0
    duration_s = _duration(probe)

    black_intervals = _scan_black(artifact_path)
    freeze_intervals = _scan_freeze(artifact_path, duration_s)
    silence_intervals = _scan_silence(artifact_path, duration_s) if audio else []
    _check_scan_intervals("black", black_intervals, spec_data, issues)
    _check_scan_intervals("freeze", freeze_intervals, spec_data, issues)
    _check_scan_intervals("silence", silence_intervals, spec_data, issues)

    try:
        video_duration_s = float((video or {}).get("duration") or duration_s)
    except (TypeError, ValueError):
        video_duration_s = duration_s
    endpoint_times = [
        0.0,
        max(0.0, min(duration_s, video_duration_s) - 1.0 / max(1.0, avg_fps)),
    ]
    endpoint_metrics = [_frame_metrics(artifact_path, value) for value in endpoint_times]
    for label, metrics in zip(("first", "last"), endpoint_metrics):
        if not metrics.get("readable"):
            issues.append(_issue(
                "blocker", f"{label}_frame_unreadable",
                f"Could not decode the {label} delivery frame.",
            ))
        elif metrics.get("near_black_blank") or metrics.get("near_uniform"):
            allowed = (spec_data.get("intentional_endpoints") or {}).get(label, False)
            if not allowed:
                issues.append(_issue(
                    "major", f"{label}_frame_appears_blank",
                    f"The {label} frame is nearly uniform/blank and is not acknowledged "
                    "as intentional.",
                    evidence=metrics,
                ))

    loudness = _audio_loudness(artifact_path) if audio else None
    audio_spec = dict(spec_data.get("audio") or {})
    if loudness and loudness.get("measured"):
        true_peak = loudness.get("true_peak_dbtp")
        if true_peak is not None and true_peak > float(audio_spec.get("maximum_true_peak_dbtp", -0.1)):
            issues.append(_issue(
                "blocker", "audio_true_peak_exceeded",
                f"Measured true peak is {true_peak:.2f} dBTP.",
                stage="audio", evidence=loudness,
            ))
        target = audio_spec.get("target_lufs")
        if target is not None and loudness.get("integrated_lufs") is not None:
            tolerance = float(audio_spec.get("lufs_tolerance", 1.5))
            delta = abs(float(loudness["integrated_lufs"]) - float(target))
            if delta > tolerance:
                issues.append(_issue(
                    "major", "integrated_loudness_out_of_range",
                    f"Integrated loudness is {loudness['integrated_lufs']:.2f} LUFS; "
                    f"target is {target}±{tolerance} LU.",
                    stage="audio", evidence=loudness,
                ))
        maximum_lra = audio_spec.get("maximum_loudness_range_lu")
        if maximum_lra is not None and loudness.get("loudness_range_lu") is not None:
            if float(loudness["loudness_range_lu"]) > float(maximum_lra):
                issues.append(_issue(
                    "major", "loudness_range_exceeded",
                    f"Loudness range is {loudness['loudness_range_lu']:.2f} LU; "
                    f"maximum is {maximum_lra} LU.",
                    stage="audio", evidence=loudness,
                ))

    fingerprints = {
        "video_decoded_sha256": _decoded_fingerprint(artifact_path, "0:v:0"),
        "audio_decoded_sha256": _decoded_fingerprint(artifact_path, "0:a:0") if audio else None,
    }
    repeatability = {
        "status": "not-compared",
        "comparison_artifact": None,
        "video_match": None,
        "audio_match": None,
        "determinism_required": determinism_required,
        "waiver": determinism_waiver,
    }
    if compare_to is not None:
        comparison_path = Path(compare_to).resolve()
        if not comparison_path.is_file():
            issues.append(_issue(
                "blocker", "determinism_comparison_missing",
                f"Comparison render does not exist: {comparison_path}",
                stage="determinism",
            ))
        else:
            comparison_probe = _probe(comparison_path)
            comparison_audio = _stream(comparison_probe, "audio")
            comparison_fingerprints = {
                "video_decoded_sha256": _decoded_fingerprint(comparison_path, "0:v:0"),
                "audio_decoded_sha256": (
                    _decoded_fingerprint(comparison_path, "0:a:0")
                    if comparison_audio else None
                ),
            }
            video_match = fingerprints["video_decoded_sha256"] == (
                comparison_fingerprints["video_decoded_sha256"]
            )
            audio_match = fingerprints["audio_decoded_sha256"] == (
                comparison_fingerprints["audio_decoded_sha256"]
            )
            repeatability = {
                "status": "pass" if video_match and audio_match else "fail",
                "comparison_artifact": str(comparison_path),
                "comparison_artifact_sha256": _artifact_sha256(comparison_path),
                "video_match": video_match,
                "audio_match": audio_match,
                "comparison_fingerprints": comparison_fingerprints,
                "determinism_required": determinism_required,
                "waiver": determinism_waiver,
            }
            if not video_match or not audio_match:
                issues.append(_issue(
                    "blocker", "repeat_render_mismatch",
                    "Decoded video/audio fingerprints differ between repeated renders.",
                    stage="determinism", evidence=repeatability,
                ))
    elif determinism_required:
        issues.append(_issue(
            "blocker", "repeat_render_not_supplied",
            "A second independent render is required to verify deterministic decoded "
            "frames and audio.",
            stage="determinism",
        ))
    elif determinism_waiver is not None:
        repeatability["status"] = "waived"

    scene_threshold = float((spec_data.get("thresholds") or {}).get(
        "scene_detection_threshold", 0.22))
    scene_times = _scan_scenes(artifact_path, scene_threshold) if scan_scenes else []
    sample_plan = _sample_plan(duration_s, avg_fps, scene_times, spec_data)
    upstream_evidence, scene_contract_ids = _check_evidence(
        spec_data, production_context, artifact_hash, evidence_paths, issues,
    )
    log_evidence = _check_render_logs(render_logs, issues)
    human_review = _check_human_review(
        review,
        artifact_hash,
        context=production_context,
        sample_plan=sample_plan,
        expected_scene_ids=scene_contract_ids,
        audio_present=audio is not None,
        issues=issues,
    )
    summary = _summary(issues)
    automated_blocking_issues = [
        item for item in issues
        if item["stage"] != "human-review"
        and item["severity"] in BLOCKING_SEVERITIES
        and item.get("mandatory", True)
    ]
    automated_gate_passed = (
        decode["passed"]
        and not automated_blocking_issues
    )
    unaccepted_minors = [
        item for item in issues
        if item["severity"] == "minor"
        and item["code"] not in set(human_review.get("accepted_minor_issue_codes") or [])
    ]
    ready = (
        automated_gate_passed
        and human_review.get("status") == "pass"
        and human_review.get("content_accuracy_verified")
        and human_review.get("complete_playback_watched")
        and human_review.get("review_points_disposed")
        and human_review.get("scene_contracts_reviewed")
        and human_review.get("universal_criteria", {}).get("status") == "pass"
        and human_review.get("creative_score", {}).get("status") == "pass"
        and not any(item["severity"] in BLOCKING_SEVERITIES for item in issues)
        and not unaccepted_minors
    )
    return {
        "schema": SCHEMA,
        "artifact": {
            "path": str(artifact_path),
            "sha256": artifact_hash,
            "bytes": artifact_path.stat().st_size,
        },
        "spec": spec_data,
        "production_context": production_context_summary,
        "observed_delivery": observed,
        "decode_integrity": decode,
        "encoded_fingerprints": fingerprints,
        "repeatability": repeatability,
        "scans": {
            "black_intervals": black_intervals,
            "freeze_intervals": freeze_intervals,
            "silence_intervals": silence_intervals,
            "scene_threshold": scene_threshold,
            "scene_boundaries_s": scene_times,
            "endpoint_frame_metrics": endpoint_metrics,
            "audio_loudness": loudness,
        },
        "review_sample_plan": sample_plan,
        "upstream_evidence": upstream_evidence,
        "render_logs": log_evidence,
        "human_review": human_review,
        "issues": sorted(
            issues,
            key=lambda item: (
                -SEVERITY_ORDER[item["severity"]],
                item["stage"], item["code"], item["message"],
            ),
        ),
        "summary": summary,
        "automated_gate_passed": automated_gate_passed,
        "ready": ready,
    }


def _dump(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit an encoded video against the ARETE delivery and review contract."
    )
    parser.add_argument("artifact", help="encoded video to inspect")
    parser.add_argument("--spec", help="required arete-video-quality-spec/v2 JSON")
    parser.add_argument("--compare-to", help="second independently rendered artifact")
    parser.add_argument("--review", help="arete-human-video-review/v2 JSON")
    parser.add_argument("--evidence", action="append", default=[],
                        help="declared evidence-envelope path cross-check; repeatable")
    parser.add_argument("--render-log", action="append", default=[],
                        help="deprecated raw input; always rejected (use render_log envelope)")
    parser.add_argument("--output", help="write report JSON here")
    parser.add_argument("--no-scene-scan", action="store_true",
                        help="skip automatic scene-boundary discovery")
    parser.add_argument("--require-ready", action="store_true",
                        help="exit non-zero until human review makes ready=true")
    parser.add_argument("--print-review-template", action="store_true",
                        help="print a human-review template bound to this artifact")
    return parser


def review_template(
    artifact: str | Path,
    spec: Mapping[str, Any],
    *,
    scan_scenes: bool = True,
) -> dict[str, Any]:
    path = Path(artifact).resolve()
    if not path.is_file():
        raise QualityAuditError(f"video does not exist: {path}")
    if not runtime.tool("ffmpeg", required=False) or not runtime.tool("ffprobe", required=False):
        raise QualityAuditError("ffmpeg and ffprobe are required")
    spec_data = dict(spec)
    issues: list[dict[str, Any]] = []
    _validate_quality_spec(spec_data, issues)
    context, _ = _load_production_context(spec_data, issues)
    _validate_determinism_contract(spec_data, issues)
    artifact_hash = _artifact_sha256(path)
    _, scene_contract_ids = _check_evidence(
        spec_data, context, artifact_hash, (), issues,
    )
    blocking = [
        item for item in issues
        if item["severity"] in BLOCKING_SEVERITIES and item.get("mandatory", True)
    ]
    if blocking:
        details = "; ".join(f"{item['code']}: {item['message']}" for item in blocking)
        raise QualityAuditError(
            "cannot generate a trustworthy review template from invalid inputs: " + details
        )
    probe = _probe(path)
    video = _stream(probe, "video")
    avg_fps = _fraction((video or {}).get("avg_frame_rate")) or 30.0
    duration_s = _duration(probe)
    threshold = float((spec_data.get("thresholds") or {}).get(
        "scene_detection_threshold", 0.22,
    ))
    scene_times = _scan_scenes(path, threshold) if scan_scenes else []
    sample_plan = _sample_plan(duration_s, avg_fps, scene_times, spec_data)
    required_checks = _required_review_checks(context)
    source_ids = sorted(
        source_id for source_id in (
            _source_identity(source)
            for source in context.get("sources", [])
            if isinstance(source, Mapping)
        ) if source_id
    )
    return {
        "schema": REVIEW_SCHEMA,
        "artifact_sha256": artifact_hash,
        "reviewer": "",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "complete_playback": {
            "watched_from_start_to_finish": False,
            "normal_speed": False,
            "audio_enabled": False,
            "target_device": "",
        },
        "content_accuracy": {
            "verified": False,
            "required_source_ids": source_ids,
            "sources_checked": [],
            "unsupported_or_unverified": [],
        },
        "checks": [
            {"id": check_id, "status": "pending", "notes": ""}
            for check_id in required_checks
        ],
        "review_points": [
            {
                "id": item["id"],
                "at_s": item["at_s"],
                "reasons": item["reasons"],
                "status": "pending",
                "notes": "",
            }
            for item in sample_plan
        ],
        "scene_contracts": [
            {
                "scene_id": scene_id,
                "entering_state": "",
                "promised_change": "",
                "delivered_change": "",
                "proof": "",
                "exit_state": "",
                "failure_condition": "",
                "status": "pending",
                "notes": "",
            }
            for scene_id in scene_contract_ids
        ],
        "universal_criteria": {
            key: {"score": None, "notes": ""}
            for key in UNIVERSAL_CRITERIA
        },
        "creative_scores": {key: None for key in CREATIVE_SCORE_WEIGHTS},
        "accepted_minor_issue_codes": [],
        "notes": "",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    runtime.guard_args(args, ("output",))
    try:
        spec = _load_json(args.spec) if args.spec else {}
        if args.print_review_template:
            if not args.spec:
                raise QualityAuditError("--spec is required for a review template")
            print(_dump(review_template(
                args.artifact,
                spec,
                scan_scenes=not args.no_scene_scan,
            )), end="")
            return 0
        review = _load_json(args.review) if args.review else None
        report = run_quality_audit(
            args.artifact,
            spec=spec,
            compare_to=args.compare_to,
            review=review,
            evidence_paths=args.evidence,
            render_logs=args.render_log,
            scan_scenes=not args.no_scene_scan,
        )
    except QualityAuditError as exc:
        print(f"quality audit error: {exc}", file=sys.stderr)
        return 2
    payload = _dump(report)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"wrote: {output}")
    else:
        print(payload, end="")
    if args.require_ready:
        return 0 if report["ready"] else 1
    return 0 if report["automated_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

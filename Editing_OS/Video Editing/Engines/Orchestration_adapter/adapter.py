"""Fail-closed orchestration adapter for the ARETE Editing OS.

The adapter is deliberately owned code.  It sits in front of third-party
orchestrators and refuses to translate "the pipeline ran" into "the artifact
is publishable".  Publication authority remains the Quality Engine report for
the exact encoded artifact.
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
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_SCHEMA = "arete-evidence-envelope/v1"
QUALITY_REPORT_SCHEMA = "arete-video-quality-report/v2"
PRODUCTION_CONTEXT_KIND = "production-context"
PRODUCTION_CONTEXT_VERSION = "1.0.0"

GOVERNING_DOCUMENTS = {
    "master_prompt": "Skills/MASTER_PROMPT.md",
    "taste_profile": "Skills/TASTE_PROFILE.md",
    "tool_routing": "Skills/TOOL_ROUTING.md",
    "quality_standard": "Skills/QUALITY_STANDARD.md",
    "editing_handbook": (
        "Skills/Video editing handbook/Elite_AI_Video_Editing_Workflow.md"
    ),
}

CONTRACT_KINDS = {
    "production-context",
    "editorial-intent",
    "taste-selection",
    "edl-approval",
    "short-form-experiment",
    "post-publish-learning",
    "audio-plan",
}

EVIDENCE_TYPES = {
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
    "quality_report",
    "artifact_bound_human_review",
    "short_form_experiment",
    "post_publish_learning",
}

STAGE_ORDER = {"before-execution": 0, "before-final-render": 1}
FORCED_ALIGNMENT_METHODS = {
    "whisperx",
    "whisperx-forced",
    "phoneme-forced-alignment",
}
TREATMENT_SENSITIVE_EVIDENCE_TYPES = {
    "caption_qa",
    "graphics_qa",
    "color_approval",
    "audio_qa",
}
CONTRACT_EVIDENCE = {
    "editorial_intent": (
        "editorial-intent",
        "https://arete.local/editing-os/contracts/editorial-intent/v1",
    ),
    "taste_selection": (
        "taste-selection",
        "https://arete.local/editing-os/contracts/taste-selection/v1",
    ),
    "edl_approval": (
        "edl-approval",
        "https://arete.local/editing-os/contracts/edl-approval/v1",
    ),
    "audio_plan": (
        "audio-plan",
        "https://arete.local/editing-os/contracts/audio-plan/v1",
    ),
    "short_form_experiment": (
        "short-form-experiment",
        "https://arete.local/editing-os/contracts/short-form-experiment/v1",
    ),
    "post_publish_learning": (
        "post-publish-learning",
        "https://arete.local/editing-os/contracts/post-publish-learning/v1",
    ),
}

_CONTRACTS_API: Any | None = None
_QUALITY_API: Any | None = None


class AdapterError(RuntimeError):
    """A fail-closed orchestration error suitable for CLI display."""


def _editing_os_root() -> Path:
    # adapter.py -> Orchestration_adapter -> Engines -> Video Editing -> Editing_OS
    return runtime.root() / "Editing_OS"


def _load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read JSON {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"JSON root must be an object: {source}")
    return value


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output = Path(path).resolve()
    runtime.output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _sha256_file(path: str | Path) -> str:
    source = Path(path).resolve()
    if not source.is_file():
        raise AdapterError(f"required artifact does not exist: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _resolve_reference(path: str, base_dir: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve()).casefold() == str(right.resolve()).casefold()


def _resolve_governing_path(value: str, editing_os_root: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    parts = candidate.parts
    if parts and parts[0].casefold() == editing_os_root.name.casefold():
        return (editing_os_root.parent / candidate).resolve()
    return (editing_os_root / candidate).resolve()


def _contracts_module() -> Any:
    global _CONTRACTS_API
    if _CONTRACTS_API is not None:
        return _CONTRACTS_API
    module_path = _editing_os_root() / "Video Editing" / "Contracts" / "validate.py"
    if not module_path.is_file():
        raise AdapterError(
            "Contracts/validate.py is required; the adapter will not fall back to "
            "ad-hoc contract validation"
        )
    spec = importlib.util.spec_from_file_location("arete_contract_validation", module_path)
    if spec is None or spec.loader is None:
        raise AdapterError(f"cannot load contract validator: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "validate_document", None)):
        raise AdapterError(
            "Contracts/validate.py must expose validate_document(kind, payload)"
        )
    _CONTRACTS_API = module
    return module


def validate_contract(kind: str, payload: Mapping[str, Any]) -> None:
    """Validate through the single Contracts API and normalize its failures."""
    if kind not in CONTRACT_KINDS:
        raise AdapterError(f"unknown contract kind: {kind!r}")
    try:
        errors = _contracts_module().validate_document(kind, payload)
    except Exception as exc:  # the API boundary must never become a bypass
        raise AdapterError(f"{kind} validation could not run: {exc}") from exc
    if not isinstance(errors, list):
        raise AdapterError(
            f"{kind} validator returned {type(errors).__name__}; expected a list"
        )
    if errors:
        rendered = "; ".join(
            f"{item.get('path', '$')}: {item.get('message', 'invalid')}"
            if isinstance(item, Mapping)
            else str(item)
            for item in errors[:20]
        )
        raise AdapterError(f"{kind} contract is invalid: {rendered}")


def verify_governing_documents(
    context: Mapping[str, Any],
    *,
    editing_os_root: str | Path | None = None,
) -> list[dict[str, str]]:
    """Resolve and compare the five live governing documents.

    Paths are not user-selectable.  A context that points at a copied,
    historical, or alternate authority fails even when its copied bytes happen
    to match.
    """
    root = Path(editing_os_root or _editing_os_root()).resolve()
    declared = context.get("governing_documents")
    if not isinstance(declared, list) or len(declared) != len(GOVERNING_DOCUMENTS):
        raise AdapterError("production context must declare exactly five governing documents")
    by_role: dict[str, Mapping[str, Any]] = {}
    for item in declared:
        if not isinstance(item, Mapping):
            raise AdapterError("governing document entries must be objects")
        role = str(item.get("role") or "")
        if role in by_role:
            raise AdapterError(f"duplicate governing document role: {role!r}")
        by_role[role] = item
    if set(by_role) != set(GOVERNING_DOCUMENTS):
        raise AdapterError(
            "governing document roles must be exactly: "
            + ", ".join(sorted(GOVERNING_DOCUMENTS))
        )

    verified = []
    for role, relative in GOVERNING_DOCUMENTS.items():
        canonical = (root / relative).resolve()
        item = by_role[role]
        declared_path = _resolve_governing_path(
            str(item.get("path") or ""),
            root,
        )
        if not _same_path(declared_path, canonical):
            raise AdapterError(
                f"{role} must resolve to live authority {canonical}, got {declared_path}"
            )
        observed = _sha256_file(canonical)
        declared_hash = str(item.get("sha256") or "").lower()
        if declared_hash != observed:
            raise AdapterError(
                f"{role} SHA-256 mismatch: declared {declared_hash or '<missing>'}, "
                f"live {observed}"
            )
        verified.append({"role": role, "path": str(canonical), "sha256": observed})
    return verified


def _verify_artifact_reference(
    reference: Mapping[str, Any],
    *,
    base_dir: Path,
    label: str,
    override: str | Path | None = None,
) -> dict[str, str]:
    if not isinstance(reference, Mapping):
        raise AdapterError(f"{label} reference must be an object")
    expected_path = _resolve_reference(str(reference.get("path") or ""), base_dir)
    actual_path = Path(override).resolve() if override is not None else expected_path
    if override is not None and not _same_path(expected_path, actual_path):
        raise AdapterError(
            f"{label} path mismatch: approval references {expected_path}, "
            f"caller supplied {actual_path}"
        )
    observed = _sha256_file(actual_path)
    expected_hash = str(reference.get("sha256") or "").lower()
    if observed != expected_hash:
        raise AdapterError(
            f"{label} SHA-256 mismatch: declared {expected_hash or '<missing>'}, "
            f"observed {observed}"
        )
    return {"path": str(actual_path), "sha256": observed}


def validate_evidence_envelope(
    envelope: Mapping[str, Any],
    *,
    envelope_path: str | Path | None = None,
    requirement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the strict legacy evidence boundary.

    The wrapper proves identity and transport integrity.  It does not magically
    make an untrusted producer semantically correct; callers still require
    ``passed=true`` and perform evidence-type-specific checks.
    """
    required = {
        "schema",
        "evidence_id",
        "evidence_type",
        "stage",
        "producer",
        "producer_version",
        "status",
        "source_path",
        "source_sha256",
        "source_schema",
    }
    missing = sorted(required - set(envelope))
    optional = {
        "artifact_sha256",
        "timeline_sha256",
        "payload",
        "payload_sha256",
        "taste_selection_sha256",
        "selected_option_id",
        "treatment_sha256",
    }
    extra = sorted(set(envelope) - required - optional)
    if missing or extra:
        raise AdapterError(
            f"evidence envelope fields invalid; missing={missing}, extra={extra}"
        )
    if envelope.get("schema") != EVIDENCE_SCHEMA:
        raise AdapterError(f"evidence schema must be {EVIDENCE_SCHEMA!r}")
    evidence_type = str(envelope.get("evidence_type") or "")
    if evidence_type not in EVIDENCE_TYPES:
        raise AdapterError(f"unknown evidence type: {evidence_type!r}")
    if envelope.get("stage") not in STAGE_ORDER:
        raise AdapterError("evidence stage must be before-execution or before-final-render")
    if envelope.get("status") != "pass":
        raise AdapterError(
            f"evidence {envelope.get('evidence_id')!r} did not explicitly pass"
        )
    if not str(envelope.get("producer") or "").strip():
        raise AdapterError("evidence producer must be non-empty")
    if not str(envelope.get("producer_version") or "").strip():
        raise AdapterError("evidence producer_version must be non-empty")
    raw_source_path = str(envelope.get("source_path") or "")
    if not raw_source_path or not Path(raw_source_path).is_absolute():
        raise AdapterError("evidence source_path must be absolute")
    source_path = Path(raw_source_path).resolve()
    observed_source_hash = _sha256_file(source_path)
    if observed_source_hash != str(envelope.get("source_sha256") or "").lower():
        raise AdapterError(f"evidence source SHA-256 mismatch: {source_path}")
    if not str(envelope.get("source_schema") or "").strip():
        raise AdapterError("evidence source_schema must be non-empty")
    bindings = [
        key for key in ("artifact_sha256", "timeline_sha256")
        if str(envelope.get(key) or "").strip()
    ]
    if not bindings:
        raise AdapterError(
            "evidence requires at least one subject binding: artifact_sha256 or "
            "timeline_sha256"
        )
    for binding_key in bindings:
        binding_value = str(envelope[binding_key])
        if not _is_sha256(binding_value):
            raise AdapterError(f"evidence {binding_key} must be lowercase SHA-256")
    has_payload = "payload" in envelope
    has_payload_hash = "payload_sha256" in envelope
    if not has_payload and not has_payload_hash:
        raise AdapterError("evidence requires payload or payload_sha256")
    if has_payload:
        payload = envelope.get("payload")
        if payload in (None, {}, [], ""):
            raise AdapterError("evidence payload cannot be empty")
        if has_payload_hash:
            observed_payload_hash = _canonical_sha256(payload)
            if str(envelope.get("payload_sha256") or "") != observed_payload_hash:
                raise AdapterError("evidence payload_sha256 does not match payload")
    elif has_payload_hash:
        payload_hash = str(envelope.get("payload_sha256") or "")
        if not _is_sha256(payload_hash):
            raise AdapterError("evidence payload_sha256 must be lowercase SHA-256")
    if evidence_type in TREATMENT_SENSITIVE_EVIDENCE_TYPES:
        if (
            not _is_sha256(envelope.get("taste_selection_sha256"))
            or not str(envelope.get("selected_option_id") or "").strip()
            or not _is_sha256(envelope.get("treatment_sha256"))
        ):
            raise AdapterError(
                f"{evidence_type} requires taste_selection_sha256, "
                "selected_option_id, and treatment_sha256"
            )

    if requirement is not None:
        comparisons = {
            "evidence_id": requirement.get("evidence_id"),
            "evidence_type": requirement.get("evidence_type"),
            "stage": requirement.get("stage"),
            "source_schema": requirement.get("schema_id"),
        }
        for field, expected in comparisons.items():
            if envelope.get(field) != expected:
                raise AdapterError(
                    f"evidence {field} mismatch: expected {expected!r}, "
                    f"got {envelope.get(field)!r}"
                )
    return {
        "evidence_id": str(envelope["evidence_id"]),
        "evidence_type": evidence_type,
        "stage": str(envelope["stage"]),
        "path": str(Path(envelope_path).resolve()) if envelope_path else "",
        "sha256": _sha256_file(envelope_path) if envelope_path else "",
        "source": str(source_path),
        "source_sha256": observed_source_hash,
        "passed": True,
        "subject_binding": {
            key: str(envelope[key])
            for key in bindings
        },
    }


def wrap_evidence(
    *,
    source_path: str | Path,
    evidence_id: str,
    evidence_type: str,
    stage: str,
    schema_id: str,
    producer_name: str,
    producer_version: str,
    passed: bool,
    artifact_sha256: str | None = None,
    timeline_sha256: str | None = None,
    taste_selection_sha256: str | None = None,
    selected_option_id: str | None = None,
    treatment_sha256: str | None = None,
) -> dict[str, Any]:
    """Wrap a legacy JSON producer without inferring that its output passed."""
    if evidence_type not in EVIDENCE_TYPES:
        raise AdapterError(f"unknown evidence type: {evidence_type!r}")
    if stage not in STAGE_ORDER:
        raise AdapterError(f"unknown evidence stage: {stage!r}")
    if passed is not True:
        raise AdapterError(
            "legacy evidence may only enter production after an explicit --passed "
            "assertion; failed/pending evidence is not a production envelope"
        )
    source = Path(source_path).resolve()
    if evidence_type == "render_log":
        try:
            payload = _load_json(source)
        except AdapterError:
            try:
                text = source.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise AdapterError(f"cannot read render log {source}: {exc}") from exc
            if not text.strip():
                raise AdapterError("render log source cannot be empty")
            payload = {
                "format": "text",
                "bytes": source.stat().st_size,
                "line_count": len(text.splitlines()),
                "source_sha256": _sha256_file(source),
            }
    else:
        payload = _load_json(source)
    contract_rule = CONTRACT_EVIDENCE.get(evidence_type)
    if contract_rule is not None:
        contract_kind, expected_schema = contract_rule
        if schema_id != expected_schema:
            raise AdapterError(
                f"{evidence_type} source schema must be {expected_schema!r}"
            )
        validate_contract(contract_kind, payload)
    elif evidence_type != "render_log":
        observed_schema = payload.get("schema")
        if observed_schema != schema_id:
            raise AdapterError(
                f"{evidence_type} source declares schema {observed_schema!r}; "
                f"wrapper requested {schema_id!r}"
            )
    failure_signals: list[str] = []
    for key in ("status", "result"):
        value = payload.get(key) if isinstance(payload, Mapping) else None
        if isinstance(value, str) and value.casefold() in {
            "fail",
            "failed",
            "failure",
            "rejected",
            "error",
        }:
            failure_signals.append(f"{key}={value!r}")
    for key in ("passed", "automatedChecksPassed", "automated_gate_passed"):
        if isinstance(payload, Mapping) and payload.get(key) is False:
            failure_signals.append(f"{key}=false")
    nested_qa = payload.get("qa") if isinstance(payload, Mapping) else None
    if isinstance(nested_qa, Mapping) and nested_qa.get("automated_gate_passed") is False:
        failure_signals.append("qa.automated_gate_passed=false")
    if failure_signals:
        raise AdapterError(
            "legacy source contains explicit failure signals and cannot be wrapped "
            "as passing evidence: " + ", ".join(failure_signals)
        )
    if not artifact_sha256 and not timeline_sha256:
        raise AdapterError(
            "wrap-evidence requires artifact_sha256 or timeline_sha256"
        )
    subjects = {
        key: str(value).lower()
        for key, value in (
            ("artifact_sha256", artifact_sha256),
            ("timeline_sha256", timeline_sha256),
        )
        if value
    }
    for subject_key, subject_value in subjects.items():
        if not _is_sha256(subject_value):
            raise AdapterError(f"{subject_key} must be a lowercase SHA-256")
    treatment_values = (
        taste_selection_sha256,
        selected_option_id,
        treatment_sha256,
    )
    if evidence_type in TREATMENT_SENSITIVE_EVIDENCE_TYPES and not all(treatment_values):
        raise AdapterError(
            f"{evidence_type} wrapping requires taste-selection, selected-option, "
            "and treatment bindings"
        )
    envelope = {
        "schema": EVIDENCE_SCHEMA,
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "stage": stage,
        "producer": producer_name,
        "producer_version": producer_version,
        "status": "pass",
        "source_path": str(source),
        "source_sha256": _sha256_file(source),
        "source_schema": schema_id,
        "payload": payload,
    }
    envelope.update(subjects)
    if any(treatment_values):
        if not all(treatment_values):
            raise AdapterError("treatment binding fields must be supplied together")
        envelope.update(
            {
                "taste_selection_sha256": str(taste_selection_sha256).lower(),
                "selected_option_id": str(selected_option_id),
                "treatment_sha256": str(treatment_sha256).lower(),
            }
        )
    return envelope


def require_context_evidence(
    context: Mapping[str, Any],
    *,
    context_path: str | Path,
    stage: str,
    evidence_paths: Iterable[str | Path],
) -> list[dict[str, Any]]:
    if stage not in STAGE_ORDER:
        raise AdapterError(f"unknown preflight stage: {stage!r}")
    context_source = Path(context_path).resolve()
    requirements = context.get("required_evidence")
    if not isinstance(requirements, list):
        raise AdapterError("production context required_evidence must be an array")
    envelopes: dict[str, tuple[Path, dict[str, Any]]] = {}
    for value in evidence_paths:
        path = Path(value).resolve()
        envelope = _load_json(path)
        evidence_id = str(envelope.get("evidence_id") or "")
        if not evidence_id:
            raise AdapterError(f"evidence envelope has no evidence_id: {path}")
        if evidence_id in envelopes:
            raise AdapterError(f"duplicate realized evidence ID: {evidence_id!r}")
        envelopes[evidence_id] = (path, envelope)
    verified = []
    seen_ids: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise AdapterError("required_evidence entries must be objects")
        evidence_id = str(requirement.get("evidence_id") or "")
        if evidence_id in seen_ids:
            raise AdapterError(f"duplicate evidence requirement: {evidence_id!r}")
        seen_ids.add(evidence_id)
        requirement_stage = str(requirement.get("stage") or "")
        if requirement_stage not in STAGE_ORDER:
            raise AdapterError(f"invalid evidence stage for {evidence_id!r}")
        if STAGE_ORDER[requirement_stage] > STAGE_ORDER[stage]:
            continue
        expected_source = _resolve_reference(
            str(requirement.get("expected_path") or ""),
            context_source.parent,
        )
        if evidence_id not in envelopes:
            raise AdapterError(
                f"required evidence {evidence_id!r} has no supplied envelope"
            )
        envelope_path, envelope = envelopes[evidence_id]
        observed = validate_evidence_envelope(
            envelope,
            envelope_path=envelope_path,
            requirement=requirement,
        )
        if not _same_path(Path(str(envelope["source_path"])), expected_source):
            raise AdapterError(
                f"evidence {evidence_id!r} source_path must match production "
                f"context expected_path {expected_source}"
            )
        verified.append(observed)
    timeline_hashes = {
        item["subject_binding"]["timeline_sha256"]
        for item in verified
        if "timeline_sha256" in item.get("subject_binding", {})
    }
    if len(timeline_hashes) > 1:
        raise AdapterError(
            "required evidence envelopes disagree on the production timeline "
            f"fingerprint: {sorted(timeline_hashes)}"
        )
    return verified


def _selected_taste_option(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    selection = payload.get("selection")
    selected_id = (
        str(selection.get("selected_option_id") or "")
        if isinstance(selection, Mapping)
        else ""
    )
    for option in payload.get("options") or []:
        if isinstance(option, Mapping) and option.get("option_id") == selected_id:
            return option
    raise AdapterError("taste selection has no resolvable selected option")


def _implicit_subtle_grade(value: Any) -> bool:
    normalized = " ".join(str(value or "").strip().casefold().split())
    return normalized in {
        "subtle",
        "default subtle",
        "default: subtle",
        "preset subtle",
        "preset: subtle",
        "preset=subtle",
    }


def _enforce_mode_and_feature_requirements(
    context: Mapping[str, Any],
    contracts: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    *,
    stage: str,
) -> None:
    """Enforce context-sensitive requirements absent from structural schemas."""
    artifact_type = str(context.get("artifact_type") or "")
    archetype = str(context.get("content_archetype") or "")
    mode = str(context.get("operating_mode") or "")
    captions_required = bool(
        (context.get("accessibility") or {}).get("captions_required")
        if isinstance(context.get("accessibility"), Mapping)
        else False
    )
    declared_evidence = {
        str(item.get("evidence_type") or "")
        for item in context.get("required_evidence") or []
        if isinstance(item, Mapping)
    }
    required_evidence: set[str] = set()
    if artifact_type in {"video_edit", "hybrid"}:
        required_evidence.update({
            "editorial_intent",
            "taste_selection",
            "audio_plan",
            "edl_approval",
        })
    if artifact_type in {"motion_graphic", "generated_video"}:
        required_evidence.update({"editorial_intent", "taste_selection", "graphics_qa"})
    if artifact_type == "generated_video":
        required_evidence.add("render_log")
    if artifact_type == "still_asset":
        required_evidence.add("taste_selection")
    if captions_required:
        required_evidence.update({"forced_alignment", "caption_qa"})
    if archetype == "podcast_interview":
        required_evidence.update({"audio_plan", "audio_qa"})
    missing_evidence_types = sorted(required_evidence - declared_evidence)
    if missing_evidence_types:
        raise AdapterError(
            "production context omits mode/feature-required evidence types: "
            + ", ".join(missing_evidence_types)
        )

    taste_required = artifact_type in {
        "video_edit",
        "hybrid",
        "motion_graphic",
        "generated_video",
        "still_asset",
    }
    if taste_required:
        taste_contracts = contracts.get("taste-selection") or []
        if len(taste_contracts) != 1:
            raise AdapterError(
                f"{artifact_type} requires exactly one validated taste-selection "
                "contract before execution"
            )
        taste_path, taste_payload = taste_contracts[0]
        selected = _selected_taste_option(taste_payload)
        tokens = selected.get("treatment_tokens")
        treatment_artifact = selected.get("treatment_artifact")
        if isinstance(tokens, Mapping):
            grade = tokens.get("color_grade")
            if not isinstance(grade, Mapping):
                raise AdapterError("selected treatment tokens have no color_grade")
            if _implicit_subtle_grade(grade.get("look_description")) or (
                grade.get("lut_reference") is not None
                and _implicit_subtle_grade(grade.get("lut_reference"))
            ):
                raise AdapterError(
                    "implicit grade token 'subtle' is forbidden; the selected taste "
                    "option must name an explicit, human-approved treatment"
                )
            motion = tokens.get("motion")
            if isinstance(motion, Mapping) and int(
                motion.get("minimum_duration_ms", 0)
            ) > int(motion.get("maximum_duration_ms", 0)):
                raise AdapterError(
                    "selected treatment motion minimum_duration_ms exceeds maximum"
                )
        elif isinstance(treatment_artifact, Mapping):
            _verify_artifact_reference(
                treatment_artifact,
                base_dir=taste_path.parent,
                label="selected treatment_artifact",
            )
        else:
            # The contract schema should catch this first.  Retaining an
            # explicit runtime guard prevents schema drift from reintroducing
            # niche-label inference.
            raise AdapterError(
                "selected taste option requires frozen treatment_tokens or a "
                "hash-verified treatment_artifact"
            )
    if mode in {"standard", "flagship"} and artifact_type in {
        "video_edit",
        "hybrid",
        "motion_graphic",
        "generated_video",
    }:
        if len(contracts.get("editorial-intent") or []) != 1:
            raise AdapterError(
                f"{mode} {artifact_type} requires exactly one editorial-intent contract"
            )
    audio_plans = contracts.get("audio-plan") or []
    if artifact_type in {"video_edit", "hybrid"} and len(audio_plans) != 1:
        raise AdapterError(
            "video production requires exactly one audio-plan contract; mark "
            "unused operations not_applicable instead of omitting the plan"
        )
    if archetype == "podcast_interview":
        diarization = audio_plans[0][1].get("diarization")
        if not isinstance(diarization, Mapping):
            raise AdapterError("audio-plan must declare diarization")
    if (
        stage == "before-final-render"
        and artifact_type in {"video_edit", "hybrid"}
        and len(contracts.get("edl-approval") or []) != 1
    ):
        raise AdapterError(
            "timing-changing final render requires exactly one edl-approval contract"
        )
    if stage == "before-final-render" and artifact_type in {"video_edit", "hybrid"}:
        approval = contracts["edl-approval"][0][1]
        if (
            approval.get("status") != "approved"
            or approval.get("unresolved_decision_ids")
            or not isinstance(approval.get("approval"), Mapping)
        ):
            raise AdapterError(
                "before-final-render preflight requires approved EDL status, no "
                "unresolved decisions, and an approval block"
            )


def _enforce_treatment_evidence_bindings(
    context: Mapping[str, Any],
    contracts: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    *,
    stage: str,
    evidence_paths: Iterable[str | Path],
) -> None:
    """Prevent a valid taste contract from sitting beside a niche-default render."""
    taste_contracts = contracts.get("taste-selection") or []
    if not taste_contracts:
        return
    taste_path, taste_payload = taste_contracts[0]
    selected = _selected_taste_option(taste_payload)
    selected_id = str(selected.get("option_id") or "")
    taste_hash = _sha256_file(taste_path)
    treatment_artifact = selected.get("treatment_artifact")
    treatment_hash = None
    if isinstance(treatment_artifact, Mapping):
        treatment_hash = str(treatment_artifact.get("sha256") or "")
    elif isinstance(selected.get("treatment_tokens"), Mapping):
        treatment_hash = _canonical_sha256(selected["treatment_tokens"])

    by_type: dict[str, Mapping[str, Any]] = {}
    for value in evidence_paths:
        envelope = _load_json(value)
        evidence_type = str(envelope.get("evidence_type") or "")
        if evidence_type in by_type:
            raise AdapterError(f"duplicate evidence type envelope: {evidence_type!r}")
        by_type[evidence_type] = envelope
    due_types = {
        str(item.get("evidence_type") or "")
        for item in context.get("required_evidence") or []
        if isinstance(item, Mapping)
        and STAGE_ORDER.get(str(item.get("stage") or ""), 99) <= STAGE_ORDER[stage]
    }
    for evidence_type in sorted(TREATMENT_SENSITIVE_EVIDENCE_TYPES & due_types):
        envelope = by_type.get(evidence_type)
        if envelope is None:
            # require_context_evidence will provide the primary missing-file
            # error; do not turn it into a less specific taste-binding error.
            continue
        if envelope.get("selected_option_id") != selected_id:
            raise AdapterError(
                f"{evidence_type} selected_option_id is not the approved taste option"
            )
        if envelope.get("taste_selection_sha256") != taste_hash:
            raise AdapterError(
                f"{evidence_type} is not bound to the selected taste-selection SHA-256"
            )
        if envelope.get("treatment_sha256") != treatment_hash:
            raise AdapterError(
                f"{evidence_type} is not bound to the selected frozen treatment"
            )


def run_preflight(
    context_path: str | Path,
    *,
    stage: str,
    contracts: Iterable[tuple[str, str | Path]] = (),
    evidence_paths: Iterable[str | Path] = (),
    editing_os_root: str | Path | None = None,
) -> dict[str, Any]:
    context_source = Path(context_path).resolve()
    context = _load_json(context_source)
    validate_contract(PRODUCTION_CONTEXT_KIND, context)
    if context.get("schema_version") != PRODUCTION_CONTEXT_VERSION:
        raise AdapterError(
            f"production context schema_version must be {PRODUCTION_CONTEXT_VERSION!r}"
        )
    governing = verify_governing_documents(
        context,
        editing_os_root=editing_os_root,
    )
    validated_contracts = [
        {
            "kind": PRODUCTION_CONTEXT_KIND,
            "path": str(context_source),
            "sha256": _sha256_file(context_source),
        }
    ]
    contract_payloads: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for kind, path in contracts:
        source = Path(path).resolve()
        payload = _load_json(source)
        validate_contract(kind, payload)
        contract_payloads.setdefault(kind, []).append((source, payload))
        if payload.get("project_id") != context.get("project_id"):
            raise AdapterError(
                f"{kind} project_id does not match production context: {source}"
            )
        if kind != "production-context":
            reference = payload.get("production_context")
            _verify_artifact_reference(
                reference,
                base_dir=source.parent,
                label=f"{kind}.production_context",
                override=context_source,
            )
        if kind == "taste-selection":
            live_taste_hash = next(
                item["sha256"]
                for item in governing
                if item["role"] == "taste_profile"
            )
            if payload.get("taste_profile_sha256") != live_taste_hash:
                raise AdapterError(
                    "taste-selection.taste_profile_sha256 does not match the "
                    "governing Taste Profile"
                )
        validated_contracts.append(
            {"kind": kind, "path": str(source), "sha256": _sha256_file(source)}
        )
    _enforce_mode_and_feature_requirements(
        context,
        contract_payloads,
        stage=stage,
    )
    evidence_paths = list(evidence_paths)
    _enforce_treatment_evidence_bindings(
        context,
        contract_payloads,
        stage=stage,
        evidence_paths=evidence_paths,
    )
    evidence = require_context_evidence(
        context,
        context_path=context_source,
        stage=stage,
        evidence_paths=evidence_paths,
    )
    return {
        "schema": "arete-orchestration-preflight/v1",
        "status": "pass",
        "publishable": False,
        "project_id": context["project_id"],
        "stage": stage,
        "production_context": {
            "path": str(context_source),
            "sha256": _sha256_file(context_source),
        },
        "governing_documents": governing,
        "validated_contracts": validated_contracts,
        "required_evidence": evidence,
        "note": (
            "Preflight proves inputs and prerequisites only. It never grants "
            "publication readiness."
        ),
    }


def check_edl_approval(
    approval_path: str | Path,
    *,
    edl_path: str | Path | None = None,
    taste_selection_path: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(approval_path).resolve()
    approval = _load_json(source)
    validate_contract("edl-approval", approval)
    if approval.get("status") != "approved":
        raise AdapterError("timing-changing render requires EDL status=approved")
    if approval.get("unresolved_decision_ids"):
        raise AdapterError("timing-changing render has unresolved editorial decisions")
    approval_block = approval.get("approval")
    if not isinstance(approval_block, Mapping):
        raise AdapterError("approved EDL requires an approval block")
    base = source.parent
    artifacts = {}
    for label in (
        "production_context",
        "edl",
        "preview",
        "timeline_map",
        "retimed_words",
    ):
        override = edl_path if label == "edl" else None
        artifacts[label] = _verify_artifact_reference(
            approval.get(label),
            base_dir=base,
            label=label,
            override=override,
        )
    if approval_block.get("approved_edl_sha256") != artifacts["edl"]["sha256"]:
        raise AdapterError("approval.approved_edl_sha256 does not match the EDL")
    edl_payload = _load_json(artifacts["edl"]["path"])
    approved_edl = (
        edl_payload.get("edl")
        if isinstance(edl_payload.get("edl"), Mapping)
        else edl_payload
    )
    grade_tokens = []
    if approved_edl.get("grade") is not None:
        grade_tokens.append(approved_edl.get("grade"))
    for item in approved_edl.get("ranges") or []:
        if isinstance(item, Mapping) and item.get("grade") is not None:
            grade_tokens.append(item.get("grade"))
    if not grade_tokens:
        raise AdapterError(
            "approved EDL has no explicit grade/treatment token; engine defaults "
            "may not select the look"
        )
    if any(_implicit_subtle_grade(value) for value in grade_tokens):
        raise AdapterError(
            "approved EDL contains forbidden implicit grade token 'subtle'"
        )
    if any(str(value).strip().casefold() != "none" for value in grade_tokens):
        raise AdapterError(
            "approved EDL must use grade='none'; the selected taste contract "
            "owns the executable color treatment"
        )

    required_decision_ids: set[str] = set()
    decision_lists = [
        approved_edl.get("review_required"),
        (approved_edl.get("analysis") or {}).get("review_required")
        if isinstance(approved_edl.get("analysis"), Mapping) else None,
        (approved_edl.get("editorial") or {}).get("review_required")
        if isinstance(approved_edl.get("editorial"), Mapping) else None,
    ]
    editorial = approved_edl.get("editorial")
    if isinstance(editorial, Mapping):
        decision_lists.append(
            [
                item for item in editorial.get("decisions") or []
                if isinstance(item, Mapping) and item.get("automatic") is False
            ]
        )
    for values in decision_lists:
        for item in values or []:
            if isinstance(item, Mapping) and item.get("id"):
                required_decision_ids.add(str(item["id"]))
    resolved_ids = {
        str(item.get("decision_id"))
        for item in approval.get("resolved_decisions") or []
        if isinstance(item, Mapping) and item.get("decision_id")
    }
    missing_decisions = sorted(required_decision_ids - resolved_ids)
    if missing_decisions:
        raise AdapterError(
            "approved EDL has review decisions without recorded resolutions: "
            + ", ".join(missing_decisions)
        )

    timeline_payload = _load_json_value(artifacts["timeline_map"]["path"])
    words_payload = _load_json_value(artifacts["retimed_words"]["path"])
    timeline_array = _extract_array(timeline_payload, "timeline_map")
    words_array = _extract_array(words_payload, "retimed_words")
    timeline_fingerprint = caption_timeline_fingerprint(
        timeline_array,
        words_array,
    )
    if approval_block.get("timeline_fingerprint") != timeline_fingerprint:
        raise AdapterError(
            "approval.timeline_fingerprint does not match timeline_map + "
            "retimed_words"
        )
    embedded_editorial = approved_edl.get("editorial")
    if isinstance(embedded_editorial, Mapping):
        if embedded_editorial.get("timeline_map") is not None and (
            _canonical_sha256(embedded_editorial["timeline_map"])
            != _canonical_sha256(timeline_array)
        ):
            raise AdapterError("external timeline_map differs from the approved EDL")
        if embedded_editorial.get("retimed_words") is not None and (
            _canonical_sha256(embedded_editorial["retimed_words"])
            != _canonical_sha256(words_array)
        ):
            raise AdapterError("external retimed_words differs from the approved EDL")
    context = _load_json(artifacts["production_context"]["path"])
    validate_contract("production-context", context)
    if context.get("project_id") != approval.get("project_id"):
        raise AdapterError("EDL approval and production context project IDs differ")

    if taste_selection_path is None:
        raise AdapterError(
            "timing-changing render requires the selected taste-selection artifact"
        )
    taste_path = Path(taste_selection_path).resolve()
    taste = _load_json(taste_path)
    validate_contract("taste-selection", taste)
    taste_hash = _sha256_file(taste_path)
    if approval_block.get("selected_taste_selection_sha256") != taste_hash:
        raise AdapterError(
            "approval selected_taste_selection_sha256 does not match supplied artifact"
        )
    if taste.get("project_id") != approval.get("project_id"):
        raise AdapterError("taste selection and EDL approval project IDs differ")
    selected = _selected_taste_option(taste)
    tokens = selected.get("treatment_tokens")
    if not isinstance(tokens, Mapping):
        raise AdapterError(
            "approved render requires embedded executable treatment_tokens"
        )
    color_grade = tokens.get("color_grade")
    if not isinstance(color_grade, Mapping):
        raise AdapterError("selected treatment has no executable color_grade")
    strategy = str(color_grade.get("render_strategy") or "")
    if strategy not in {"ungraded", "ffmpeg_filter", "lut_3d"}:
        raise AdapterError("selected color_grade.render_strategy is unsupported")
    if strategy == "ffmpeg_filter" and not str(
        color_grade.get("filtergraph") or ""
    ).strip():
        raise AdapterError("ffmpeg_filter strategy requires a filtergraph")
    if strategy == "lut_3d":
        _verify_artifact_reference(
            color_grade.get("lut_reference"),
            base_dir=taste_path.parent,
            label="selected color LUT",
        )
    return {
        "schema": "arete-edl-render-authorization/v1",
        "status": "pass",
        "publishable": False,
        "project_id": approval["project_id"],
        "approval": {"path": str(source), "sha256": _sha256_file(source)},
        "artifacts": artifacts,
        "taste_selection": {"path": str(taste_path), "sha256": taste_hash},
        "timeline_fingerprint": timeline_fingerprint,
        "color_grade": {
            "render_strategy": strategy,
            "treatment_sha256": _canonical_sha256(tokens),
        },
        "resolved_decision_count": len(approval.get("resolved_decisions") or []),
        "note": "This authorizes the approved timing only; it is not publication approval.",
    }


def _verified_edl_authorization(
    authorization_path: str | Path,
) -> tuple[dict[str, Any], Path]:
    source = Path(authorization_path).resolve()
    supplied = _load_json(source)
    if supplied.get("schema") != "arete-edl-render-authorization/v1":
        raise AdapterError("unknown EDL render authorization schema")
    if supplied.get("status") != "pass":
        raise AdapterError("EDL render authorization did not pass")
    approval = supplied.get("approval")
    artifacts = supplied.get("artifacts")
    taste = supplied.get("taste_selection")
    if not all(isinstance(value, Mapping) for value in (approval, artifacts, taste)):
        raise AdapterError("EDL render authorization is incomplete")
    edl = artifacts.get("edl")
    if not isinstance(edl, Mapping):
        raise AdapterError("EDL render authorization has no EDL identity")
    recomputed = check_edl_approval(
        str(approval.get("path") or ""),
        edl_path=str(edl.get("path") or ""),
        taste_selection_path=str(taste.get("path") or ""),
    )
    if supplied != recomputed:
        raise AdapterError(
            "EDL render authorization is stale or was not emitted by the "
            "current adapter"
        )
    return recomputed, source


def _ffmpeg_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:")


def apply_approved_edl(
    authorization_path: str | Path,
    output_path: str | Path,
    *,
    engine_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    ffmpeg_bin: str = "ffmpeg",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Render only through a revalidated EDL capability and selected color tokens."""
    authorization, authorization_source = _verified_edl_authorization(
        authorization_path
    )
    output = Path(output_path).resolve()
    runtime.output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    engine = (
        Path(engine_path).resolve()
        if engine_path
        else (
            _editing_os_root()
            / "Video Editing"
            / "Engines"
            / "Video editing engine"
            / "engine.py"
        ).resolve()
    )
    if not engine.is_file():
        raise AdapterError(f"video editing engine is missing: {engine}")
    base = output.with_name(f".{output.stem}.approved-base{output.suffix}")
    graded = output.with_name(f".{output.stem}.selected-color{output.suffix}")
    try:
        base.unlink(missing_ok=True)
        graded.unlink(missing_ok=True)
        command = [
            sys.executable,
            "-B",
            str(engine),
            "--apply-edits",
            "--edl-in",
            authorization["artifacts"]["edl"]["path"],
            "--out",
            str(base),
            "--no-captions",
        ]
        if work_dir:
            command.extend(["--work-dir", str(Path(work_dir).resolve())])
        try:
            runner(command, check=True, **({"env": runtime.child_env(), **runtime.child_kwargs()} if runner is subprocess.run else {}))
        except (OSError, subprocess.CalledProcessError) as exc:
            raise AdapterError(f"approved EDL render failed: {exc}") from exc
        if not base.is_file():
            raise AdapterError("video engine returned without an encoded artifact")

        taste_path = Path(authorization["taste_selection"]["path"]).resolve()
        taste = _load_json(taste_path)
        selected = _selected_taste_option(taste)
        tokens = selected["treatment_tokens"]
        grade = tokens["color_grade"]
        strategy = grade["render_strategy"]
        if strategy == "ungraded":
            os.replace(base, output)
        else:
            if strategy == "ffmpeg_filter":
                video_filter = str(grade["filtergraph"])
            elif strategy == "lut_3d":
                lut = _verify_artifact_reference(
                    grade["lut_reference"],
                    base_dir=taste_path.parent,
                    label="selected color LUT",
                )
                video_filter = f"lut3d=file='{_ffmpeg_filter_path(Path(lut['path']))}'"
            else:  # guarded by the contract and check_edl_approval
                raise AdapterError(f"unsupported color render strategy: {strategy}")
            color_command = [
                runtime.tool("ffmpeg", explicit=None if ffmpeg_bin == "ffmpeg" else ffmpeg_bin),
                "-y",
                "-i",
                str(base),
                "-vf",
                video_filter,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(graded),
            ]
            try:
                runner(color_command, check=True, **({"env": runtime.child_env(), **runtime.child_kwargs()} if runner is subprocess.run else {}))
            except (OSError, subprocess.CalledProcessError) as exc:
                raise AdapterError(f"selected color treatment failed: {exc}") from exc
            if not graded.is_file():
                raise AdapterError("selected color treatment produced no artifact")
            os.replace(graded, output)
        if not output.is_file():
            raise AdapterError("approved render did not produce the requested output")
        return {
            "schema": "arete-approved-edl-render/v1",
            "status": "pass",
            "publishable": False,
            "artifact": {
                "path": str(output),
                "sha256": _sha256_file(output),
            },
            "authorization": {
                "path": str(authorization_source),
                "sha256": _sha256_file(authorization_source),
            },
            "edl": authorization["artifacts"]["edl"],
            "taste_selection": authorization["taste_selection"],
            "timing": {
                "timeline_map": authorization["artifacts"]["timeline_map"],
                "retimed_words": authorization["artifacts"]["retimed_words"],
                "timeline_fingerprint": authorization["timeline_fingerprint"],
            },
            "color_grade": {
                "render_strategy": strategy,
                "treatment_sha256": _canonical_sha256(tokens),
            },
            "engine": str(engine),
            "note": "Render execution only; publication still requires Quality ready=true.",
        }
    finally:
        base.unlink(missing_ok=True)
        graded.unlink(missing_ok=True)


def _extract_array(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, Mapping):
        values = payload.get(key)
    else:
        values = None
    if not isinstance(values, list) or not values:
        raise AdapterError(f"{key} artifact must contain a non-empty array")
    if not all(isinstance(item, Mapping) for item in values):
        raise AdapterError(f"{key} entries must be objects")
    return [dict(item) for item in values]


def _load_json_value(path: str | Path) -> Any:
    source = Path(path).resolve()
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read JSON {source}: {exc}") from exc


def caption_timeline_fingerprint(
    timeline_map: Sequence[Mapping[str, Any]],
    retimed_words: Sequence[Mapping[str, Any]],
) -> str:
    return _canonical_sha256(
        {
            "timeline_map": [dict(item) for item in timeline_map],
            "retimed_words": [dict(item) for item in retimed_words],
        }
    )


def _verify_forced_alignment(
    forced_alignment_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    source = Path(forced_alignment_path).resolve()
    envelope = _load_json(source)
    verified = validate_evidence_envelope(envelope, envelope_path=source)
    if envelope.get("evidence_type") != "forced_alignment":
        raise AdapterError("forced-alignment envelope has the wrong evidence_type")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise AdapterError("forced-alignment payload must be an object")
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise AdapterError("forced-alignment payload requires provenance")
    method = str(provenance.get("method") or "").lower()
    if method not in FORCED_ALIGNMENT_METHODS or provenance.get("forced") is not True:
        raise AdapterError(
            "production captions require explicit phoneme forced-alignment provenance"
        )
    return envelope, verified, source


def authorize_caption_render(
    *,
    edl_authorization_path: str | Path,
    forced_alignment_path: str | Path,
    timeline_map_path: str | Path,
    retimed_words_path: str | Path,
    taste_selection_path: str | Path,
) -> dict[str, Any]:
    edl_authorization, edl_source = _verified_edl_authorization(
        edl_authorization_path
    )
    _, forced_verified, forced_source = _verify_forced_alignment(
        forced_alignment_path
    )
    timeline_path = Path(timeline_map_path).resolve()
    words_path = Path(retimed_words_path).resolve()
    taste_path = Path(taste_selection_path).resolve()
    expected_refs = {
        "timeline_map": timeline_path,
        "retimed_words": words_path,
    }
    for label, supplied_path in expected_refs.items():
        reference = edl_authorization["artifacts"][label]
        if not _same_path(Path(reference["path"]), supplied_path):
            raise AdapterError(
                f"caption render {label} differs from EDL authorization"
            )
        if _sha256_file(supplied_path) != reference["sha256"]:
            raise AdapterError(f"caption render {label} hash changed")
    if not _same_path(
        Path(edl_authorization["taste_selection"]["path"]),
        taste_path,
    ) or _sha256_file(taste_path) != edl_authorization["taste_selection"]["sha256"]:
        raise AdapterError(
            "caption render taste selection differs from EDL authorization"
        )
    timeline = _extract_array(_load_json_value(timeline_path), "timeline_map")
    words = _extract_array(_load_json_value(words_path), "retimed_words")
    fingerprint = caption_timeline_fingerprint(timeline, words)
    if fingerprint != edl_authorization["timeline_fingerprint"]:
        raise AdapterError("caption render timeline fingerprint is not approved")
    return {
        "schema": "arete-caption-render-authorization/v1",
        "status": "pass",
        "publishable": False,
        "edl_authorization": {
            "path": str(edl_source),
            "sha256": _sha256_file(edl_source),
        },
        "forced_alignment": forced_verified,
        "timeline_map": {
            "path": str(timeline_path),
            "sha256": _sha256_file(timeline_path),
        },
        "retimed_words": {
            "path": str(words_path),
            "sha256": _sha256_file(words_path),
            "word_count": len(words),
        },
        "taste_selection": {
            "path": str(taste_path),
            "sha256": _sha256_file(taste_path),
        },
        "timeline_fingerprint": fingerprint,
        "note": "Caption render execution only; final caption QA remains required.",
    }


def check_caption_timing(
    *,
    forced_alignment_path: str | Path,
    caption_evidence_path: str | Path,
    timeline_map_path: str | Path,
    retimed_words_path: str | Path,
) -> dict[str, Any]:
    caption_source = Path(caption_evidence_path).resolve()
    caption = _load_json(caption_source)
    _, forced_verified, forced_source = _verify_forced_alignment(
        forced_alignment_path
    )
    caption_verified = validate_evidence_envelope(
        caption,
        envelope_path=caption_source,
    )
    if caption.get("evidence_type") != "caption_qa":
        raise AdapterError("caption evidence envelope must have evidence_type=caption_qa")

    timeline_path = Path(timeline_map_path).resolve()
    words_path = Path(retimed_words_path).resolve()
    timeline = _extract_array(_load_json_value(timeline_path), "timeline_map")
    words = _extract_array(_load_json_value(words_path), "retimed_words")
    previous_end = -1.0
    for index, word in enumerate(words):
        try:
            start = float(word["start"])
            end = float(word["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError(f"retimed word {index} has invalid timing") from exc
        if start < previous_end - 1e-6 or end <= start:
            raise AdapterError(f"retimed word {index} is non-monotonic or empty")
        previous_end = end
    fingerprint = caption_timeline_fingerprint(timeline, words)
    caption_payload = caption.get("payload")
    if not isinstance(caption_payload, Mapping):
        raise AdapterError("caption QA payload must be an object")
    timing = caption_payload.get("post_cut_timing")
    if not isinstance(timing, Mapping):
        raise AdapterError("caption QA payload requires post_cut_timing")
    expected = {
        "source_of_truth": "post-cut-retimed-words",
        "forced_alignment_sha256": _sha256_file(forced_source),
        "timeline_map_sha256": _sha256_file(timeline_path),
        "retimed_words_sha256": _sha256_file(words_path),
        "timeline_fingerprint": fingerprint,
    }
    for key, value in expected.items():
        if timing.get(key) != value:
            raise AdapterError(
                f"caption post_cut_timing.{key} mismatch: expected {value!r}, "
                f"got {timing.get(key)!r}"
            )
    return {
        "schema": "arete-caption-timing-authorization/v1",
        "status": "pass",
        "publishable": False,
        "forced_alignment": forced_verified,
        "caption_qa": caption_verified,
        "timeline_map": {
            "path": str(timeline_path),
            "sha256": expected["timeline_map_sha256"],
        },
        "retimed_words": {
            "path": str(words_path),
            "sha256": expected["retimed_words_sha256"],
            "word_count": len(words),
        },
        "timeline_fingerprint": fingerprint,
    }


def _quality_module() -> Any:
    global _QUALITY_API
    if _QUALITY_API is not None:
        return _QUALITY_API
    module_path = (
        _editing_os_root()
        / "Video Editing"
        / "Engines"
        / "Quality_engine"
        / "qa.py"
    )
    if not module_path.is_file():
        raise AdapterError(f"Quality Engine is missing: {module_path}")
    spec = importlib.util.spec_from_file_location("arete_quality_engine", module_path)
    if spec is None or spec.loader is None:
        raise AdapterError(f"cannot load Quality Engine: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "run_quality_audit", None)):
        raise AdapterError("Quality Engine does not expose run_quality_audit")
    _QUALITY_API = module
    return module


def run_quality(
    artifact: str | Path,
    *,
    spec_path: str | Path,
    review_path: str | Path | None = None,
    compare_to: str | Path | None = None,
    evidence_paths: Iterable[str | Path] = (),
    render_logs: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Invoke the owned Quality Engine and return its report unchanged.

    This function never synthesizes or upgrades ``ready``.  In particular, a
    clean automated pass remains non-publishable until the Quality Engine has a
    complete, exact-artifact human review.
    """
    qa = _quality_module()
    report = qa.run_quality_audit(
        artifact,
        spec=_load_json(spec_path),
        compare_to=compare_to,
        review=_load_json(review_path) if review_path else None,
        evidence_paths=[str(Path(value).resolve()) for value in evidence_paths],
        render_logs=[str(Path(value).resolve()) for value in render_logs],
    )
    if not isinstance(report, dict) or report.get("schema") != QUALITY_REPORT_SCHEMA:
        raise AdapterError("Quality Engine returned an unknown report schema")
    return report


def assert_publishable(
    artifact_path: str | Path,
    quality_report_path: str | Path,
) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve()
    report_path = Path(quality_report_path).resolve()
    report = _load_json(report_path)
    if report.get("schema") != QUALITY_REPORT_SCHEMA:
        raise AdapterError(f"quality report schema must be {QUALITY_REPORT_SCHEMA!r}")
    artifact_entry = report.get("artifact")
    if not isinstance(artifact_entry, Mapping):
        raise AdapterError("quality report has no artifact identity")
    observed = _sha256_file(artifact)
    if artifact_entry.get("sha256") != observed:
        raise AdapterError(
            "quality report is not bound to the exact artifact requested for publication"
        )
    reported_path = Path(str(artifact_entry.get("path") or "")).resolve()
    if not _same_path(reported_path, artifact):
        raise AdapterError(
            f"quality report artifact path differs: {reported_path} != {artifact}"
        )
    if report.get("automated_gate_passed") is not True:
        raise AdapterError("Quality Engine automated gate did not pass")
    human = report.get("human_review")
    if not isinstance(human, Mapping) or human.get("status") != "pass":
        raise AdapterError("Quality Engine exact-artifact human review did not pass")
    if report.get("ready") is not True:
        raise AdapterError("Quality Engine report does not grant ready=true")
    return {
        "schema": "arete-publication-authorization/v1",
        "status": "pass",
        "publishable": True,
        "artifact": {"path": str(artifact), "sha256": observed},
        "quality_report": {
            "path": str(report_path),
            "sha256": _sha256_file(report_path),
            "schema": QUALITY_REPORT_SCHEMA,
            "ready": True,
        },
    }


def _parse_contract(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("contract must be KIND=PATH")
    kind, path = value.split("=", 1)
    if kind not in CONTRACT_KINDS:
        raise argparse.ArgumentTypeError(f"unknown contract kind: {kind}")
    if not path.strip():
        raise argparse.ArgumentTypeError("contract path cannot be empty")
    return kind, path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed owned adapter for Editing OS orchestration."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="validate context and prerequisites")
    preflight.add_argument("--context", required=True)
    preflight.add_argument(
        "--stage",
        choices=sorted(STAGE_ORDER, key=STAGE_ORDER.get),
        default="before-execution",
    )
    preflight.add_argument("--contract", action="append", type=_parse_contract, default=[])
    preflight.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="strict arete-evidence-envelope/v1 JSON; repeatable",
    )
    preflight.add_argument("--output")

    wrap = commands.add_parser("wrap-evidence", help="wrap explicit-passing legacy JSON")
    wrap.add_argument("--input", required=True)
    wrap.add_argument("--output", required=True)
    wrap.add_argument("--evidence-id", required=True)
    wrap.add_argument("--evidence-type", choices=sorted(EVIDENCE_TYPES), required=True)
    wrap.add_argument("--stage", choices=sorted(STAGE_ORDER), required=True)
    wrap.add_argument("--schema-id", required=True)
    wrap.add_argument("--producer", required=True)
    wrap.add_argument("--producer-version", required=True)
    wrap.add_argument("--artifact-sha256")
    wrap.add_argument("--timeline-sha256")
    wrap.add_argument("--taste-selection-sha256")
    wrap.add_argument("--selected-option-id")
    wrap.add_argument("--treatment-sha256")
    wrap.add_argument("--passed", action="store_true", required=True)

    caption = commands.add_parser(
        "check-caption-timing",
        help="prove forced alignment and the post-cut timing chain",
    )
    caption.add_argument("--forced-alignment", required=True)
    caption.add_argument("--caption-evidence", required=True)
    caption.add_argument("--timeline-map", required=True)
    caption.add_argument("--retimed-words", required=True)
    caption.add_argument("--output")

    authorize_caption = commands.add_parser(
        "authorize-caption-render",
        help="issue a caption render capability for one approved post-cut clock",
    )
    authorize_caption.add_argument("--edl-authorization", required=True)
    authorize_caption.add_argument("--forced-alignment", required=True)
    authorize_caption.add_argument("--timeline-map", required=True)
    authorize_caption.add_argument("--retimed-words", required=True)
    authorize_caption.add_argument("--taste-selection", required=True)
    authorize_caption.add_argument("--output", required=True)

    edl = commands.add_parser(
        "check-edl-approval",
        help="authorize the exact approved timing for render",
    )
    edl.add_argument("--approval", required=True)
    edl.add_argument("--edl")
    edl.add_argument("--taste-selection", required=True)
    edl.add_argument("--output")

    apply_edl = commands.add_parser(
        "apply-approved-edl",
        help="consume an EDL authorization and render through the owned boundary",
    )
    apply_edl.add_argument("--authorization", required=True)
    apply_edl.add_argument("--out", required=True)
    apply_edl.add_argument("--manifest", required=True)
    apply_edl.add_argument("--engine")
    apply_edl.add_argument("--work-dir")
    apply_edl.add_argument("--ffmpeg", default="ffmpeg")

    quality = commands.add_parser(
        "run-quality",
        help="invoke the Quality Engine without inventing readiness",
    )
    quality.add_argument("--artifact", required=True)
    quality.add_argument("--spec", required=True)
    quality.add_argument("--review")
    quality.add_argument("--compare-to")
    quality.add_argument("--evidence", action="append", default=[])
    quality.add_argument("--render-log", action="append", default=[])
    quality.add_argument("--output", required=True)

    publish = commands.add_parser(
        "assert-publishable",
        help="require ready=true for this exact artifact hash",
    )
    publish.add_argument("--artifact", required=True)
    publish.add_argument("--quality-report", required=True)
    publish.add_argument("--output")
    return parser


def _emit(payload: Mapping[str, Any], output: str | Path | None = None) -> None:
    if output:
        target = _write_json(output, payload)
        print(f"wrote: {target}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    runtime.guard_args(args, ("output", "out", "manifest", "work_dir"))
    try:
        if args.command == "preflight":
            result = run_preflight(
                args.context,
                stage=args.stage,
                contracts=args.contract,
                evidence_paths=args.evidence,
            )
            _emit(result, args.output)
        elif args.command == "wrap-evidence":
            envelope = wrap_evidence(
                source_path=args.input,
                evidence_id=args.evidence_id,
                evidence_type=args.evidence_type,
                stage=args.stage,
                schema_id=args.schema_id,
                producer_name=args.producer,
                producer_version=args.producer_version,
                passed=args.passed,
                artifact_sha256=args.artifact_sha256,
                timeline_sha256=args.timeline_sha256,
                taste_selection_sha256=args.taste_selection_sha256,
                selected_option_id=args.selected_option_id,
                treatment_sha256=args.treatment_sha256,
            )
            validate_evidence_envelope(envelope)
            _emit(envelope, args.output)
        elif args.command == "check-caption-timing":
            _emit(
                check_caption_timing(
                    forced_alignment_path=args.forced_alignment,
                    caption_evidence_path=args.caption_evidence,
                    timeline_map_path=args.timeline_map,
                    retimed_words_path=args.retimed_words,
                ),
                args.output,
            )
        elif args.command == "authorize-caption-render":
            _emit(
                authorize_caption_render(
                    edl_authorization_path=args.edl_authorization,
                    forced_alignment_path=args.forced_alignment,
                    timeline_map_path=args.timeline_map,
                    retimed_words_path=args.retimed_words,
                    taste_selection_path=args.taste_selection,
                ),
                args.output,
            )
        elif args.command == "check-edl-approval":
            _emit(
                check_edl_approval(
                    args.approval,
                    edl_path=args.edl,
                    taste_selection_path=args.taste_selection,
                ),
                args.output,
            )
        elif args.command == "apply-approved-edl":
            _emit(
                apply_approved_edl(
                    args.authorization,
                    args.out,
                    engine_path=args.engine,
                    work_dir=args.work_dir,
                    ffmpeg_bin=args.ffmpeg,
                ),
                args.manifest,
            )
        elif args.command == "run-quality":
            report = run_quality(
                args.artifact,
                spec_path=args.spec,
                review_path=args.review,
                compare_to=args.compare_to,
                evidence_paths=args.evidence,
                render_logs=args.render_log,
            )
            _emit(report, args.output)
            return 0 if report.get("automated_gate_passed") else 1
        elif args.command == "assert-publishable":
            _emit(
                assert_publishable(args.artifact, args.quality_report),
                args.output,
            )
        else:  # pragma: no cover - argparse guarantees a known command
            raise AdapterError(f"unsupported command: {args.command}")
    except AdapterError as exc:
        print(f"orchestration adapter error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

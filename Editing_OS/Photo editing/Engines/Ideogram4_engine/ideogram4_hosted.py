#!/usr/bin/env python3
"""Production-safe Ideogram 4 hosted API adapter for the Editing OS.

The adapter is intentionally structured-prompt-only. It validates Ideogram 4's
caption contract, defaults to a no-cost dry run, and requires explicit flags
before a paid API request can be made.
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
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable


API_URL = "https://api.ideogram.ai/v1/ideogram-v4/generate"
API_DOC_URL = "https://developer.ideogram.ai/api-reference/api-reference/generate-v4"
PRICING_URL = "https://ideogram.ai/api-pricing/"
API_TERMS_URL = "https://ideogram.ai/terms-of-service"
SCHEMA_VERSION = "editing-os/ideogram4-hosted/v1"
SECRET_ENV = "IDEOGRAM_API_KEY"
MAX_PROMPT_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 1_000_000
MAX_IMAGE_BYTES = 64 * 1024 * 1024

SPEED_COST_USD = {
    "TURBO": 0.03,
    "DEFAULT": 0.06,
    "QUALITY": 0.10,
}

SUPPORTED_RESOLUTIONS = (
    "2048x2048",
    "1440x2880",
    "2880x1440",
    "1664x2496",
    "2496x1664",
    "1792x2240",
    "2240x1792",
    "1440x2560",
    "2560x1440",
    "1600x2560",
    "2560x1600",
    "1728x2304",
    "2304x1728",
    "1296x3168",
    "3168x1296",
    "1152x2944",
    "2944x1152",
    "1248x3328",
    "3328x1248",
    "1280x3072",
    "3072x1280",
    "1024x3072",
    "3072x1024",
)

PURPOSES = (
    "thumbnail",
    "title-card",
    "quote-card",
    "stat-card",
    "cta",
    "signage",
    "logo-concept",
    "other",
)

HEX_COLOR = re.compile(r"^#[0-9A-F]{6}$")
IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"RIFF",
)


class PromptValidationError(ValueError):
    """Raised when a structured prompt violates the production contract."""


class IdeogramApiError(RuntimeError):
    """Raised for safe, redacted API or download failures."""


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptValidationError(f"{path} must be a non-empty string")
    return value


def _validate_key_order(
    obj: dict[str, Any],
    allowed: list[str],
    required: Iterable[str],
    path: str,
) -> None:
    unknown = [key for key in obj if key not in allowed]
    if unknown:
        raise PromptValidationError(f"{path} contains unknown key(s): {', '.join(unknown)}")

    missing = [key for key in required if key not in obj]
    if missing:
        raise PromptValidationError(f"{path} is missing required key(s): {', '.join(missing)}")

    actual = list(obj)
    expected = [key for key in allowed if key in obj]
    if actual != expected:
        raise PromptValidationError(
            f"{path} key order must be {expected}; received {actual}"
        )


def _validate_palette(value: Any, limit: int, path: str) -> None:
    if not isinstance(value, list):
        raise PromptValidationError(f"{path} must be a list")
    if not value:
        raise PromptValidationError(f"{path} must not be empty")
    if len(value) > limit:
        raise PromptValidationError(f"{path} supports at most {limit} colors")
    for index, color in enumerate(value):
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            raise PromptValidationError(
                f"{path}[{index}] must use uppercase #RRGGBB format"
            )


def _validate_bbox(value: Any, path: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise PromptValidationError(
            f"{path} must be four integers: [y_min,x_min,y_max,x_max]"
        )
    if any(item < 0 or item > 1000 for item in value):
        raise PromptValidationError(f"{path} coordinates must be within 0..1000")
    y_min, x_min, y_max, x_max = value
    if y_min >= y_max or x_min >= x_max:
        raise PromptValidationError(
            f"{path} must have y_min < y_max and x_min < x_max"
        )


def validate_prompt(prompt: Any) -> list[str]:
    """Validate the production subset of the official Ideogram 4 JSON contract."""
    if not isinstance(prompt, dict):
        raise PromptValidationError("prompt must be a JSON object")

    _validate_key_order(
        prompt,
        [
            "high_level_description",
            "style_description",
            "compositional_deconstruction",
        ],
        [
            "high_level_description",
            "style_description",
            "compositional_deconstruction",
        ],
        "prompt",
    )
    _non_empty_string(prompt["high_level_description"], "high_level_description")

    style = prompt["style_description"]
    if not isinstance(style, dict):
        raise PromptValidationError("style_description must be an object")
    has_photo = "photo" in style
    has_art = "art_style" in style
    if has_photo == has_art:
        raise PromptValidationError(
            "style_description must contain exactly one of photo or art_style"
        )
    if has_photo:
        style_order = [
            "aesthetics",
            "lighting",
            "photo",
            "medium",
            "color_palette",
        ]
        style_required = ["aesthetics", "lighting", "photo", "medium"]
    else:
        style_order = [
            "aesthetics",
            "lighting",
            "medium",
            "art_style",
            "color_palette",
        ]
        style_required = ["aesthetics", "lighting", "medium", "art_style"]
    _validate_key_order(style, style_order, style_required, "style_description")
    for key in style_required:
        _non_empty_string(style[key], f"style_description.{key}")
    if "color_palette" in style:
        _validate_palette(
            style["color_palette"], 16, "style_description.color_palette"
        )

    composition = prompt["compositional_deconstruction"]
    if not isinstance(composition, dict):
        raise PromptValidationError("compositional_deconstruction must be an object")
    _validate_key_order(
        composition,
        ["background", "elements"],
        ["background", "elements"],
        "compositional_deconstruction",
    )
    _non_empty_string(
        composition["background"], "compositional_deconstruction.background"
    )
    elements = composition["elements"]
    if not isinstance(elements, list) or not elements:
        raise PromptValidationError(
            "compositional_deconstruction.elements must be a non-empty list"
        )

    warnings: list[str] = []
    total_literal_text = 0
    for index, element in enumerate(elements):
        path = f"compositional_deconstruction.elements[{index}]"
        if not isinstance(element, dict):
            raise PromptValidationError(f"{path} must be an object")
        element_type = element.get("type")
        if element_type == "obj":
            allowed = ["type", "bbox", "desc", "color_palette"]
            required = ["type", "desc"]
        elif element_type == "text":
            allowed = ["type", "bbox", "text", "desc", "color_palette"]
            required = ["type", "text", "desc"]
        else:
            raise PromptValidationError(f"{path}.type must be 'obj' or 'text'")
        _validate_key_order(element, allowed, required, path)
        _non_empty_string(element["desc"], f"{path}.desc")
        if "bbox" in element:
            _validate_bbox(element["bbox"], f"{path}.bbox")
        elif element_type == "text":
            warnings.append(f"{path} has no bbox; critical text placement may drift")
        if element_type == "text":
            literal = _non_empty_string(element["text"], f"{path}.text")
            total_literal_text += len(literal)
            if len(literal) > 60:
                warnings.append(
                    f"{path}.text is longer than 60 characters; legibility may degrade"
                )
        if "color_palette" in element:
            _validate_palette(element["color_palette"], 5, f"{path}.color_palette")

    if total_literal_text > 120:
        warnings.append(
            "total literal on-image text exceeds 120 characters; use an editable overlay "
            "or split the design"
        )
    if "color_palette" not in style:
        warnings.append(
            "style_description has no color_palette; brand and grade coherence may drift"
        )
    aesthetics = style["aesthetics"].lower()
    if any(term in aesthetics for term in ("oversaturated", "over-saturated", "hyper-saturated")):
        warnings.append(
            "aesthetics requests aggressive saturation, which conflicts with the Taste "
            "Profile reject reflex"
        )
    return warnings


def validate_use_case(prompt: dict[str, Any], purpose: str) -> list[str]:
    warnings: list[str] = []
    elements = prompt["compositional_deconstruction"]["elements"]
    text_elements = [item for item in elements if item["type"] == "text"]
    if purpose in {"thumbnail", "title-card", "quote-card", "stat-card", "cta", "signage"}:
        if not text_elements:
            warnings.append(
                f"purpose '{purpose}' normally requires a literal text element; "
                "consider a text-free generator instead"
            )
    return warnings


def load_prompt(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PromptValidationError(f"could not read prompt: {exc}") from exc
    if len(raw) > MAX_PROMPT_BYTES:
        raise PromptValidationError(
            f"prompt exceeds the {MAX_PROMPT_BYTES}-byte safety limit"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptValidationError(f"prompt is not valid UTF-8 JSON: {exc}") from exc
    validate_prompt(value)
    return value


def prompt_digest(prompt: dict[str, Any]) -> str:
    compact = json.dumps(
        prompt, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(compact).hexdigest()


def prompt_summary(prompt: dict[str, Any]) -> dict[str, Any]:
    style = prompt["style_description"]
    composition = prompt["compositional_deconstruction"]
    objects = []
    text = []
    for element in composition["elements"]:
        item = {
            "bbox": element.get("bbox"),
            "description": element["desc"],
            "color_palette": element.get("color_palette", []),
        }
        if element["type"] == "text":
            item["text"] = element["text"]
            text.append(item)
        else:
            objects.append(item)
    return {
        "subject": prompt["high_level_description"],
        "background": composition["background"],
        "objects": objects,
        "literal_text": text,
        "style": {
            "aesthetics": style["aesthetics"],
            "lighting": style["lighting"],
            "medium": style["medium"],
            "photo": style.get("photo"),
            "art_style": style.get("art_style"),
            "color_palette": style.get("color_palette", []),
        },
    }


def aspect_ratio(resolution: str) -> str:
    width_text, height_text = resolution.split("x", 1)
    width, height = int(width_text), int(height_text)
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def encode_multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----EditingOS{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"\r\n'
                    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                ).encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), boundary


def _read_limited(response: Any, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise IdeogramApiError(f"response exceeded the {limit}-byte safety limit")
    return body


def post_generation(
    api_key: str,
    prompt: dict[str, Any],
    resolution: str,
    rendering_speed: str,
    copyright_detection: bool,
    timeout: int,
) -> dict[str, Any]:
    fields = {
        "json_prompt": json.dumps(
            prompt, separators=(",", ":"), ensure_ascii=False
        ),
        "resolution": resolution,
        "rendering_speed": rendering_speed,
        "enable_copyright_detection": (
            "true" if copyright_detection else "false"
        ),
    }
    body, boundary = encode_multipart(fields)
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Editing-OS-Ideogram4/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _read_limited(response, MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read(64_000).decode("utf-8", "replace")
            parsed = json.loads(raw_error)
            message = parsed.get("error") if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError):
            message = None
        safe_message = message or "request rejected"
        raise IdeogramApiError(f"Ideogram API HTTP {exc.code}: {safe_message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IdeogramApiError(f"Ideogram API request failed: {exc}") from exc

    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdeogramApiError("Ideogram API returned invalid JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise IdeogramApiError("Ideogram API response is missing its data list")
    return result


def _target_for_index(output: Path, index: int) -> Path:
    if index == 0:
        return output
    return output.with_name(f"{output.stem}_{index + 1}{output.suffix}")


def _has_image_signature(first_bytes: bytes) -> bool:
    if first_bytes.startswith(IMAGE_SIGNATURES[0]):
        return True
    if first_bytes.startswith(IMAGE_SIGNATURES[1]):
        return True
    return (
        first_bytes.startswith(IMAGE_SIGNATURES[2])
        and len(first_bytes) >= 12
        and first_bytes[8:12] == b"WEBP"
    )


def download_image(
    url: str,
    target: Path,
    timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise IdeogramApiError("refused a non-HTTPS or malformed image URL")
    if target.exists() and not overwrite:
        raise IdeogramApiError(
            f"output already exists: {target}; pass --overwrite to replace it"
        )
    runtime.output(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Editing-OS-Ideogram4/1.0"},
    )
    temp_name: str | None = None
    size = 0
    digest = hashlib.sha256()
    first_bytes = b""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=target.parent, prefix=f".{target.name}."
            ) as temp:
                temp_name = temp.name
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise IdeogramApiError(
                            f"image exceeded the {MAX_IMAGE_BYTES}-byte safety limit"
                        )
                    if len(first_bytes) < 16:
                        first_bytes += chunk[: 16 - len(first_bytes)]
                    digest.update(chunk)
                    temp.write(chunk)
        if not _has_image_signature(first_bytes):
            raise IdeogramApiError("downloaded artifact is not PNG, JPEG, or WebP")
        os.replace(temp_name, target)
        temp_name = None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, IdeogramApiError):
            raise
        raise IdeogramApiError(f"image download failed: {exc}") from exc
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "path": str(target.resolve()),
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def write_json_atomic(path: Path, value: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise IdeogramApiError(
            f"metadata already exists: {path}; pass --overwrite to replace it"
        )
    runtime.output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
        ) as temp:
            temp_name = temp.name
            json.dump(value, temp, indent=2, ensure_ascii=False)
            temp.write("\n")
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def build_metadata(
    args: argparse.Namespace,
    prompt: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    unit_cost = SPEED_COST_USD[args.speed]
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "Ideogram",
        "model": "Ideogram 4.0 hosted API",
        "project": args.project,
        "purpose": args.purpose,
        "platform": args.platform,
        "request": {
            "endpoint": API_URL,
            "rendering_speed": args.speed,
            "resolution": args.resolution,
            "aspect_ratio": aspect_ratio(args.resolution),
            "copyright_detection": args.copyright_detection,
            "prompt_sha256": prompt_digest(prompt),
            "prompt": prompt,
            "summary": prompt_summary(prompt),
        },
        "cost": {
            "currency": "USD",
            "estimated_outputs": 1,
            "unit_cost_usd": unit_cost,
            "estimated_cost_usd": unit_cost,
            "approved_max_cost_usd": args.max_cost_usd,
            "pricing_checked": "2026-07-23",
            "pricing_source": PRICING_URL,
        },
        "rights": {
            "route": "hosted_api",
            "note": (
                "Production/commercial use is routed through the hosted API. "
                "Usage remains subject to the account's Ideogram agreement and policy."
            ),
            "terms_source": API_TERMS_URL,
        },
        "provenance": {
            "api_documentation": API_DOC_URL,
            "secret_reference": SECRET_ENV,
            "seed_control": (
                "The hosted V4 generate request does not expose an input seed. "
                "Returned seeds are recorded per output."
            ),
        },
        "warnings": warnings,
        "executed": False,
        "result": None,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or generate a production image with Ideogram 4's hosted API. "
            "Dry-run is the default."
        )
    )
    parser.add_argument("--prompt-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project", default=None)
    parser.add_argument("--purpose", required=True, choices=PURPOSES)
    parser.add_argument("--platform", required=True)
    parser.add_argument(
        "--resolution",
        default="2048x2048",
        choices=SUPPORTED_RESOLUTIONS,
    )
    parser.add_argument(
        "--speed",
        default="DEFAULT",
        choices=tuple(SPEED_COST_USD),
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=None,
        help="Required for --execute; must cover the current per-image tier price.",
    )
    parser.add_argument(
        "--metadata-out",
        type=Path,
        default=None,
        help="Default: <output>.ideogram.json",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Make the paid network request. Without this flag, only validate and plan.",
    )
    parser.add_argument(
        "--acknowledge-api-terms",
        action="store_true",
        help="Confirm the account's Ideogram API agreement/policy governs this use.",
    )
    parser.add_argument(
        "--no-copyright-detection",
        dest="copyright_detection",
        action="store_false",
        help="Disable the API copyright check (enabled by default).",
    )
    parser.set_defaults(copyright_detection=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    runtime.guard_args(args, ("output", "metadata_out"))

    if args.output.suffix.lower() != ".png":
        parser.error("--output must use a .png extension (the adapter does not transcode)")
    if args.timeout < 1 or args.timeout > 1800:
        parser.error("--timeout must be between 1 and 1800 seconds")

    try:
        prompt = load_prompt(args.prompt_json)
        warnings = validate_prompt(prompt)
        warnings.extend(validate_use_case(prompt, args.purpose))
    except PromptValidationError as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        return 2

    metadata = build_metadata(args, prompt, warnings)
    unit_cost = SPEED_COST_USD[args.speed]
    metadata_path = args.metadata_out or args.output.with_suffix(
        args.output.suffix + ".ideogram.json"
    )

    if not args.execute:
        print(json.dumps(metadata, indent=2, ensure_ascii=False))
        print(
            "\nDRY RUN: validation passed; no API request was made and no cost was incurred.",
            file=sys.stderr,
        )
        return 0

    if not args.acknowledge_api_terms:
        print(
            "EXECUTION BLOCKED: pass --acknowledge-api-terms after confirming the "
            "Ideogram agreement/policy for this project.",
            file=sys.stderr,
        )
        return 2
    if args.max_cost_usd is None:
        print(
            f"EXECUTION BLOCKED: pass --max-cost-usd of at least {unit_cost:.2f}.",
            file=sys.stderr,
        )
        return 2
    if args.max_cost_usd < unit_cost:
        print(
            f"EXECUTION BLOCKED: {args.speed} costs ${unit_cost:.2f}; "
            f"approved maximum is ${args.max_cost_usd:.2f}.",
            file=sys.stderr,
        )
        return 2
    api_key = os.environ.get(SECRET_ENV, "").strip()
    if not api_key:
        print(
            f"EXECUTION BLOCKED: {SECRET_ENV} is not present in the process environment.",
            file=sys.stderr,
        )
        return 2
    if args.output.exists() and not args.overwrite:
        print(
            f"EXECUTION BLOCKED: output already exists: {args.output}",
            file=sys.stderr,
        )
        return 2
    if metadata_path.exists() and not args.overwrite:
        print(
            f"EXECUTION BLOCKED: metadata already exists: {metadata_path}",
            file=sys.stderr,
        )
        return 2

    try:
        response = post_generation(
            api_key=api_key,
            prompt=prompt,
            resolution=args.resolution,
            rendering_speed=args.speed,
            copyright_detection=args.copyright_detection,
            timeout=args.timeout,
        )
        outputs: list[dict[str, Any]] = []
        for index, image in enumerate(response["data"]):
            if not isinstance(image, dict):
                raise IdeogramApiError("Ideogram API returned a malformed image record")
            if image.get("is_image_safe") is not True:
                raise IdeogramApiError(
                    f"output {index + 1} did not pass the API safety check"
                )
            url = image.get("url")
            if not isinstance(url, str) or not url:
                raise IdeogramApiError(
                    f"output {index + 1} is missing its ephemeral download URL"
                )
            artifact = download_image(
                url,
                _target_for_index(args.output, index),
                timeout=args.timeout,
                overwrite=args.overwrite,
            )
            artifact.update(
                {
                    "resolution": image.get("resolution"),
                    "seed": image.get("seed"),
                    "is_image_safe": image.get("is_image_safe"),
                }
            )
            outputs.append(artifact)
        if not outputs:
            raise IdeogramApiError("Ideogram API returned no downloadable outputs")
    except IdeogramApiError as exc:
        print(f"GENERATION ERROR: {exc}", file=sys.stderr)
        return 1

    metadata["executed"] = True
    metadata["result"] = {
        "created": response.get("created"),
        "response_type": response.get("response_type"),
        "outputs": outputs,
        "actual_output_count": len(outputs),
        "estimated_actual_cost_usd": round(unit_cost * len(outputs), 2),
    }
    try:
        write_json_atomic(metadata_path, metadata, overwrite=args.overwrite)
    except IdeogramApiError as exc:
        print(f"METADATA ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "outputs": [item["path"] for item in outputs],
                "metadata": str(metadata_path.resolve()),
                "estimated_actual_cost_usd": metadata["result"][
                    "estimated_actual_cost_usd"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

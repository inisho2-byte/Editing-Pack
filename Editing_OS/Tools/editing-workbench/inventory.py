"""Read every eligible source completely; report evidence depth, never infer readiness."""
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
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
sys.dont_write_bytecode = True

PRUNE = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
         ".thumbnails", ".pytest_cache", ".next", "target", "site-packages"}
TEXT = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".py", ".ts", ".tsx",
        ".js", ".jsx", ".toml", ".css", ".sh", ".ps1", ".ass", ".srt", ".vtt"}


class Scenes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scenes = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-start" in a and ("scene" in a.get("id", "").lower() or
                                  "data-composition-id" in a or "data-duration" in a):
            self.scenes.append({"tag": tag, "id": a.get("id"),
                                "start": a.get("data-start"), "duration": a.get("data-duration"),
                                "media_start": a.get("data-media-start"),
                                "track": a.get("data-track-index")})


def category(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    name = path.name.lower()
    if name == "skill.md":
        return "skill"
    if "/schemas/" in relative:
        return "schema"
    if "/examples/" in relative and "Editing_OS/Tools/" not in relative:
        return "contract-example"
    if path.suffix == ".html" and ("videos/" in relative or "template" in relative.lower()):
        return "composition-or-template"
    if "pipeline" in relative.lower() and path.suffix in {".json", ".yaml", ".yml"}:
        return "workflow"
    if "template" in relative.lower() and path.suffix in TEXT:
        return "template"
    if relative.startswith("Editing_OS/Skills/") or path.name == "AGENTS.md":
        return "instruction"
    if path.suffix == ".md" and "/Tools/" not in relative and relative.startswith("Editing_OS/"):
        return "owned-component-document"
    if "graphics-plan" in name or "storyboard" in name or "scene" in name:
        return "scene-plan"
    return "supporting-source"


def role(path: str) -> str:
    if "/Tools/" in path:
        return "third-party-specialist-reference"
    if "/Archive/" in path or "/Audits/" in path or "/Case studies/" in path:
        return "historical-evidence"
    if path.startswith("videos/"):
        return "project-specific-material"
    return "owned-system"


def inspect_links(text: str, path: Path, kit: Path, toolkit: Path) -> list[dict]:
    findings = []
    targets = re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", text)
    for target in targets:
        target = target.strip().strip("<>").split(' "')[0]
        if not target or target.startswith(("http:", "https:", "mailto:", "#", "data:", "app:", "codex:")):
            continue
        target = unquote(target.split("#")[0])
        if not target or any(c in target for c in ["*", "$", "{", "}", "<", ">"]):
            continue
        resolved = path.parent / target
        if not resolved.exists():
            findings.append({"kind": "markdown-target-not-found", "target": target,
                             "scope": role(path.relative_to(kit).as_posix())})
    for link in re.findall(r"\[\[([^\]\n]+)\]\]", text):
        target = link.split("|")[0].split("#")[0]
        if "/" not in target:
            continue  # Vault name lookup is intentionally a separate concern.
        options = [toolkit / target, kit / target, path.parent / target]
        if not any(p.exists() or p.with_suffix(".md").exists() for p in options):
            findings.append({"kind": "wikilink-target-not-found", "target": target,
                             "scope": role(path.relative_to(kit).as_posix())})
    return findings


def inspect_component(path: Path, text: str, kit: Path, toolkit: Path) -> dict:
    relative = path.relative_to(kit).as_posix()
    headers = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    descriptions = re.findall(r"^description:\s*(.+)$", text, re.MULTILINE)
    fields = {}
    for label, pattern in {
        "inputs": r"input|source|brief|transcript|audio|asset",
        "outputs": r"output|emit|deliver|artifact|render",
        "dependencies": r"dependenc|requirement|install|prerequisite|ffmpeg|python|node",
        "workflow": r"workflow|pipeline|step|routing|phase",
        "quality": r"quality|validat|review|check|test|failure",
    }.items():
        fields[label] = [h for h in headers if re.search(pattern, h, re.I)]
    scenes = []
    if path.suffix == ".html":
        parser = Scenes()
        parser.feed(text)
        scenes = parser.scenes
    json_status = None
    if path.suffix == ".json":
        try:
            payload = json.loads(text)
            json_status = "parsed"
            if isinstance(payload, dict) and isinstance(payload.get("cues"), list):
                scenes.extend({"id": cue.get("id"), "type": cue.get("graphic_type", cue.get("type")),
                               "start": cue.get("start_sec"), "end": cue.get("end_sec"),
                               "anchor": cue.get("anchor_sec")}
                              for cue in payload["cues"] if isinstance(cue, dict))
        except json.JSONDecodeError as exc:
            json_status = f"invalid at line {exc.lineno}"
    warnings = []
    if "setInterval(" in text or "Date.now(" in text or "Math.random(" in text:
        warnings.append("Seek/determinism review required; interactive/sample code may be intentional")
    if "SQLite" in text or "sqlite" in text:
        warnings.append("Filesystem evidence boundary: machine orchestration state is not publication authority")
    if "--apply-edits" in text and "/Video editing engine/" in relative:
        warnings.append("Direct nested-engine execution is diagnostic; production requires the owned adapter")
    timing_findings = []
    for item in scenes:
        try:
            start = float(item["start"])
            duration = float(item["duration"]) if "duration" in item else float(item["end"]) - start
            if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
                timing_findings.append({"id": item.get("id"), "issue": "invalid/nonpositive scene interval"})
            if item.get("anchor") is not None and not start <= float(item["anchor"]) <= start + duration:
                timing_findings.append({"id": item.get("id"), "issue": "anchor outside interval"})
        except (TypeError, ValueError, KeyError):
            timing_findings.append({"id": item.get("id"), "issue": "timing requires contextual evaluation"})
    ownership = role(relative)
    return {"path": relative, "category": category(path, kit), "ownership": role(relative),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "characters": len(text),
            "purpose_hint": descriptions[0] if descriptions else (headers[0] if headers else "Requires contextual review"),
            "documented_sections": fields, "json_check": json_status,
            "scene_items": scenes, "scene_timing_findings": timing_findings,
            "interface_attention": [label for label, sections in fields.items() if not sections],
            "operational_status": ("reference-only; activation requires applicable contract checks"
                                   if ownership == "third-party-specialist-reference" else
                                   "historical/project-specific; not universal production authority"
                                   if ownership in {"historical-evidence", "project-specific-material"} else
                                   "owned; execution/review evidence recorded separately"),
            "reference_findings": inspect_links(text, path, kit, toolkit),
            "boundary_findings": warnings, "coverage": "complete-file-machine-inspection",
            "semantic_human_review": False, "execution_verified": False,
            "publication_ready": False}


def inventory(kit: Path, toolkit: Path) -> dict:
    files, components, failures = [], [], []
    for folder, dirs, names in os.walk(kit, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in PRUNE and
                         not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.suffix.lower() not in TEXT or name in {"package-lock.json", "bun.lock", "pnpm-lock.yaml"}:
                continue
            if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
                failures.append({"path": str(path.relative_to(kit)), "reason": "symlink or source over 8 MiB"})
                continue
            try:
                raw = path.read_bytes()
                try:
                    text = raw.decode("utf-8-sig")
                    encoding = "utf-8-sig"
                except UnicodeError:
                    # Vendor legal text may use Windows ANSI. Preserve bytes/hash and label decoding.
                    text = raw.decode("cp1252")
                    encoding = "cp1252"
            except (UnicodeError, OSError) as exc:
                failures.append({"path": str(path.relative_to(kit)), "reason": str(exc)})
                continue
            rel = path.relative_to(kit).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": rel, "sha256": digest, "characters": len(text),
                          "category": category(path, kit), "encoding": encoding})
            if category(path, kit) != "supporting-source":
                components.append(inspect_component(path, text, kit, toolkit))
    groups = {}
    for component in components:
        groups.setdefault(component["sha256"], []).append(component["path"])
    for component in components:
        component["identical_copies"] = [p for p in groups[component["sha256"]] if p != component["path"]]
    return {"schema": "editing-component-register/v1", "kit": str(kit),
            "summary": dict(Counter(c["category"] for c in components)),
            "source_files": files, "components": components, "read_failures": failures,
            "exclusions": sorted(PRUNE),
            "limits": ["Complete-file machine inspection does not mean semantic or human review.",
                       "Per-component execution and encoded scene review remain separate evidence.",
                       "Binary assets are not decoded by this inventory; ownership/licensing is not inferred."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path)
    parser.add_argument("--reference-root", dest="toolkit", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--index", type=Path, help="Readable individual component index")
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    args.kit = args.kit or runtime.root()
    args.toolkit = args.toolkit or args.kit
    runtime.guard_args(args, ("out", "index"))
    result = inventory(args.kit.resolve(), args.toolkit.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.index:
        lines = ["# Individual editing component index", "",
                 "Generated by the owned inventory tool. Complete-file machine inspection only;",
                 "semantic, execution, licensing and publication approval are separate evidence.", "",
                 "Missing section headings indicate contextual review, not necessarily a missing capability.", "",
                 "| Component | Kind / ownership | Purpose hint | Individual diagnostics |",
                 "|---|---|---|---|"]
        for component in result["components"]:
            target = os.path.relpath(args.kit / component["path"], args.index.parent).replace("\\", "/")
            hint = component["purpose_hint"].replace("|", "\\|").replace("\n", " ")[:220]
            diagnostics = (f"{len(component['reference_findings'])} link findings; "
                           f"{len(component['scene_timing_findings'])} timing findings; "
                           f"{len(component['boundary_findings'])} boundary notes; "
                           "sections needing context: " + ", ".join(component["interface_attention"]))
            lines.append(f"| [{component['path']}](<{target}>) | {component['category']} / "
                         f"{component['ownership']} | {hint} | {diagnostics} |")
        args.index.parent.mkdir(parents=True, exist_ok=True)
        args.index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"source_files": len(result["source_files"]),
                      "components": len(result["components"]), "summary": result["summary"],
                      "read_failures": len(result["read_failures"])}))
    return 1 if result["read_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

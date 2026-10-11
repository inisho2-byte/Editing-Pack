"""Deterministic graphics compositor for the Video Editing OS.

Two entry paths are supported:

* ``title_card`` preserves the small legacy API used by the sibling editing
  engine.
* ``plan_graphics`` + ``write_project`` creates a transcript-aware graphics
  package with semantic cards, exact word anchors, varied speaker layouts,
  local assets, a paused master timeline, and a machine-readable QA report.

Captions remain the Captions_engine's responsibility.  This engine reserves
their region and refuses collisions rather than attempting to render them.
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
import html
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import math
import re
from pathlib import Path
from typing import Any, Mapping

try:  # Package import when discovered by a test runner.
    from .planner import GraphicCue, GraphicsPlan, assert_plan_valid, plan_graphics
except ImportError:  # Direct ``python compose.py`` and sibling-engine import.
    from planner import GraphicCue, GraphicsPlan, assert_plan_valid, plan_graphics


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ENGINE_DIR = Path(__file__).resolve().parent
EDITING_OS_DIR = ENGINE_DIR.parents[2]
CHECK_TIMEOUT_SECONDS = 180
MIN_RENDER_TIMEOUT_SECONDS = 3600
RENDER_TIMEOUT_PER_MEDIA_SECOND = 20
RENDER_TIMEOUT_OVERHEAD_SECONDS = 300



def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _css(value: str) -> str:
    """Allow only plain CSS color/font tokens from the internal theme table."""
    return re_safe(value)


def re_safe(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in "#(),.-_ %'")


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _stage_runtime(project_dir: Path) -> None:
    project_dir = runtime.output(project_dir)
    gsap = Path(runtime.tool("gsap_runtime"))
    fonts = [(Path(runtime.tool("inter_regular_font")), "Inter-400-latin.woff2"),
             (Path(runtime.tool("inter_bold_font")), "Inter-700-latin.woff2")]
    manifest = json.loads((runtime.root() / "config/tools.manifest.json").read_text(encoding="utf-8"))
    pins = {item["id"]: item for item in manifest["tools"]}
    for source, expected in [(gsap, pins["gsap"]["asset_sha256"]["dist/gsap.min.js"]),
                             (fonts[0][0], pins["inter"]["asset_sha256"]["files/inter-latin-400-normal.woff2"]),
                             (fonts[1][0], pins["inter"]["asset_sha256"]["files/inter-latin-700-normal.woff2"])]:
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise runtime.ConfigurationError("Runtime asset differs from the documented known-source package; reinstall the pinned package")
    notices = []
    for font, _ in fonts:
        notice = font.parent.parent / "LICENSE"
        if not notice.is_file():
            raise runtime.ConfigurationError("Inter must come from its known-source package with LICENSE beside files/")
        if hashlib.sha256(notice.read_bytes()).hexdigest() != pins["inter"]["asset_sha256"]["LICENSE"]:
            raise runtime.ConfigurationError("Inter license differs from the selected package notice")
        notices.append(notice.read_text(encoding="utf-8"))
    (project_dir / "vendor").mkdir(parents=True, exist_ok=True)
    (project_dir / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(gsap, project_dir / "vendor/gsap.min.js")
    for font, name in fonts:
        shutil.copyfile(font, project_dir / "fonts" / name)
    (project_dir / "fonts/LICENSE.txt").write_text(notices[0], encoding="utf-8")
    (project_dir / "vendor/NOTICE.txt").write_text(
        "GSAP retains its embedded GreenSock copyright and custom license notice. "
        "Terms: https://gsap.com/standard-license/. Not covered by toolkit MIT.\n", encoding="utf-8")
    ledger = {"gsap": {"sha256": hashlib.sha256(gsap.read_bytes()).hexdigest(), "license": "GSAP Standard License"},
              "fonts": [{"file": name, "sha256": hashlib.sha256(font.read_bytes()).hexdigest(), "license": "OFL-1.1"} for font, name in fonts]}
    (project_dir / "runtime-assets.json").write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _theme_css(theme: Mapping[str, Any]) -> str:
    accents = list(theme.get("accents") or ["#3DD6D0"])
    while len(accents) < 4:
        accents.append(accents[-1])
    return "\n".join(
        [
            f"--bg:{_css(theme.get('background', '#0E151C'))};",
            f"--surface:{_css(theme.get('surface', '#17222C'))};",
            f"--text:{_css(theme.get('text', '#F5F8FA'))};",
            f"--muted:{_css(theme.get('muted', '#A2B0BC'))};",
            f"--font:{_css(theme.get('font', 'Inter'))};",
        ]
        + [f"--accent-{index}:{_css(color)};" for index, color in enumerate(accents[:4])]
    )


def _asset_markup(cue: GraphicCue, asset_ref: str | None) -> str:
    if not asset_ref:
        return ""
    suffix = Path(asset_ref).suffix.lower()
    ref = _escape(asset_ref.replace("\\", "/"))
    if suffix in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        # HyperFrames media must be a direct composition-root child.  Video
        # assets are emitted separately by _asset_video_markup(); the card
        # retains only its frame/shade/copy shell.
        return ""
    return f'<img class="asset-media" src="{ref}" alt="" />'


def _is_video_ref(asset_ref: str | None) -> bool:
    return bool(asset_ref and Path(asset_ref).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"})


def _timed_markup(items: list[Any], class_name: str = "timed-item", start_index: int = 0) -> str:
    allow_overlap = (
        ' data-layout-allow-overlap="true"'
        if any(token in class_name for token in ("orbit-item", "stack-layer", "clarity-plane", "value-word"))
        else ""
    )
    return "".join(
        f'<div class="{class_name}" data-index="{index + start_index}"{allow_overlap}>{_escape(item)}</div>'
        for index, item in enumerate(items)
    )


def _visual_mode_inner(cue: GraphicCue) -> str | None:
    """Bespoke, narration-led stages used when a generic card is too templated.

    These modes stay data-driven so an editorial plan can author exact spoken
    anchors without embedding one-off timing logic in the HTML generator.
    """
    mode = str(cue.content.get("visualMode") or "").strip()
    if not mode:
        return None
    headline = _escape(cue.headline)
    kicker = _escape(cue.content.get("kicker", cue.graphic_type.replace("_", " ").upper()))
    items = list(cue.content.get("items") or [])

    if mode == "agentic-orbit":
        orbit_items = _timed_markup(items[:6], "timed-item orbit-item")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="mode-stage orbit-stage">
            <div class="ghost-word" data-layout-allow-overlap="true">AGENTIC</div><div class="orbit-ring ring-a"></div><div class="orbit-ring ring-b"></div>
            <div class="orbit-center"><small>BUILD WITH</small><strong>AGENTIC</strong><em>SYSTEMS</em></div>
            {orbit_items}
          </div>
          <h2 class="mode-footer">{headline}</h2>
        """
    if mode == "nontechnical-depth":
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="statement-stage">
            <div class="statement-small">NOT FROM A</div>
            <div class="depth-stack depth-technical" aria-label="TECHNICAL">
              <span class="depth-back depth-4" data-layout-allow-overlap="true">TECHNICAL</span><span class="depth-back depth-3" data-layout-allow-overlap="true">TECHNICAL</span>
              <span class="depth-back depth-2" data-layout-allow-overlap="true">TECHNICAL</span><span class="depth-back depth-1" data-layout-allow-overlap="true">TECHNICAL</span>
              <strong class="depth-front" data-layout-allow-overlap="true">TECHNICAL</strong>
            </div>
            <div class="statement-large" data-layout-allow-overlap="true">BACKGROUND</div>
            <div class="statement-chip timed-item" data-index="0">BEGINNER PERSPECTIVE</div>
          </div>
        """
    if mode == "app-architecture":
        nodes = _timed_markup(items[1:5], "timed-item architecture-node", start_index=1)
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="architecture-stage">
            <div class="architecture-grid"></div>
            <svg viewBox="0 0 760 650" aria-hidden="true">
              <path d="M380 325 C250 245 210 150 118 108"/><path d="M380 325 C510 245 560 150 650 112"/>
              <path d="M380 325 C250 410 200 500 108 548"/>
            </svg>
            <div class="timed-item architecture-core" data-index="0"><small>BUILD</small><strong>{_escape(items[0] if items else 'APP')}</strong></div>
            {nodes}
          </div>
          <h2 class="mode-footer architecture-footer">{headline}</h2>
        """
    if mode == "teaching-goal":
        phrase = _timed_markup(items[:4], "timed-item goal-phrase")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="goal-stage"><div class="goal-index">01 / SERIES GOAL</div>{phrase}<div class="goal-rule"></div></div>
        """
    if mode == "clarity-planes":
        planes = _timed_markup(items[:2], "timed-item clarity-plane")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="clarity-stage">{planes}<div class="clarity-arrow">→</div></div>
        """
    if mode == "key-terms-hit":
        words = _timed_markup(items[:2], "timed-item key-word")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="key-stage">{words}<div class="key-underline"></div></div>
        """
    if mode == "ai-tools-sequence":
        words = _timed_markup(items[:3], "timed-item ai-word")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="ai-stage">{words}</div>
          <div class="ai-method"><span>PROMPT</span><i>/</i><span>TEST</span><i>/</i><span>VERIFY</span></div>
        """
    if mode == "feature-stack":
        layers = _timed_markup(items[:3], "timed-item stack-layer")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <h2 class="stack-headline">{headline}</h2>
          <div class="stack-stage">{layers}<div class="stack-axis">FEATURE → TOOL → STACK</div></div>
        """
    if mode == "series-roadmap":
        chapters = _timed_markup(items[:3], "timed-item chapter-card")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <h2 class="series-headline">{headline}</h2>
          <div class="roadmap-stage"><div class="roadmap-line"></div>{chapters}</div>
        """
    if mode == "high-value-finale":
        words = _timed_markup(items[:4], "timed-item value-word")
        return f"""
          <div class="ambient-plane ambient-plane-a"></div><div class="ambient-plane ambient-plane-b"></div>
          <div class="kicker"><span></span>{kicker}</div>
          <div class="value-stage">{words}</div>
          <div class="value-chip">IN THE NEXT COMING DAYS</div>
        """
    return None


def _card_inner(cue: GraphicCue, asset_ref: str | None) -> str:
    visual_mode = _visual_mode_inner(cue)
    if visual_mode is not None:
        return visual_mode
    headline = _escape(cue.headline)
    detail = _escape(cue.detail)
    accent = cue.accent_index % 4
    kicker = _escape(cue.graphic_type.replace("_", " ").upper())

    if cue.graphic_type == "stat":
        value = _escape(cue.content.get("value", cue.headline))
        label = _escape(cue.content.get("label", cue.detail))
        proportion = cue.content.get("proportion")
        measure = ""
        if isinstance(proportion, (int, float)) and 0 <= float(proportion) <= 1:
            measure = (
                f'<div class="measure" data-proportion="{_fmt(float(proportion))}">'
                f'<i style="--measure-proportion:{_fmt(float(proportion))}"></i></div>'
            )
        return f"""
          <div class="kicker"><span></span>{kicker}</div>
          <div class="stat-value">{value}</div>
          <div class="stat-label">{label}</div>
          {measure}
        """
    if cue.graphic_type == "comparison":
        left = _escape(cue.content.get("left", "Current"))
        right = _escape(cue.content.get("right", "Better"))
        return f"""
          <div class="kicker"><span></span>COMPARE</div>
          <div class="comparison-grid">
            <div class="comparison-side" data-side="left"><small>01</small><strong>{left}</strong></div>
            <div class="comparison-axis"><i></i><b>→</b></div>
            <div class="comparison-side is-accent" data-side="right"><small>02</small><strong>{right}</strong></div>
          </div>
        """
    if cue.graphic_type == "process":
        steps = list(cue.content.get("steps") or [])[:3]
        step_markup = "".join(
            f'<div class="process-step"><b>{index + 1:02d}</b><span>{_escape(step)}</span></div>'
            for index, step in enumerate(steps)
        )
        return f"""
          <div class="kicker"><span></span>PROCESS</div>
          <h2>{headline}</h2>
          <div class="process-line">{step_markup}</div>
        """
    if cue.graphic_type == "concept_diagram":
        center = _escape(cue.content.get("center", cue.anchor_word))
        nodes = list(cue.content.get("nodes") or [])[:3]
        node_markup = "".join(
            f'<div class="diagram-node node-{index + 1}">{_escape(node)}</div>'
            for index, node in enumerate(nodes)
        )
        return f"""
          <div class="kicker"><span></span>IDEA MAP</div>
          <div class="diagram">
            <svg viewBox="0 0 600 420" aria-hidden="true">
              <path d="M300 84 C300 190 100 190 100 315" />
              <path d="M300 84 L300 315" />
              <path d="M300 84 C300 190 500 190 500 315" />
            </svg>
            <div class="diagram-center">{center}</div>{node_markup}
          </div>
          <h2 class="diagram-title">{headline}</h2>
        """
    if cue.graphic_type == "quote":
        return f"""
          <div class="quote-mark">“</div>
          <blockquote>{headline}</blockquote>
          <div class="quote-rule"></div>
        """
    if cue.graphic_type == "asset_focus":
        media = _asset_markup(cue, asset_ref)
        return f"""
          <div class="asset-frame">{media}<div class="asset-shade"></div></div>
          <div class="asset-copy" data-layout-allow-occlusion="true"><div class="kicker"><span></span>{kicker}</div><h2>{headline}</h2></div>
        """
    emphasis = _escape(cue.content.get("emphasis", ""))
    return f"""
      <div class="kicker"><span></span>{kicker}</div>
      <h2 class="keyword-title">{headline}</h2>
      <div class="keyword-rule"><i></i></div>
      {f'<div class="meaning-chip">{emphasis}</div>' if emphasis else ''}
    """


def _card_markup(cue: GraphicCue, asset_ref: str | None = None) -> str:
    bounds = cue.graphic_bounds
    media_class = " has-host-video" if _is_video_ref(asset_ref) else ""
    visual_mode = str(cue.content.get("visualMode") or "").strip()
    mode_class = f" mode-{re_safe(visual_mode)}" if visual_mode else ""
    return f"""
      <section id="{_escape(cue.id)}" class="graphic-card clip type-{_escape(cue.graphic_type)} layout-{_escape(cue.layout)}{media_class}{mode_class}"
        data-start="{_fmt(cue.start_sec)}" data-duration="{_fmt(cue.duration)}" data-track-index="3"
        data-anchor="{_fmt(cue.anchor_sec)}" data-anchor-word="{_escape(cue.anchor_word)}"
        style="left:{bounds.x}px;top:{bounds.y}px;width:{bounds.width}px;height:{bounds.height}px;--cue-accent:var(--accent-{cue.accent_index % 4});">
        <div class="graphic-shell" data-layout-allow-occlusion="true">{_card_inner(cue, asset_ref)}</div>
      </section>
    """


def _bounded_reveal_window(cue: GraphicCue, preferred_duration: float, *,
                           count: int = 1, preferred_stagger: float = 0.0) -> dict[str, Any]:
    """Scale one reveal so its last element resolves no later than the anchor.

    With zero lead the authored DOM is already the readable end state, so no
    entrance tween is emitted.  This is essential for a trigger on frame zero:
    a minimum-duration tween would make the meaning late by construction.
    """
    lead = max(0.0, cue.anchor_sec - cue.start_sec)
    count = max(1, int(count))
    preferred_total = max(0.0, preferred_duration) + max(0.0, preferred_stagger) * (count - 1)
    if lead <= 1e-6 or preferred_total <= 1e-9:
        return {
            "animated": False,
            "start": cue.anchor_sec,
            "duration": 0.0,
            "stagger": 0.0,
            "end": cue.anchor_sec,
        }
    scale = min(1.0, lead / preferred_total)
    duration = preferred_duration * scale
    stagger = preferred_stagger * scale
    total = duration + stagger * (count - 1)
    start = max(cue.start_sec, cue.anchor_sec - total)
    return {
        "animated": True,
        "start": start,
        "duration": duration,
        "stagger": stagger,
        "end": start + total,
    }


def _cue_reveal_schedule(cue: GraphicCue) -> dict[str, dict[str, Any]]:
    """Single source of truth for generator and trigger-deadline QA."""
    schedule = {
        "shell": _bounded_reveal_window(cue, 0.34),
        "managed-media": _bounded_reveal_window(cue, 0.28),
    }
    if cue.graphic_type == "stat":
        schedule["stat-value"] = _bounded_reveal_window(cue, 0.36)
        if isinstance(cue.content.get("proportion"), (int, float)):
            schedule["measure"] = _bounded_reveal_window(cue, 0.34)
    elif cue.graphic_type == "comparison":
        schedule["comparison-sides"] = _bounded_reveal_window(
            cue, 0.30, count=2, preferred_stagger=0.06
        )
        schedule["comparison-axis"] = _bounded_reveal_window(cue, 0.34)
    elif cue.graphic_type == "process":
        count = max(1, len(list(cue.content.get("steps") or [])[:3]))
        schedule["process-steps"] = _bounded_reveal_window(
            cue, 0.28, count=count, preferred_stagger=0.07
        )
    elif cue.graphic_type == "concept_diagram":
        schedule["diagram-path"] = _bounded_reveal_window(cue, 0.48)
        count = max(1, len(list(cue.content.get("nodes") or [])[:3]))
        schedule["diagram-nodes"] = _bounded_reveal_window(
            cue, 0.28, count=count, preferred_stagger=0.06
        )
    elif cue.graphic_type == "asset_focus":
        schedule["asset-copy"] = _bounded_reveal_window(cue, 0.34)
    elif cue.graphic_type == "quote":
        schedule["quote"] = _bounded_reveal_window(cue, 0.36)
    else:
        schedule["keyword-rule"] = _bounded_reveal_window(cue, 0.34)
    return schedule


def validate_reveal_deadlines(plan: GraphicsPlan) -> list[dict[str, Any]]:
    """Verify every generated meaning reveal resolves by its trigger word."""
    issues: list[dict[str, Any]] = []
    for cue in plan.cues:
        for element, window in _cue_reveal_schedule(cue).items():
            if window["start"] < cue.start_sec - 1e-6 or window["end"] > cue.anchor_sec + 1e-6:
                issues.append({
                    "severity": "error",
                    "code": "reveal_misses_anchor_deadline",
                    "cueId": cue.id,
                    "message": (
                        f"{element} reveal {window['start']:.4f}..{window['end']:.4f} "
                        f"must stay inside cue start {cue.start_sec:.4f} and anchor {cue.anchor_sec:.4f}"
                    ),
                })
            if cue.anchor_sec <= cue.start_sec + 1e-6 and window["animated"]:
                issues.append({
                    "severity": "error",
                    "code": "zero_lead_reveal_not_static",
                    "cueId": cue.id,
                    "message": f"{element} must use its readable static end state at a zero-lead trigger",
                })
    return issues


def validate_engagement_contract(plan: GraphicsPlan) -> list[dict[str, Any]]:
    """Validate portrait scale and exact narration-led item anchors.

    Generic cards need no extra metadata. Bespoke ``visualMode`` stages do:
    every authored item must have one finite, monotonic anchor inside its cue.
    This keeps the engaging motion tied to speech instead of decorative time.
    """
    issues: list[dict[str, Any]] = []
    width = int(plan.composition["width"])
    height = int(plan.composition["height"])
    portrait = height > width
    for cue in plan.cues:
        def issue(severity: str, code: str, message: str) -> None:
            issues.append({
                "severity": severity,
                "code": code,
                "cueId": cue.id,
                "message": message,
            })

        mode = str(cue.content.get("visualMode") or "").strip()
        if portrait and cue.layout == "stage_pip" and cue.graphic_bounds.width < width * 0.65:
            issue(
                "error",
                "portrait_stage_too_narrow",
                "portrait stage_pip graphics must use at least 65% of the canvas width",
            )
        if not mode:
            continue
        items = list(cue.content.get("items") or [])
        anchors = list(cue.content.get("itemAnchors") or [])
        if not items:
            issue("error", "visual_mode_items_empty", f"visualMode {mode!r} has no semantic items")
            continue
        if len(anchors) != len(items):
            issue(
                "error",
                "visual_mode_anchor_count",
                f"visualMode {mode!r} has {len(items)} items but {len(anchors)} anchors",
            )
            continue
        previous: float | None = None
        for index, raw_anchor in enumerate(anchors):
            if not isinstance(raw_anchor, (int, float)) or not math.isfinite(float(raw_anchor)):
                issue("error", "visual_mode_anchor_invalid", f"item {index} anchor is not finite")
                continue
            anchor = float(raw_anchor)
            if not cue.start_sec <= anchor <= cue.end_sec:
                issue(
                    "error",
                    "visual_mode_anchor_outside_cue",
                    f"item {index} anchor {anchor:.4f}s is outside {cue.start_sec:.4f}..{cue.end_sec:.4f}s",
                )
            if previous is not None and anchor < previous:
                issue(
                    "error",
                    "visual_mode_anchors_not_monotonic",
                    f"item {index} anchor {anchor:.4f}s precedes {previous:.4f}s",
                )
            previous = anchor
    return issues


def _visual_mode_timeline(cue: GraphicCue, selector: str) -> list[str]:
    mode = str(cue.content.get("visualMode") or "").strip()
    if not mode:
        return []
    lines: list[str] = []
    anchors = list(cue.content.get("itemAnchors") or [])
    item_count = len(list(cue.content.get("items") or []))
    for index in range(item_count):
        anchor = float(anchors[index]) if index < len(anchors) else cue.anchor_sec + index * 0.12
        anchor = min(max(cue.start_sec, anchor), cue.end_sec - 0.12)
        direction = -1 if index % 2 == 0 else 1
        final_depth = 0
        final_rotation_x = 0
        final_rotation_y = 0
        if mode == "app-architecture" and index == 0:
            final_depth = 170
        elif mode == "clarity-planes":
            final_depth = -40 if index == 0 else 80
            final_rotation_y = 8 if index == 0 else -8
        elif mode == "feature-stack":
            final_depth = (-120, 0, 120)[min(index, 2)]
            final_rotation_x = 58
        lines.append(
            f"tl.fromTo({selector} + ' .timed-item[data-index=\"{index}\"]', "
            f"{{opacity:0, x:{direction * 34}, y:18, z:-120, rotationX:9, rotationY:{direction * 12}, scale:.88}}, "
            f"{{opacity:1, x:0, y:0, z:{final_depth}, rotationX:{final_rotation_x}, rotationY:{final_rotation_y}, scale:1, duration:.42, ease:'power4.out'}}, {_fmt(anchor)});"
        )
    if mode == "agentic-orbit":
        orbit_start = min(cue.end_sec - 0.4, max(cue.anchor_sec + 0.15, cue.start_sec + 0.2))
        orbit_duration = max(0.3, cue.end_sec - orbit_start - 0.22)
        lines.append(
            f"tl.fromTo({selector} + ' .orbit-ring', {{opacity:0, rotationX:58, rotationZ:-8}}, "
            f"{{opacity:.64, rotationX:66, rotationZ:4, duration:.7, ease:'expo.out'}}, {_fmt(cue.anchor_sec)});"
        )
        lines.append(
            f"tl.to({selector} + ' .orbit-stage', {{rotationY:4, rotationX:-2, duration:{_fmt(orbit_duration)}, ease:'sine.inOut'}}, {_fmt(orbit_start)});"
        )
    elif mode == "nontechnical-depth":
        depth_at = max(cue.start_sec, cue.anchor_sec - 0.26)
        lines.append(
            f"tl.fromTo({selector} + ' .depth-back', {{opacity:0, x:0, y:0}}, "
            f"{{opacity:.72, x:10, y:10, duration:.5, stagger:.045, ease:'power3.out'}}, {_fmt(depth_at)});"
        )
        lines.append(
            f"tl.fromTo({selector} + ' .depth-front', {{opacity:0, y:20, z:-90}}, "
            f"{{opacity:1, y:0, z:0, duration:.52, ease:'expo.out'}}, {_fmt(depth_at + 0.08)});"
        )
    elif mode == "app-architecture":
        node_anchors = anchors[1:5]
        for index, anchor in enumerate(node_anchors):
            path_anchor = max(cue.start_sec, float(anchor) - 0.12)
            lines.append(
                f"tl.fromTo({selector} + ' .architecture-stage path:nth-of-type({index + 1})', "
                f"{{strokeDasharray:900, strokeDashoffset:900}}, "
                f"{{strokeDashoffset:0, duration:.48, ease:'power2.inOut'}}, {_fmt(path_anchor)});"
            )
        lines.append(
            f"tl.to({selector} + ' .architecture-grid', {{backgroundPosition:'42px 42px', duration:{_fmt(max(.5, cue.duration - .8))}, ease:'none'}}, {_fmt(cue.start_sec + .4)});"
        )
    elif mode == "teaching-goal":
        lines.append(
            f"tl.fromTo({selector} + ' .goal-rule', {{scaleX:0}}, {{scaleX:1, duration:.72, ease:'power2.inOut'}}, {_fmt(cue.anchor_sec)});"
        )
    elif mode == "clarity-planes":
        struggle_at = float(cue.content.get("struggleAnchor", cue.end_sec - 0.7))
        lines.append(
            f"tl.to({selector} + ' .clarity-plane[data-index=\"0\"]', {{z:-180, rotationY:-12, opacity:.42, duration:.64, ease:'power3.in'}}, {_fmt(struggle_at)});"
        )
    elif mode == "key-terms-hit":
        lines.append(
            f"tl.fromTo({selector} + ' .key-underline', {{scaleX:0}}, {{scaleX:1, duration:.48, ease:'expo.out'}}, {_fmt(cue.anchor_sec)});"
        )
    elif mode == "feature-stack":
        lines.append(
            f"tl.to({selector} + ' .stack-stage', {{rotationY:-4, rotationX:2, duration:{_fmt(max(.5, cue.duration - .9))}, ease:'sine.inOut'}}, {_fmt(cue.start_sec + .5)});"
        )
    elif mode == "series-roadmap":
        lines.append(
            f"tl.fromTo({selector} + ' .roadmap-line', {{scaleY:0}}, {{scaleY:1, duration:.68, ease:'power2.inOut'}}, {_fmt(cue.anchor_sec)});"
        )
    elif mode == "high-value-finale":
        high_at = float(anchors[1]) if len(anchors) > 1 else cue.anchor_sec + 1.8
        lines.append(
            f"tl.fromTo({selector} + ' .value-stage', {{rotationY:-4}}, {{rotationY:3, duration:{_fmt(max(.5, high_at - cue.anchor_sec))}, ease:'sine.inOut'}}, {_fmt(cue.anchor_sec)});"
        )
    ambient_start = min(cue.end_sec - 0.35, max(cue.anchor_sec + 0.15, cue.start_sec + 0.25))
    ambient_duration = max(0.24, cue.end_sec - ambient_start - 0.22)
    lines.append(
        f"tl.fromTo({selector} + ' .ambient-plane-a', {{x:-8, y:6, rotationZ:-2}}, "
        f"{{x:18, y:-12, rotationZ:3, duration:{_fmt(ambient_duration)}, ease:'sine.inOut'}}, {_fmt(ambient_start)});"
    )
    lines.append(
        f"tl.fromTo({selector} + ' .ambient-plane-b', {{x:10, y:-8}}, "
        f"{{x:-14, y:12, duration:{_fmt(ambient_duration)}, ease:'sine.inOut'}}, {_fmt(ambient_start)});"
    )
    return lines


def _card_timeline(cue: GraphicCue) -> str:
    selector = json.dumps(f"#{cue.id}")
    start = cue.start_sec
    end = cue.end_sec
    schedule = _cue_reveal_schedule(cue)
    exit_duration = min(0.30, max(0.18, cue.duration * 0.12))
    exit_at = max(start, end - exit_duration)
    lines: list[str] = []
    shell = schedule["shell"]
    if shell["animated"]:
        lines.append(
            f"tl.fromTo({selector} + ' .graphic-shell', {{opacity:0, y:28, scale:.96, rotationX:6, rotationY:-3, transformPerspective:1400}}, "
            f"{{opacity:1, y:0, scale:1, rotationX:0, rotationY:0, duration:{_fmt(shell['duration'])}, ease:'power4.out'}}, {_fmt(shell['start'])});"
        )
    mode = str(cue.content.get("visualMode") or "").strip()
    if mode:
        lines.extend(_visual_mode_timeline(cue, selector))
    elif cue.graphic_type == "stat":
        reveal = schedule["stat-value"]
        if reveal["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .stat-value', {{opacity:0, y:28}}, "
                f"{{opacity:1, y:0, duration:{_fmt(reveal['duration'])}, ease:'power3.out'}}, {_fmt(reveal['start'])});"
            )
        proportion = cue.content.get("proportion")
        measure = schedule.get("measure")
        if measure and measure["animated"] and isinstance(proportion, (int, float)) and 0 <= float(proportion) <= 1:
            lines.append(
                f"tl.fromTo({selector} + ' .measure i', {{scaleX:0}}, "
                f"{{scaleX:{_fmt(float(proportion))}, duration:{_fmt(measure['duration'])}, ease:'power2.inOut'}}, {_fmt(measure['start'])});"
            )
    elif cue.graphic_type == "comparison":
        sides = schedule["comparison-sides"]
        axis = schedule["comparison-axis"]
        if sides["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .comparison-side', {{opacity:0, y:18}}, "
                f"{{opacity:1, y:0, duration:{_fmt(sides['duration'])}, stagger:{_fmt(sides['stagger'])}, ease:'power3.out'}}, {_fmt(sides['start'])});"
            )
        if axis["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .comparison-axis i', {{scaleY:0}}, "
                f"{{scaleY:1, duration:{_fmt(axis['duration'])}, ease:'power2.inOut'}}, {_fmt(axis['start'])});"
            )
    elif cue.graphic_type == "process":
        steps = schedule["process-steps"]
        if steps["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .process-step', {{opacity:0, y:18}}, "
                f"{{opacity:1, y:0, duration:{_fmt(steps['duration'])}, stagger:{_fmt(steps['stagger'])}, ease:'power3.out'}}, {_fmt(steps['start'])});"
            )
    elif cue.graphic_type == "concept_diagram":
        path = schedule["diagram-path"]
        nodes = schedule["diagram-nodes"]
        if path["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .diagram path', {{strokeDasharray:700, strokeDashoffset:700}}, "
                f"{{strokeDashoffset:0, duration:{_fmt(path['duration'])}, ease:'power2.inOut'}}, {_fmt(path['start'])});"
            )
        if nodes["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .diagram-node', {{opacity:0, scale:.94}}, "
                f"{{opacity:1, scale:1, duration:{_fmt(nodes['duration'])}, stagger:{_fmt(nodes['stagger'])}, ease:'power3.out'}}, {_fmt(nodes['start'])});"
            )
    elif cue.graphic_type == "asset_focus":
        copy = schedule["asset-copy"]
        if copy["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .asset-copy', {{opacity:0, y:18}}, "
                f"{{opacity:1, y:0, duration:{_fmt(copy['duration'])}, ease:'power3.out'}}, {_fmt(copy['start'])});"
            )
    elif cue.graphic_type == "quote":
        quote = schedule["quote"]
        if quote["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' blockquote', {{opacity:0, y:18}}, "
                f"{{opacity:1, y:0, duration:{_fmt(quote['duration'])}, ease:'power3.out'}}, {_fmt(quote['start'])});"
            )
    else:
        rule = schedule["keyword-rule"]
        if rule["animated"]:
            lines.append(
                f"tl.fromTo({selector} + ' .keyword-rule i', {{scaleX:0}}, "
                f"{{scaleX:1, duration:{_fmt(rule['duration'])}, ease:'power2.inOut'}}, {_fmt(rule['start'])});"
            )
    lines.extend([
        f"tl.to({selector} + ' .graphic-shell', {{opacity:0, y:-10, duration:{_fmt(exit_duration)}, ease:'power2.in'}}, {_fmt(exit_at)});",
        f"tl.set({selector} + ' .graphic-shell', {{opacity:0}}, {_fmt(end)});",
    ])
    return "\n      ".join(lines)


def _source_media_markup(plan: GraphicsPlan, source_ref: str) -> str:
    """Emit framework-owned A-roll, audio, and fixed speaker windows.

    All media nodes are direct root children.  Speaker windows use authored
    fixed geometry plus opacity/scale motion, avoiding left/top/width/height
    tweens and the reflow/jank they caused in the previous wrapped-video path.
    """
    duration = float(plan.composition["durationSeconds"])
    ref = _escape(source_ref.replace("\\", "/"))
    parts = [f"""
      <video id="source-video" class="source-video" src="{ref}" muted playsinline preload="auto"
        data-start="0" data-duration="{_fmt(duration)}" data-track-index="0"></video>
      <audio id="source-audio" src="{ref}" preload="auto"
        data-start="0" data-duration="{_fmt(duration)}" data-track-index="10" data-volume="1"></audio>"""]
    for cue in plan.cues:
        if cue.layout in {"stage_pip", "side_panel", "full_stage"}:
            parts.append(f"""
      <div id="backdrop-{_escape(cue.id)}" class="cue-backdrop clip"
        data-start="{_fmt(cue.start_sec)}" data-duration="{_fmt(cue.duration)}" data-track-index="1"
        style="opacity:0;--cue-accent:var(--accent-{cue.accent_index % 4});"></div>""")
        if not cue.speaker_bounds:
            continue
        bounds = cue.speaker_bounds
        radius = "50%" if cue.speaker_shape == "circle" else "28px"
        parts.append(f"""
      <video id="speaker-{_escape(cue.id)}" class="speaker-media" src="{ref}" muted playsinline preload="auto"
        data-start="{_fmt(cue.start_sec)}" data-duration="{_fmt(cue.duration)}"
        data-media-start="{_fmt(cue.start_sec)}" data-track-index="2"
        data-crop-verification="{_escape('verified' if cue.speaker_crop_status == 'verified' else 'unverified')}"
        style="left:{bounds.x}px;top:{bounds.y}px;width:{bounds.width}px;height:{bounds.height}px;border-radius:{radius};"></video>""")
    return "\n".join(parts)


def _asset_video_markup(plan: GraphicsPlan, asset_refs: Mapping[str, str]) -> str:
    parts: list[str] = []
    for cue in plan.cues:
        asset_ref = asset_refs.get(cue.id)
        if not _is_video_ref(asset_ref):
            continue
        bounds = cue.graphic_bounds
        ref = _escape(str(asset_ref).replace("\\", "/"))
        parts.append(f"""
      <video id="asset-video-{_escape(cue.id)}" class="asset-host-video" src="{ref}" muted playsinline preload="auto"
        data-start="{_fmt(cue.start_sec)}" data-duration="{_fmt(cue.duration)}"
        data-media-start="0" data-track-index="4"
        style="left:{bounds.x}px;top:{bounds.y}px;width:{bounds.width}px;height:{bounds.height}px;"></video>""")
    return "\n".join(parts)


def _managed_media_timeline(plan: GraphicsPlan, asset_refs: Mapping[str, str],
                            include_source: bool = False) -> str:
    lines: list[str] = []
    for cue in plan.cues:
        reveal = _bounded_reveal_window(cue, 0.28)
        if include_source and cue.layout in {"stage_pip", "side_panel", "full_stage"}:
            selector = json.dumps(f"#backdrop-{cue.id}")
            if reveal["animated"]:
                lines.append(
                    f"tl.fromTo({selector}, {{opacity:0}}, "
                    f"{{opacity:1, duration:{_fmt(reveal['duration'])}, ease:'power3.out'}}, {_fmt(reveal['start'])});"
                )
            exit_duration = min(0.28, max(0.0, cue.duration / 3))
            if exit_duration > 0:
                lines.append(
                    f"tl.to({selector}, {{opacity:0, duration:{_fmt(exit_duration)}, ease:'power2.in'}}, "
                    f"{_fmt(cue.end_sec - exit_duration)});"
                )
        if include_source and cue.speaker_bounds and reveal["animated"]:
            selector = json.dumps(f"#speaker-{cue.id}")
            lines.append(
                f"tl.fromTo({selector}, {{opacity:0, scale:.975}}, "
                f"{{opacity:1, scale:1, duration:{_fmt(reveal['duration'])}, ease:'power3.out'}}, {_fmt(reveal['start'])});"
            )
        if _is_video_ref(asset_refs.get(cue.id)) and reveal["animated"]:
            selector = json.dumps(f"#asset-video-{cue.id}")
            lines.append(
                f"tl.fromTo({selector}, {{opacity:0, scale:1.025}}, "
                f"{{opacity:1, scale:1, duration:{_fmt(reveal['duration'])}, ease:'power3.out'}}, {_fmt(reveal['start'])});"
            )
    return "\n      ".join(lines)


def build_composition(plan: GraphicsPlan, *, source_ref: str | None = None,
                      asset_refs: Mapping[str, str] | None = None) -> str:
    """Compile a validated graphics plan into one seek-safe HyperFrames page."""
    assert_plan_valid(plan)
    contract_issues = [*validate_reveal_deadlines(plan), *validate_engagement_contract(plan)]
    contract_errors = [item for item in contract_issues if item["severity"] == "error"]
    if contract_errors:
        rendered = "\n".join(f"- {item['code']}: {item['message']}" for item in contract_errors)
        raise ValueError(f"graphics timing/engagement contract failed QA:\n{rendered}")
    asset_refs = dict(asset_refs or {})
    composition = plan.composition
    width = int(composition["width"])
    height = int(composition["height"])
    duration = float(composition["durationSeconds"])
    fps = int(composition["fps"])
    cards = "\n".join(_card_markup(cue, asset_refs.get(cue.id)) for cue in plan.cues)
    card_timeline = "\n      ".join(_card_timeline(cue) for cue in plan.cues)
    media_markup = _asset_video_markup(plan, asset_refs)
    if source_ref:
        media_markup = "\n".join(filter(None, [_source_media_markup(plan, source_ref), media_markup]))
    media_timeline = _managed_media_timeline(plan, asset_refs, include_source=bool(source_ref))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={width},height={height}" />
  <style>
    @font-face {{ font-family:'Inter'; src:url('fonts/Inter-400-latin.woff2') format('woff2'); font-weight:400; font-display:block; }}
    @font-face {{ font-family:'Inter'; src:url('fonts/Inter-700-latin.woff2') format('woff2'); font-weight:700; font-display:block; }}
    :root {{ {_theme_css(plan.theme)} }}
    * {{ box-sizing:border-box; }}
    html,body {{ margin:0; width:{width}px; height:{height}px; overflow:hidden; background:var(--bg); font-family:var(--font),Arial,sans-serif; }}
    #stage {{ position:relative; width:100%; height:100%; overflow:hidden; isolation:isolate; background:var(--bg); color:var(--text); }}
    .stage-background {{ position:absolute; inset:0; width:{width}px; height:{height}px; z-index:0; background:var(--bg); }}
    .source-video {{ position:absolute; inset:0; display:block; width:{width}px; height:{height}px; object-fit:cover; object-position:50% 36%; z-index:1; }}
    .cue-backdrop {{ position:absolute; inset:0; width:{width}px; height:{height}px; z-index:1; pointer-events:none; background:radial-gradient(circle at 78% 18%,color-mix(in srgb,var(--cue-accent) 10%,transparent),transparent 38%),linear-gradient(155deg,var(--bg),var(--surface)); }}
    .speaker-media,.asset-host-video {{ position:absolute; display:block; object-fit:cover; object-position:50% 36%; overflow:hidden; transform-origin:center; will-change:transform,opacity; }}
    .speaker-media {{ z-index:4; box-shadow:0 18px 55px rgba(0,0,0,.32); border:3px solid color-mix(in srgb,var(--bg) 76%,transparent); }}
    .asset-host-video {{ z-index:2; border-radius:32px; }}
    .graphic-card {{ position:absolute; z-index:3; pointer-events:none; container-type:inline-size; }}
    .graphic-shell {{ position:relative; width:100%; height:100%; overflow:hidden; padding:clamp(30px,5.6cqi,68px); color:var(--text); border:2px solid color-mix(in srgb,var(--text) 14%,transparent); border-radius:clamp(24px,3.8cqi,44px); background:linear-gradient(145deg,color-mix(in srgb,var(--surface) 94%,transparent),color-mix(in srgb,var(--bg) 88%,transparent)); box-shadow:0 28px 90px rgba(0,0,0,.24); transform-style:preserve-3d; perspective:1400px; }}
    .layout-overlay .graphic-shell {{ background:linear-gradient(120deg,color-mix(in srgb,var(--bg) 82%,transparent),color-mix(in srgb,var(--surface) 62%,transparent)); backdrop-filter:blur(18px); }}
    .kicker {{ position:relative; z-index:12; display:flex; align-items:center; gap:12px; color:var(--muted); font-size:clamp(18px,2.3cqi,24px); line-height:1; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
    .kicker span {{ display:block; width:28px; height:3px; border-radius:3px; background:var(--cue-accent); }}
    h2 {{ margin:24px 0 0; max-width:15ch; font-size:clamp(46px,8.5cqi,116px); line-height:.95; letter-spacing:-.045em; text-wrap:balance; }}
    .stat-value {{ margin-top:clamp(28px,8cqi,78px); font-size:clamp(92px,24cqi,290px); line-height:.78; font-weight:700; letter-spacing:-.075em; color:var(--cue-accent); font-variant-numeric:tabular-nums; }}
    .stat-label {{ margin-top:clamp(24px,4cqi,48px); max-width:28ch; color:var(--text); font-size:clamp(24px,4.2cqi,48px); line-height:1.14; }}
    .measure {{ position:absolute; left:clamp(24px,5cqi,64px); right:clamp(24px,5cqi,64px); bottom:clamp(24px,5cqi,64px); height:5px; background:color-mix(in srgb,var(--text) 12%,transparent); }}
    .measure i {{ display:block; width:100%; height:100%; transform:scaleX(var(--measure-proportion)); transform-origin:left; background:var(--cue-accent); }}
    .comparison-grid {{ display:grid; grid-template-columns:1fr 44px 1fr; align-items:stretch; gap:20px; height:calc(100% - 54px); padding-top:clamp(28px,5cqi,58px); }}
    .comparison-side {{ display:flex; flex-direction:column; justify-content:space-between; padding:clamp(22px,4cqi,48px); border-radius:26px; background:color-mix(in srgb,var(--text) 6%,transparent); border:1px solid color-mix(in srgb,var(--text) 12%,transparent); }}
    .comparison-side small {{ color:var(--muted); font-size:18px; letter-spacing:.12em; }}
    .comparison-side strong {{ max-width:10ch; font-size:clamp(32px,6.2cqi,78px); line-height:.96; letter-spacing:-.04em; }}
    .comparison-side.is-accent {{ background:color-mix(in srgb,var(--cue-accent) 16%,var(--surface)); border-color:color-mix(in srgb,var(--cue-accent) 44%,transparent); }}
    .comparison-axis {{ position:relative; display:flex; align-items:center; justify-content:center; color:var(--cue-accent); }}
    .comparison-axis i {{ position:absolute; width:1px; height:100%; transform-origin:top; background:color-mix(in srgb,var(--text) 18%,transparent); }}
    .comparison-axis b {{ position:relative; padding:8px; background:var(--surface); font-size:24px; }}
    .process-line {{ position:relative; display:grid; gap:14px; margin-top:clamp(26px,5cqi,60px); }}
    .process-line::before {{ content:''; position:absolute; left:26px; top:26px; bottom:26px; width:2px; background:color-mix(in srgb,var(--cue-accent) 48%,transparent); }}
    .process-step {{ position:relative; display:grid; grid-template-columns:54px 1fr; align-items:center; gap:18px; min-height:78px; padding:12px 18px 12px 0; border-bottom:1px solid color-mix(in srgb,var(--text) 10%,transparent); font-size:clamp(24px,4cqi,46px); line-height:1.06; }}
    .process-step b {{ position:relative; display:grid; place-items:center; width:54px; height:54px; border-radius:50%; color:var(--bg); background:var(--cue-accent); font-size:20px; }}
    .type-concept_diagram .graphic-shell {{ display:grid; grid-template-rows:auto minmax(0,1fr) auto; gap:clamp(8px,2cqi,24px); padding:clamp(12px,5.6cqi,68px); }}
    .type-concept_diagram .kicker {{ font-size:clamp(12px,2.3cqi,24px); }}
    .diagram {{ position:relative; height:100%; min-height:0; margin:0; }}
    .diagram svg {{ position:absolute; inset:0; width:100%; height:100%; overflow:visible; }}
    .diagram path {{ fill:none; stroke:color-mix(in srgb,var(--cue-accent) 62%,var(--text)); stroke-width:3; vector-effect:non-scaling-stroke; }}
    .diagram-center,.diagram-node {{ position:absolute; display:grid; place-items:center; text-align:center; border-radius:999px; background:var(--surface); border:1px solid color-mix(in srgb,var(--text) 18%,transparent); text-transform:uppercase; letter-spacing:.08em; }}
    .diagram-center {{ left:50%; top:20%; width:50%; height:30%; padding:4px; transform:translate(-50%,-50%); color:var(--bg); background:var(--cue-accent); font-size:clamp(14px,4cqi,32px); font-weight:700; overflow-wrap:anywhere; }}
    .diagram-node {{ width:30%; height:25%; top:62.5%; padding:2px; color:var(--text); font-size:clamp(10px,2.8cqi,24px); font-weight:700; letter-spacing:0; overflow-wrap:normal; }}
    .node-1 {{ left:1.67%; }} .node-2 {{ left:35%; }} .node-3 {{ left:68.33%; }}
    .diagram-title {{ position:relative; margin:0; max-width:none; font-size:clamp(14px,5cqi,56px); line-height:1.08; }}
    .quote-mark {{ color:var(--cue-accent); font-family:Georgia,serif; font-size:clamp(100px,20cqi,240px); line-height:.66; }}
    blockquote {{ margin:clamp(28px,6cqi,72px) 0 0; max-width:18ch; font-size:clamp(44px,8.2cqi,112px); font-weight:700; line-height:.98; letter-spacing:-.045em; text-wrap:balance; }}
    .quote-rule {{ position:absolute; left:clamp(24px,5cqi,64px); bottom:clamp(24px,5cqi,64px); width:30%; height:5px; background:var(--cue-accent); }}
    .asset-frame {{ position:absolute; inset:0; overflow:hidden; }}
    .asset-media {{ width:100%; height:100%; object-fit:cover; }}
    .type-asset_focus.has-host-video .graphic-shell {{ background:transparent; }}
    .asset-shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,.22),rgba(0,0,0,.90)); }}
    .asset-copy {{ position:absolute; left:clamp(24px,5cqi,64px); right:clamp(24px,5cqi,64px); bottom:clamp(24px,5cqi,64px); }}
    .asset-copy .kicker {{ color:#fff; text-shadow:0 2px 14px rgba(0,0,0,.65); }}
    .asset-copy h2 {{ color:#fff; text-shadow:0 4px 24px rgba(0,0,0,.35); }}
    .keyword-title {{ margin-top:clamp(32px,8cqi,82px); max-width:12ch; }}
    .keyword-rule {{ margin-top:clamp(26px,5cqi,58px); width:min(460px,80%); height:6px; background:color-mix(in srgb,var(--text) 10%,transparent); }}
    .keyword-rule i {{ display:block; width:56%; height:100%; transform-origin:left; background:var(--cue-accent); }}
    .meaning-chip {{ position:absolute; right:clamp(24px,5cqi,64px); bottom:clamp(24px,5cqi,64px); padding:14px 22px; border-radius:999px; color:var(--bg); background:var(--cue-accent); font-size:clamp(20px,2.8cqi,28px); font-weight:700; text-transform:uppercase; letter-spacing:.08em; }}

    /* Narration-led video stages: larger than web UI, three visual layers, restrained real 3D. */
    .graphic-card[class*=" mode-"] .graphic-shell {{ padding:52px; background:radial-gradient(circle at 84% 12%,color-mix(in srgb,var(--cue-accent) 19%,transparent),transparent 34%),linear-gradient(145deg,color-mix(in srgb,var(--surface) 97%,transparent),color-mix(in srgb,var(--bg) 92%,transparent)); }}
    .ambient-plane {{ position:absolute; pointer-events:none; border:2px solid color-mix(in srgb,var(--cue-accent) 34%,transparent); transform-style:preserve-3d; }}
    .ambient-plane-a {{ width:360px; height:360px; right:-150px; top:-125px; border-radius:50%; background:color-mix(in srgb,var(--cue-accent) 10%,transparent); transform:translateZ(-160px); }}
    .ambient-plane-b {{ width:520px; height:180px; left:-250px; bottom:90px; border-radius:999px; transform:rotate(-18deg) translateZ(-220px); background:color-mix(in srgb,var(--cue-accent) 7%,transparent); }}
    .timed-item {{ backface-visibility:hidden; transform-style:preserve-3d; will-change:transform,opacity; }}
    .ghost-word {{ position:absolute; left:-38px; top:105px; color:color-mix(in srgb,var(--cue-accent) 11%,transparent); font-size:176px; line-height:.75; font-weight:700; letter-spacing:-.08em; writing-mode:vertical-rl; }}
    .mode-footer {{ position:absolute; left:52px; right:52px; bottom:48px; margin:0; max-width:11ch; font-size:76px; line-height:.88; letter-spacing:-.055em; }}

    .orbit-stage {{ position:relative; height:720px; margin-top:22px; transform-style:preserve-3d; perspective:1500px; }}
    .orbit-ring {{ position:absolute; left:50%; top:47%; width:650px; height:350px; margin:-175px 0 0 -325px; border:3px solid color-mix(in srgb,var(--cue-accent) 44%,transparent); border-radius:50%; transform-style:preserve-3d; }}
    .ring-b {{ width:510px; height:275px; margin:-138px 0 0 -255px; border-style:dashed; opacity:.45; }}
    .orbit-center {{ position:absolute; left:50%; top:47%; width:290px; height:210px; margin:-105px 0 0 -145px; display:grid; align-content:center; justify-items:center; border-radius:40px; color:var(--bg); background:var(--cue-accent); box-shadow:0 30px 70px color-mix(in srgb,var(--cue-accent) 30%,transparent); transform:translateZ(180px); z-index:9; }}
    .orbit-center small {{ font-size:20px; letter-spacing:.12em; }} .orbit-center strong {{ font-size:46px; line-height:.96; }} .orbit-center em {{ font-size:24px; font-style:normal; letter-spacing:.16em; }}
    .orbit-item {{ position:absolute; min-width:185px; padding:18px 22px; border:2px solid color-mix(in srgb,var(--text) 16%,transparent); border-radius:24px; background:var(--surface); box-shadow:0 18px 44px rgba(0,0,0,.18); font-size:25px; line-height:1; font-weight:700; text-align:center; }}
    .orbit-item[data-index="0"] {{ left:2%; top:17%; }} .orbit-item[data-index="1"] {{ right:0; top:34%; }} .orbit-item[data-index="2"] {{ left:4%; bottom:17%; }} .orbit-item[data-index="3"] {{ right:1%; bottom:15%; }}
    .mode-agentic-orbit .mode-footer {{ font-size:60px; max-width:12ch; }}

    .statement-stage {{ position:relative; z-index:3; margin-top:64px; transform-style:preserve-3d; }}
    .statement-small {{ font-size:44px; line-height:1; font-weight:700; letter-spacing:.08em; }}
    .depth-stack {{ position:relative; width:max-content; margin-top:10px; transform-style:preserve-3d; }}
    .depth-stack span,.depth-stack strong {{ display:block; font-size:106px; line-height:.82; font-weight:700; letter-spacing:-.075em; }}
    .depth-back {{ position:absolute; inset:0 auto auto 0; color:color-mix(in srgb,var(--cue-accent) 72%,var(--surface)); }}
    .depth-1 {{ transform:translate(3px,3px); }} .depth-2 {{ transform:translate(6px,6px); }} .depth-3 {{ transform:translate(9px,9px); }} .depth-4 {{ transform:translate(12px,12px); }}
    .depth-front {{ position:relative; color:var(--text); z-index:5; }}
    .statement-large {{ margin-top:22px; color:var(--cue-accent); font-size:92px; line-height:.84; font-weight:700; letter-spacing:-.07em; }}
    .statement-chip {{ display:inline-block; margin-top:44px; padding:16px 24px; border-radius:999px; color:var(--bg); background:var(--cue-accent); font-size:24px; font-weight:700; letter-spacing:.1em; }}

    .architecture-stage {{ position:relative; height:740px; margin-top:20px; transform-style:preserve-3d; perspective:1600px; }}
    .architecture-grid {{ position:absolute; inset:0; opacity:.28; background-image:linear-gradient(color-mix(in srgb,var(--cue-accent) 28%,transparent) 2px,transparent 2px),linear-gradient(90deg,color-mix(in srgb,var(--cue-accent) 28%,transparent) 2px,transparent 2px); background-size:42px 42px; mask-image:radial-gradient(circle,#000 28%,transparent 74%); }}
    .architecture-stage svg {{ position:absolute; inset:0; width:100%; height:100%; }} .architecture-stage path {{ fill:none; stroke:var(--cue-accent); stroke-width:4; opacity:.72; }}
    .architecture-core {{ position:absolute; left:50%; top:46%; width:260px; height:230px; margin:-115px 0 0 -130px; display:grid; align-content:center; justify-items:center; border-radius:42px; color:var(--bg); background:var(--cue-accent); box-shadow:0 36px 80px color-mix(in srgb,var(--cue-accent) 28%,transparent); transform:translateZ(170px); }}
    .architecture-core small {{ font-size:21px; letter-spacing:.14em; }} .architecture-core strong {{ font-size:76px; }}
    .architecture-node {{ position:absolute; width:245px; min-height:104px; display:grid; place-items:center; padding:18px; border:2px solid color-mix(in srgb,var(--text) 18%,transparent); border-radius:26px; background:var(--surface); box-shadow:0 20px 50px rgba(0,0,0,.17); font-size:27px; line-height:1.02; font-weight:700; text-align:center; }}
    .architecture-node[data-index="1"] {{ left:0; top:5%; }} .architecture-node[data-index="2"] {{ right:0; top:6%; }} .architecture-node[data-index="3"] {{ left:0; bottom:4%; }} .architecture-node[data-index="4"] {{ right:0; bottom:4%; }}
    .architecture-footer {{ font-size:56px; max-width:14ch; bottom:40px; }}

    .goal-stage {{ position:relative; z-index:2; margin-top:72px; display:grid; gap:18px; transform-style:preserve-3d; }}
    .goal-index {{ color:var(--muted); font-size:22px; font-weight:700; letter-spacing:.14em; }}
    .goal-phrase {{ width:max-content; max-width:88%; font-size:90px; line-height:.84; font-weight:700; letter-spacing:-.065em; }}
    .goal-phrase[data-index="1"] {{ margin-left:10%; color:var(--cue-accent); font-size:126px; }} .goal-phrase[data-index="2"] {{ margin-left:2%; }}
    .goal-rule {{ width:86%; height:8px; margin-top:18px; background:var(--cue-accent); transform-origin:left; }}

    .clarity-stage {{ position:relative; height:520px; margin-top:32px; perspective:1500px; transform-style:preserve-3d; }}
    .clarity-plane {{ position:absolute; top:40px; width:47%; height:410px; padding:38px; display:flex; align-items:flex-end; border:3px solid color-mix(in srgb,var(--text) 16%,transparent); border-radius:34px; background:var(--surface); box-shadow:0 28px 60px rgba(0,0,0,.2); font-size:55px; line-height:.9; font-weight:700; letter-spacing:-.055em; }}
    .clarity-plane[data-index="0"] {{ left:0; transform:rotateY(8deg) translateZ(-40px); }} .clarity-plane[data-index="1"] {{ right:0; color:var(--bg); background:var(--cue-accent); transform:rotateY(-8deg) translateZ(80px); }}
    .clarity-arrow {{ position:absolute; left:50%; top:50%; width:66px; height:66px; margin:-33px; display:grid; place-items:center; border-radius:50%; color:var(--cue-accent); background:var(--bg); border:2px solid var(--cue-accent); font-size:36px; z-index:7; }}

    .key-stage {{ position:relative; z-index:2; margin-top:72px; display:flex; align-items:flex-end; gap:22px; transform-style:preserve-3d; }}
    .key-word {{ font-size:132px; line-height:.76; font-weight:700; letter-spacing:-.08em; }} .key-word[data-index="1"] {{ color:var(--cue-accent); }}
    .key-underline {{ position:absolute; left:0; right:0; bottom:-34px; height:10px; background:var(--cue-accent); transform-origin:left; }}

    .ai-stage {{ position:relative; z-index:2; margin-top:76px; display:grid; gap:6px; transform-style:preserve-3d; }}
    .ai-word {{ width:max-content; font-size:102px; line-height:.78; font-weight:700; letter-spacing:-.075em; }} .ai-word[data-index="1"] {{ margin-left:12%; color:var(--cue-accent); font-size:128px; }} .ai-word[data-index="2"] {{ margin-left:4%; }}
    .ai-method {{ position:absolute; left:52px; bottom:54px; display:flex; align-items:center; gap:16px; font-size:24px; font-weight:700; letter-spacing:.12em; }} .ai-method i {{ color:var(--cue-accent); font-style:normal; }}

    .stack-headline {{ margin-top:20px; font-size:56px; max-width:12ch; }} .series-headline {{ margin-top:34px; font-size:66px; max-width:12ch; }}
    .stack-stage {{ position:relative; height:280px; margin-top:12px; perspective:1500px; transform-style:preserve-3d; }}
    .stack-layer {{ position:absolute; left:8%; width:84%; height:135px; display:flex; align-items:center; padding:24px 38px; border:3px solid color-mix(in srgb,var(--text) 18%,transparent); border-radius:28px; background:var(--surface); box-shadow:0 26px 58px rgba(0,0,0,.2); font-size:42px; font-weight:700; letter-spacing:-.04em; }}
    .stack-layer[data-index="0"] {{ top:0; transform:translateZ(-120px) rotateX(58deg); }} .stack-layer[data-index="1"] {{ top:52px; color:var(--bg); background:var(--cue-accent); transform:translateZ(0) rotateX(58deg); }} .stack-layer[data-index="2"] {{ top:104px; transform:translateZ(120px) rotateX(58deg); }}
    .stack-axis {{ position:absolute; right:8%; bottom:-4px; color:var(--muted); font-size:20px; font-weight:700; letter-spacing:.12em; }}

    .roadmap-stage {{ position:relative; height:430px; margin-top:35px; padding-left:70px; transform-style:preserve-3d; }}
    .roadmap-line {{ position:absolute; left:28px; top:20px; bottom:20px; width:7px; background:var(--cue-accent); transform-origin:top; }}
    .chapter-card {{ position:relative; min-height:112px; margin-bottom:22px; display:flex; align-items:center; padding:22px 30px; border:2px solid color-mix(in srgb,var(--text) 16%,transparent); border-radius:26px; background:var(--surface); box-shadow:0 18px 45px rgba(0,0,0,.16); font-size:34px; line-height:1; font-weight:700; }}
    .chapter-card::before {{ content:attr(data-index); position:absolute; left:-70px; width:52px; height:52px; display:grid; place-items:center; border-radius:50%; color:var(--bg); background:var(--cue-accent); font-size:20px; }}
    .chapter-card[data-index="1"] {{ margin-left:34px; }} .chapter-card[data-index="2"] {{ margin-left:68px; color:var(--bg); background:var(--cue-accent); }}

    .value-stage {{ position:relative; z-index:2; margin-top:80px; display:grid; gap:18px; perspective:1500px; transform-style:preserve-3d; }}
    .value-word {{ width:max-content; font-size:104px; line-height:.78; font-weight:700; letter-spacing:-.075em; }}
    .value-word[data-index="0"] {{ color:var(--muted); font-size:62px; letter-spacing:.02em; }} .value-word[data-index="1"] {{ color:var(--cue-accent); font-size:136px; }} .value-word[data-index="2"] {{ margin-left:26%; color:var(--cue-accent); font-size:136px; }} .value-word[data-index="3"] {{ font-size:112px; }}
    .value-chip {{ position:absolute; right:52px; bottom:52px; padding:16px 24px; border-radius:999px; color:var(--bg); background:var(--cue-accent); font-size:22px; font-weight:700; letter-spacing:.1em; }}
  </style>
</head>
<body>
  <main id="stage" data-composition-id="graphics-main" data-start="0" data-duration="{_fmt(duration)}"
    data-fps="{fps}" data-width="{width}" data-height="{height}">
    <div id="stage-background" class="stage-background clip" data-layout-ignore data-start="0"
      data-duration="{_fmt(duration)}" data-track-index="8"></div>{media_markup}
{cards}
  </main>
  <script src="vendor/gsap.min.js"></script>
  <script>
    (function() {{
      const tl = gsap.timeline({{paused:true}});
      {media_timeline}
      {card_timeline}
      tl.set('.graphic-card .graphic-shell', {{opacity:0}}, {_fmt(duration)});
      window.__timelines = window.__timelines || {{}};
      window.__timelines['graphics-main'] = tl;
    }})();
  </script>
</body>
</html>
"""


def write_composition(page_html: str, project_dir: str | Path) -> Path:
    """Write an HTML composition and stage local deterministic runtime assets."""
    project_path = Path(project_dir)
    runtime.output(project_path)
    project_path.mkdir(parents=True, exist_ok=True)
    _stage_runtime(project_path)
    index = project_path / "index.html"
    index.write_text(page_html, encoding="utf-8")
    return index


def _prepare_source_video(source: Path, destination: Path, fps: int,
                          duration: float) -> None:
    """Create a renderer-safe source with one-second GOPs and stable metadata."""
    ffmpeg = runtime.tool("ffmpeg", required=False)
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg is required to prepare a seek-safe source video")
    runtime.output(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-i", str(source), "-t", _fmt(duration),
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1", "-movflags", "+faststart", str(destination),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", **runtime.child_kwargs()
    )
    if result.returncode != 0:
        raise RuntimeError(f"source-video preparation failed:\n{result.stdout}\n{result.stderr}")


def _prepare_asset_video(source: Path, destination: Path, fps: int,
                         duration: float) -> None:
    """Normalize a selected motion asset to a browser-safe, seekable MP4."""
    ffmpeg = runtime.tool("ffmpeg", required=False)
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg is required to prepare selected video assets")
    runtime.output(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-stream_loop", "-1", "-i", str(source), "-t", _fmt(duration),
        "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "+faststart",
        str(destination),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", **runtime.child_kwargs()
    )
    if result.returncode != 0:
        raise RuntimeError(f"asset-video preparation failed:\n{result.stdout}\n{result.stderr}")


def write_project(plan: GraphicsPlan, project_dir: str | Path,
                  source_video: str | Path | None = None,
                  prepare_source: bool = True) -> dict[str, Path]:
    """Stage media/assets, compile HTML, and persist a stable plan + QA report."""
    assert_plan_valid(plan)
    project_path = Path(project_dir)
    runtime.output(project_path)
    project_path.mkdir(parents=True, exist_ok=True)
    source = Path(source_video or plan.source_video).resolve() if (source_video or plan.source_video) else None
    source_ref: str | None = None
    if source:
        if not source.exists():
            raise FileNotFoundError(f"source video not found: {source}")
        media_dir = project_path / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        if prepare_source:
            destination = media_dir / "source-video.mp4"
            _prepare_source_video(
                source, destination, int(plan.composition["fps"]),
                float(plan.composition["durationSeconds"]),
            )
        else:
            destination = media_dir / f"source-video{source.suffix.lower()}"
            shutil.copy2(source, destination)
        source_ref = destination.relative_to(project_path).as_posix()

    asset_refs: dict[str, str] = {}
    asset_dir = project_path / "assets"
    for cue in plan.cues:
        if not cue.asset_path:
            continue
        source_asset = Path(cue.asset_path)
        asset_dir.mkdir(parents=True, exist_ok=True)
        if source_asset.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
            destination = asset_dir / f"{cue.id}.mp4"
            _prepare_asset_video(
                source_asset, destination, int(plan.composition["fps"]), cue.duration
            )
        else:
            destination = asset_dir / f"{cue.id}{source_asset.suffix.lower()}"
            shutil.copy2(source_asset, destination)
        asset_refs[cue.id] = destination.relative_to(project_path).as_posix()

    page = build_composition(plan, source_ref=source_ref, asset_refs=asset_refs)
    index_path = write_composition(page, project_path)
    plan_path = project_path / "graphics-plan.json"
    plan_data = plan.to_dict()
    qa_issues = [*plan.qa, *validate_reveal_deadlines(plan), *validate_engagement_contract(plan)]
    if source:
        plan_data["sourceVideo"] = str(source)
        if any(cue.speaker_bounds for cue in plan.cues):
            plan_data["composition"]["speakerCropVerification"] = {
                "status": "unverified",
                "method": "visual-review-required",
                "note": "No face/subject tracking is inferred from transcript timing alone.",
            }
            serialized_cues = {cue["id"]: cue for cue in plan_data["cues"]}
            existing = {(item.get("code"), item.get("cueId")) for item in qa_issues}
            for cue in plan.cues:
                if not cue.speaker_bounds:
                    continue
                serialized_cues[cue.id]["speaker_crop_status"] = "unverified"
                key = ("speaker_crop_unverified", cue.id)
                if key not in existing:
                    qa_issues.append({
                        "severity": "warning",
                        "code": "speaker_crop_unverified",
                        "cueId": cue.id,
                        "message": "speaker window is geometry-only; confirm face/subject framing in the visual export review",
                    })
    plan_data["qa"] = qa_issues
    plan_path.write_text(json.dumps(plan_data, indent=2, sort_keys=True), encoding="utf-8")
    qa_path = project_path / "graphics-qa.json"
    automated_passed = not any(i["severity"] == "error" for i in qa_issues)
    qa_report = {
        "schema": "arete-graphics-qa/v1",
        "status": "pass" if automated_passed else "fail",
        "automatedChecksPassed": automated_passed,
        "timingContract": {
            "meaningEstablishedByAnchor": not any(
                item.get("code") in {"reveal_misses_anchor_deadline", "zero_lead_reveal_not_static"}
                for item in qa_issues
            ),
            "checkedCues": len(plan.cues),
        },
        "engagementContract": {
            "mobileStageLegibilityPassed": not any(
                item.get("code") == "portrait_stage_too_narrow" for item in qa_issues
            ),
            "wordTriggeredItemsPassed": not any(
                str(item.get("code", "")).startswith("visual_mode_anchor")
                or item.get("code") == "visual_mode_items_empty"
                for item in qa_issues
            ),
            "motionModel": "finite-seek-safe-perspective",
            "minimumTypographyPx": {"labels": 18, "body": 28, "hero": 64},
        },
        "readiness": {
            "readyForDelivery": False,
            "status": "review-required" if automated_passed else "automated-checks-failed",
            "requiredReviews": [
                {
                    "id": "visual-composition-review",
                    "status": "pending",
                    "checks": [
                        "speaker crop", "caption clearance", "trigger-frame legibility",
                        "phone-scale typography", "PiP focal-label clearance", "asset framing",
                    ],
                },
                {
                    "id": "export-playback-review",
                    "status": "pending",
                    "checks": [
                        "decoded media motion", "voice-triggered item sync", "audio sync",
                        "first/last frame", "3D depth/occlusion", "mobile platform UI overlay",
                    ],
                },
            ],
        },
        "issues": qa_issues,
    }
    qa_path.write_text(json.dumps(qa_report, indent=2, sort_keys=True), encoding="utf-8")
    return {"index": index_path, "plan": plan_path, "qa": qa_path}


def title_card(title: str, subtitle: str | None = None, duration: float = 3.0,
               accent: str = "#22d3ee", width: int = 1080, height: int = 1920,
               title_size: int = 72, sub_size: int = 36) -> str:
    """Legacy single-card generator, upgraded to local runtime and fluid motion."""
    title_text = _escape(title)
    subtitle_markup = f'<p id="subtitle">{_escape(subtitle)}</p>' if subtitle else ""
    subtitle_timeline = (
        "tl.fromTo('#subtitle',{opacity:0,y:14},{opacity:1,y:0,duration:.46,ease:'power3.out'},.28);"
        if subtitle else ""
    )
    subtitle_kill = "tl.set('#subtitle',{opacity:0},D);" if subtitle else ""
    safe_accent = _css(accent)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<style>
@font-face{{font-family:'Inter';src:url('fonts/Inter-400-latin.woff2') format('woff2');font-weight:400}}
@font-face{{font-family:'Inter';src:url('fonts/Inter-700-latin.woff2') format('woff2');font-weight:700}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;background:#0B1118;font-family:'Inter',Arial,sans-serif}}
#root{{position:relative;width:100%;height:100%;display:grid;place-items:center;color:#F7FAFC;overflow:hidden}}
#background{{position:absolute;inset:0;width:{width}px;height:{height}px;background:#0B1118;z-index:0}}
#content{{position:relative;width:82%;padding:70px 64px;border:1px solid rgba(255,255,255,.12);border-radius:38px;background:linear-gradient(145deg,#13212D,#0E171F);box-shadow:0 30px 100px rgba(0,0,0,.28)}}
#rule{{width:76px;height:6px;border-radius:6px;background:{safe_accent};transform-origin:left}}
h1{{margin:28px 0 0;font-size:{title_size}px;line-height:.94;letter-spacing:-.045em;text-wrap:balance}}
p{{margin:22px 0 0;color:{safe_accent};font-size:{sub_size}px;line-height:1.12;font-weight:700}}
</style></head><body>
<main id="root" data-composition-id="main" data-start="0" data-duration="{_fmt(duration)}" data-width="{width}" data-height="{height}">
<div id="background" class="clip" data-layout-ignore data-start="0" data-duration="{_fmt(duration)}" data-track-index="0"></div>
<section id="content" class="clip" data-layout-allow-occlusion="true" data-start="0" data-duration="{_fmt(duration)}" data-track-index="1"><div id="rule"></div><h1 id="title">{title_text}</h1>{subtitle_markup}</section>
</main><script src="vendor/gsap.min.js"></script><script>
window.__timelines=window.__timelines||{{}};const D={_fmt(duration)};const tl=gsap.timeline({{paused:true}});
tl.fromTo('#content',{{opacity:0,y:24,clipPath:'inset(0 0 10% 0)'}},{{opacity:1,y:0,clipPath:'inset(0 0 0% 0)',duration:.58,ease:'power3.out'}},0);
tl.fromTo('#rule',{{scaleX:0}},{{scaleX:1,duration:.52,ease:'power2.inOut'}},.10);
tl.fromTo('#title',{{opacity:0,y:18}},{{opacity:1,y:0,duration:.5,ease:'power3.out'}},.18);{subtitle_timeline}
tl.to('#content',{{opacity:0,y:-10,duration:.28,ease:'power2.in'}},Math.max(.6,D-.28));tl.set('#title',{{opacity:0}},D);{subtitle_kill}
window.__timelines['main']=tl;</script></body></html>"""


def _npx(args: list[str], cwd: str | Path, env: Mapping[str, str] | None = None,
         timeout: int = CHECK_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    if not args or args[0] != "hyperframes":
        raise runtime.ConfigurationError("Only the pinned HyperFrames CLI is allowed")
    return subprocess.run(
        runtime.hyperframes_command(args[1:]), cwd=str(cwd), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        env=dict(env) if env else runtime.child_env(),
        timeout=timeout, shell=False, **runtime.child_kwargs(),
    )


def lint(project_dir: str | Path) -> str:
    result = _npx(["hyperframes", "lint"], cwd=project_dir, timeout=CHECK_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(f"hyperframes lint failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def _composition_duration(project_dir: str | Path) -> float | None:
    index = Path(project_dir) / "index.html"
    if not index.exists():
        return None
    match = re.search(
        r'data-composition-id=["\'][^"\']+["\'][^>]*data-duration=["\']([0-9]+(?:\.[0-9]+)?)["\']',
        index.read_text(encoding="utf-8", errors="replace"),
        flags=re.I | re.S,
    )
    return float(match.group(1)) if match else None


def _render_timeout(project_dir: str | Path, requested: int | None) -> int:
    if requested is not None:
        if requested <= 0:
            raise ValueError("render timeout must be positive seconds")
        return int(requested)
    duration = _composition_duration(project_dir)
    scaled = (
        math.ceil(duration * RENDER_TIMEOUT_PER_MEDIA_SECOND + RENDER_TIMEOUT_OVERHEAD_SECONDS)
        if duration is not None else 0
    )
    return max(MIN_RENDER_TIMEOUT_SECONDS, scaled)


def render(project_dir: str | Path, out_path: str | Path, fps: int = 30,
           quality: str = "draft", output_format: str = "mp4",
           timeout: int | None = None) -> str:
    """Render through HyperFrames with the verified local Chromium fallback."""
    runtime.output(out_path)
    env = runtime.child_env()
    shell_path = runtime.tool("browser", required=False) or os.environ.get("PRODUCER_HEADLESS_SHELL_PATH", "")
    if shell_path and Path(shell_path).is_file():
        env.setdefault("PRODUCER_HEADLESS_SHELL_PATH", shell_path)
    env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
    result = _npx(
        ["hyperframes", "render", "-o", str(Path(out_path).resolve()), "-f", str(fps),
         "-q", quality, "--format", output_format, "--no-browser-gpu"],
        cwd=project_dir, env=env, timeout=_render_timeout(project_dir, timeout),
    )
    if result.returncode != 0:
        raise RuntimeError(f"hyperframes render failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_selected_treatment(path: str | Path) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Load and validate the explicit human-selected treatment for production."""
    source = Path(path).resolve()
    payload = _load_json(source)
    if not isinstance(payload, Mapping):
        raise ValueError("taste selection must be a JSON object")

    validator_path = (
        EDITING_OS_DIR / "Video Editing" / "Contracts" / "validate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "arete_graphics_contract_validation", validator_path
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

    selection = payload["selection"]
    selected_id = selection["selected_option_id"]
    selected = next(
        (
            option
            for option in payload["options"]
            if option.get("option_id") == selected_id
        ),
        None,
    )
    if selected is None or selected.get("status") != "selected":
        raise ValueError("taste-selection does not contain its selected option")
    tokens = selected.get("treatment_tokens")
    if not isinstance(tokens, Mapping):
        raise ValueError(
            "Graphics Engine requires embedded treatment_tokens; materialize a "
            "hash-bound treatment_artifact before rendering"
        )
    return tokens, {
        "source": "taste-selection/v1",
        "tasteSelectionPath": str(source),
        "tasteSelectionSha256": _sha256_file(source),
        "selectedOptionId": str(selected_id),
        "selectedBy": str(selection["selected_by"]),
        "selectedAt": str(selection["selected_at"]),
    }


def _verify_approved_render_manifest(
    manifest_path: str | Path,
    *,
    source_video: str | Path,
    transcript_path: str | Path,
    taste_selection_path: str | Path,
) -> dict[str, Any]:
    source = Path(manifest_path).resolve()
    manifest = _load_json(source)
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema") != "arete-approved-edl-render/v1"
        or manifest.get("status") != "pass"
    ):
        raise ValueError("approved render manifest did not pass")
    checks = (
        ("artifact", Path(source_video).resolve(), manifest.get("artifact")),
        (
            "retimed_words",
            Path(transcript_path).resolve(),
            (manifest.get("timing") or {}).get("retimed_words")
            if isinstance(manifest.get("timing"), Mapping)
            else None,
        ),
        (
            "taste_selection",
            Path(taste_selection_path).resolve(),
            manifest.get("taste_selection"),
        ),
    )
    for label, expected_path, reference in checks:
        if not isinstance(reference, Mapping):
            raise ValueError(f"approved render manifest has no {label} identity")
        observed_path = Path(str(reference.get("path") or "")).resolve()
        if str(observed_path).casefold() != str(expected_path).casefold():
            raise ValueError(f"approved render manifest {label} path mismatch")
        if reference.get("sha256") != _sha256_file(expected_path):
            raise ValueError(f"approved render manifest {label} hash mismatch")
    return {
        "manifestPath": str(source),
        "manifestSha256": _sha256_file(source),
        "artifactSha256": _sha256_file(source_video),
        "timelineFingerprint": manifest["timing"]["timeline_fingerprint"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semantic graphics planner + HyperFrames compositor")
    parser.add_argument("--transcript", help="word-timed JSON; enables semantic multi-cue planning")
    parser.add_argument("--title", help="legacy one-card mode")
    parser.add_argument("--subtitle")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--accent", default="#22d3ee")
    parser.add_argument("--platform", default="reels", choices=["reels", "tiktok", "shorts", "youtube", "x"])
    parser.add_argument("--niche", default="general")
    parser.add_argument(
        "--taste-selection",
        help="validated taste-selection/v1 JSON whose selected treatment drives production styling",
    )
    parser.add_argument(
        "--approved-render-manifest",
        help="adapter render manifest binding source video, retimed words, and selected taste",
    )
    parser.add_argument(
        "--allow-unapproved-draft-treatment",
        action="store_true",
        help="permit a rendered experiment to use the historical niche heuristic; never production",
    )
    parser.add_argument("--goal", default="retention and clarity")
    parser.add_argument("--source-video")
    parser.add_argument("--assets-dir", action="append", default=[])
    parser.add_argument("--allow-meme-assets", action="store_true")
    parser.add_argument("--no-captions", action="store_true", help="do not reserve the caption safe region")
    parser.add_argument("--fps", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--lint-only", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--render", help="output path; omit to only build the project")
    parser.add_argument("--quality", default="draft", choices=["draft", "standard", "high"])
    parser.add_argument(
        "--render-timeout", type=int,
        help="render timeout in seconds; default is duration-scaled with a 3600s floor",
    )
    runtime.common_args(parser)
    args = parser.parse_args(argv)
    runtime.configure_args(args)
    runtime.guard_args(args, ("project_dir", "render"))

    if args.transcript:
        transcript = _load_json(args.transcript)
        treatment_tokens = None
        treatment_provenance = None
        if args.taste_selection:
            treatment_tokens, treatment_provenance = _load_selected_treatment(
                args.taste_selection
            )
            if args.render:
                if (
                    not args.approved_render_manifest
                    or not args.source_video
                    or not args.transcript
                ):
                    parser.error(
                        "semantic production renders require "
                        "--approved-render-manifest, --source-video, and --transcript"
                    )
                treatment_provenance["approvedRender"] = (
                    _verify_approved_render_manifest(
                        args.approved_render_manifest,
                        source_video=args.source_video,
                        transcript_path=args.transcript,
                        taste_selection_path=args.taste_selection,
                    )
                )
        elif args.render and not args.allow_unapproved_draft_treatment:
            parser.error(
                "semantic production renders require --taste-selection; use "
                "--allow-unapproved-draft-treatment only for an explicit draft"
            )
        plan = plan_graphics(
            transcript, duration=args.duration, platform=args.platform, niche=args.niche,
            goal=args.goal, source_video=args.source_video, asset_dirs=args.assets_dir,
            captions_enabled=not args.no_captions, allow_meme_assets=args.allow_meme_assets,
            fps=args.fps, width=args.width, height=args.height,
            treatment_tokens=treatment_tokens,
            treatment_provenance=treatment_provenance,
        )
        paths = write_project(plan, args.project_dir, source_video=args.source_video)
        print(f"planned {len(plan.cues)} purposeful graphics")
        for cue in plan.cues:
            print(f"  {cue.start_sec:7.3f}s  {cue.graphic_type:16s}  {cue.layout:11s}  anchor={cue.anchor_word!r}")
        print(f"plan: {paths['plan']}")
        print(f"qa:   {paths['qa']}")
        print(f"html: {paths['index']}")
    else:
        if not args.title:
            parser.error("provide --transcript for semantic mode or --title for legacy card mode")
        duration = args.duration if args.duration is not None else 3.0
        page = title_card(args.title, subtitle=args.subtitle, duration=duration,
                          accent=args.accent, width=args.width or 1080, height=args.height or 1920)
        paths = {"index": write_composition(page, args.project_dir)}
        print(f"html: {paths['index']}")

    if not args.skip_lint:
        print(lint(args.project_dir))
    if args.render and not args.lint_only:
        fps = args.fps or 30
        print(render(
            args.project_dir, args.render, fps=fps, quality=args.quality,
            timeout=args.render_timeout,
        ))
        print(f"rendered: {Path(args.render).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

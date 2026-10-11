from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock


ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import compose  # noqa: E402
from planner import (  # noqa: E402
    build_clauses,
    discover_assets,
    normalize_words,
    plan_graphics,
    validate_plan,
)


def timed_words(text: str, step: float = 0.27, word_duration: float = 0.20):
    words = []
    time = 0.0
    for token in text.split():
        words.append({"text": token, "start": round(time, 3), "end": round(time + word_duration, 3)})
        time += step
    return words, time + 0.4


class MediaParentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.media_parents = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"video", "audio"}:
            self.media_parents.append((attrs.get("id"), self.stack[-1] if self.stack else None, attrs))
        if tag not in {"meta", "link", "img", "source", "br", "hr", "input"}:
            self.stack.append((tag, attrs.get("id")))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


REFERENCE_LIKE_SCRIPT = (
    "Most people think having ideas is easy . "
    "But the important thing is how clever you are at testing them . "
    "First collect ten ideas , then test 3 prototypes . "
    "Because distribution decides whether your podcast grows ."
)

SELECTED_TREATMENT = {
    "palette": {
        "background": "#101112",
        "surface": "#202326",
        "foreground": "#F3F4F5",
        "muted": "#A0A4A8",
        "accents": ["#5ED0C5"],
    },
    "typography": {
        "display_family": "Arial",
        "body_family": "Arial",
        "case_policy": "upper_emphasis_only",
        "weight_strategy": "One strong emphasis weight.",
    },
    "motion": {
        "style": "Purposeful reveals.",
        "default_easing": "power2.out",
        "minimum_duration_ms": 180,
        "maximum_duration_ms": 420,
    },
    "captions": {
        "profile": "semantic",
        "phrase_strategy": "Clauses",
        "emphasis": "One phrase",
        "max_chars_per_line": 26,
        "max_words_per_caption": 8,
        "max_lines": 2,
        "minimum_exposure_ms": 750,
        "maximum_caption_duration_ms": 3200,
        "reading_behavior": "auto",
        "font_size_short_edge_px": 54,
        "primary_color": "#F3F4F5",
        "accent_color": "#5ED0C5",
        "outline_color": "#101112",
        "outline_px": 3,
        "shadow_px": 1,
        "emphasis_scale_percent": 112,
        "entry_ms": 120,
        "exit_ms": 90,
        "motion": "clean-settle",
    },
    "color_grade": {
        "correction_required": True,
        "look_description": "Neutral restrained treatment.",
        "render_strategy": "ffmpeg_filter",
        "filtergraph": "eq=contrast=1.03:saturation=0.92",
        "lut_reference": None,
    },
    "audio": {
        "dialogue": "Dominant",
        "music": "Restrained",
        "sound_effects": "Motivated",
        "silence": "Authored only",
    },
}


class TranscriptPlanningTests(unittest.TestCase):
    def test_normalizes_whisperx_and_hyperframes_word_keys(self):
        data = {
            "segments": [
                {"words": [
                    {"word": "A", "start": 0.0, "end": 0.2},
                    {"text": "test.", "start": 0.22, "end": 0.5},
                ]}
            ]
        }
        words = normalize_words(data)
        self.assertEqual([word.text for word in words], ["A", "test."])
        self.assertEqual([word.index for word in words], [0, 1])

    def test_normalizes_approved_edl_retimed_words(self):
        data = {
            "retimed_words": [
                {"text": "Post", "start": 0.0, "end": 0.2},
                {"text": "cut.", "start": 0.22, "end": 0.5},
            ]
        }
        words = normalize_words(data)
        self.assertEqual([word.text for word in words], ["Post", "cut."])

    def test_clause_grouping_uses_punctuation_and_pauses(self):
        data = [
            {"text": "One", "start": 0.0, "end": 0.2},
            {"text": "idea.", "start": 0.25, "end": 0.55},
            {"text": "Another", "start": 1.2, "end": 1.4},
            {"text": "works", "start": 1.45, "end": 1.7},
            {"text": "because", "start": 1.75, "end": 2.0},
            {"text": "timing", "start": 2.05, "end": 2.3},
            {"text": "matters.", "start": 2.35, "end": 2.7},
        ]
        clauses = build_clauses(normalize_words(data))
        self.assertEqual([clause.text for clause in clauses], ["One idea.", "Another works because timing matters."])

    def test_selected_treatment_overrides_niche_theme_and_records_provenance(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        plan = plan_graphics(
            words,
            duration=duration,
            platform="reels",
            niche="tech",
            treatment_tokens=SELECTED_TREATMENT,
            treatment_provenance={
                "source": "taste-selection/v1",
                "selectedOptionId": "option-one",
                "tasteSelectionSha256": "a" * 64,
            },
        )
        self.assertEqual(plan.theme["background"], "#101112")
        self.assertEqual(plan.theme["text"], "#F3F4F5")
        self.assertEqual(plan.theme["font"], "Arial")
        self.assertEqual(plan.composition["treatmentMode"], "selected-contract")
        self.assertEqual(plan.treatment["selectedOptionId"], "option-one")

    def test_semantic_render_requires_selected_treatment_or_explicit_draft_waiver(self):
        words, _ = timed_words(REFERENCE_LIKE_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "words.json"
            transcript.write_text(json.dumps(words), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                compose.main([
                    "--transcript", str(transcript),
                    "--project-dir", str(Path(tmp) / "project"),
                    "--render", str(Path(tmp) / "output.mp4"),
                    "--skip-lint",
                ])
            self.assertEqual(raised.exception.code, 2)

    def test_approved_render_manifest_binds_source_clock_and_taste(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "approved-base.mp4"
            transcript = root / "retimed-words.json"
            taste = root / "taste-selection.json"
            source.write_bytes(b"approved encoded source")
            transcript.write_text(
                json.dumps(
                    {
                        "retimed_words": [
                            {"text": "Bound.", "start": 0.0, "end": 0.3}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            taste.write_text('{"selection":"fixture"}', encoding="utf-8")
            manifest = root / "approved-render.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "arete-approved-edl-render/v1",
                        "status": "pass",
                        "artifact": {
                            "path": str(source.resolve()),
                            "sha256": compose._sha256_file(source),
                        },
                        "timing": {
                            "retimed_words": {
                                "path": str(transcript.resolve()),
                                "sha256": compose._sha256_file(transcript),
                            },
                            "timeline_fingerprint": "a" * 64,
                        },
                        "taste_selection": {
                            "path": str(taste.resolve()),
                            "sha256": compose._sha256_file(taste),
                        },
                    }
                ),
                encoding="utf-8",
            )
            verified = compose._verify_approved_render_manifest(
                manifest,
                source_video=source,
                transcript_path=transcript,
                taste_selection_path=taste,
            )
            self.assertEqual(verified["timelineFingerprint"], "a" * 64)

    def test_number_graphic_is_anchored_to_the_exact_number_word(self):
        words, duration = timed_words("We tested 3 prototypes and learned fast .")
        plan = plan_graphics(words, duration=duration, platform="reels", niche="tech")
        stat = next(cue for cue in plan.cues if cue.graphic_type == "stat")
        self.assertEqual(stat.anchor_word, "3")
        self.assertAlmostEqual(stat.anchor_sec, round(round(words[2]["start"] * 30) / 30, 4))
        self.assertLessEqual(stat.start_sec, stat.anchor_sec)
        self.assertLess(stat.anchor_sec, stat.end_sec)

    def test_reference_rhythm_rotates_speaker_and_graphic_led_states(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        plan = plan_graphics(words, duration=duration, platform="reels", niche="podcast")
        layouts = [cue.layout for cue in plan.cues]
        self.assertIn("stage_pip", layouts)
        self.assertTrue(any(layout in layouts for layout in ("full_stage", "side_panel", "overlay")))
        self.assertTrue(any(cue.speaker_shape == "circle" for cue in plan.cues))
        self.assertTrue(all(cue.end_sec >= cue.meaning_end_sec for cue in plan.cues))
        self.assertFalse([issue for issue in plan.qa if issue["severity"] == "error"])

    def test_slow_explanation_survives_the_old_refresh_ceiling(self):
        words, duration = timed_words(
            "These 3 prototypes explain how distribution changes the entire system.",
            step=0.50, word_duration=0.47,
        )
        plan = plan_graphics(words, duration=duration, platform="reels")
        stat = next(cue for cue in plan.cues if cue.graphic_type == "stat")
        self.assertGreater(stat.duration, 3.8)
        self.assertGreaterEqual(stat.end_sec, round(words[-1]["end"] * 30) / 30)
        stat.end_sec = round((stat.meaning_end_sec - 0.2) * 30) / 30
        errors = [issue["code"] for issue in validate_plan(plan) if issue["severity"] == "error"]
        self.assertIn("meaning_hold_truncated", errors)

    def test_cue_competition_does_not_truncate_an_explanation(self):
        words, duration = timed_words(
            "These 3 prototypes explain why the mechanism works. "
            "Next test 4 outcomes before you build the complete system.",
            step=0.38, word_duration=0.33,
        )
        plan = plan_graphics(words, duration=duration, platform="reels")
        self.assertTrue(plan.cues)
        for cue in plan.cues:
            self.assertGreaterEqual(cue.end_sec + 1e-4, cue.meaning_end_sec)
        for left, right in zip(plan.cues, plan.cues[1:]):
            self.assertLessEqual(left.end_sec, right.start_sec)

    def test_portrait_stage_pip_uses_the_full_safe_stage(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        plan = plan_graphics(words, duration=duration, platform="shorts", niche="education")
        stage = next(cue for cue in plan.cues if cue.layout == "stage_pip")
        self.assertEqual(stage.graphic_bounds.width, plan.safe_areas["content"]["width"])
        self.assertTrue(stage.speaker_bounds)
        self.assertTrue(stage.graphic_bounds.intersects(stage.speaker_bounds))
        self.assertFalse([issue for issue in plan.qa if issue["severity"] == "error"])

    def test_planning_is_byte_stable_for_identical_inputs(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        first = plan_graphics(words, duration=duration, platform="shorts", niche="education")
        second = plan_graphics(words, duration=duration, platform="shorts", niche="education")
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True, separators=(",", ":")),
            json.dumps(second.to_dict(), sort_keys=True, separators=(",", ":")),
        )

    def test_caption_region_is_reserved_for_every_graphic(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        plan = plan_graphics(words, duration=duration, platform="tiktok", niche="tech", captions_enabled=True)
        caption = plan.safe_areas["captions"]
        caption_top = caption["y"]
        for cue in plan.cues:
            self.assertLessEqual(cue.graphic_bounds.bottom + 16, caption_top)

    def test_rejects_overlapping_words_and_words_ending_after_composition(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            normalize_words([
                {"text": "one", "start": 0.0, "end": 0.5},
                {"text": "two", "start": 0.4, "end": 0.7},
            ])
        with self.assertRaisesRegex(ValueError, "beyond composition duration"):
            plan_graphics(
                [{"text": "late", "start": 0.8, "end": 1.1}],
                duration=1.0,
            )

    def test_platform_safe_areas_use_caption_engine_fractions_at_custom_and_2x_sizes(self):
        expected = {
            "reels": (0.10, 0.18, 0.20, 0.07),
            "tiktok": (0.11, 0.19, 0.23, 0.07),
            "shorts": (0.09, 0.17, 0.18, 0.07),
            "youtube": (0.06, 0.06, 0.11, 0.06),
            "x": (0.07, 0.08, 0.14, 0.08),
        }
        caption_heights = {
            "reels": 300 / 1920,
            "tiktok": 310 / 1920,
            "shorts": 300 / 1920,
            "youtube": 150 / 1080,
            "x": 210 / 1350,
        }
        words, _ = timed_words("A clear system works because timing matters .")
        for platform, (top, right, bottom, left) in expected.items():
            for width, height in ((2160, 3840), (1440, 2560)):
                plan = plan_graphics(words, duration=height / 100.0, platform=platform, width=width, height=height)
                ui = plan.safe_areas["platformUI"]
                self.assertEqual(ui["top"], round(height * top))
                self.assertEqual(ui["right"], round(width * right))
                self.assertEqual(ui["bottom"], round(height * bottom))
                self.assertEqual(ui["left"], round(width * left))
                self.assertEqual(ui["fractions"], {"top": top, "right": right, "bottom": bottom, "left": left})
                captions = plan.safe_areas["captions"]
                caption_height = round(height * caption_heights[platform])
                self.assertEqual(captions["x"], round(width * left))
                self.assertEqual(captions["width"], width - round(width * left) - round(width * right))
                self.assertEqual(captions["height"], caption_height)
                self.assertEqual(captions["y"], height - round(height * bottom) - caption_height)
                self.assertEqual(plan.safe_areas["captionPolicy"]["heightFraction"], caption_heights[platform])

    def test_stat_measure_requires_truthful_parseable_proportion(self):
        count_words, count_duration = timed_words("We tested 3 prototypes and learned quickly .")
        count_plan = plan_graphics(count_words, duration=count_duration)
        count_stat = next(cue for cue in count_plan.cues if cue.graphic_type == "stat")
        self.assertNotIn("proportion", count_stat.content)
        self.assertNotIn('class="measure"', compose.build_composition(count_plan))

        percent_words, percent_duration = timed_words("Retention reached 72% after the redesign .")
        percent_plan = plan_graphics(percent_words, duration=percent_duration)
        percent_stat = next(cue for cue in percent_plan.cues if cue.graphic_type == "stat")
        self.assertEqual(percent_stat.content["proportion"], 0.72)
        page = compose.build_composition(percent_plan)
        self.assertIn('data-proportion="0.72"', page)
        self.assertIn("scaleX:0.72", page)


class AssetSelectionTests(unittest.TestCase):
    def test_catalog_is_visual_only_and_memes_are_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "images").mkdir()
            (root / "Memes").mkdir()
            (root / "audio").mkdir()
            (root / "images" / "idea-lightbulb.png").write_bytes(b"png")
            (root / "Memes" / "idea-joke.mp4").write_bytes(b"video")
            (root / "audio" / "idea.mp3").write_bytes(b"audio")
            clean = discover_assets([root])
            all_assets = discover_assets([root], allow_memes=True)
            self.assertEqual([Path(asset.path).name for asset in clean], ["idea-lightbulb.png"])
            self.assertEqual({Path(asset.path).name for asset in all_assets}, {"idea-lightbulb.png", "idea-joke.mp4"})

    def test_semantically_matching_asset_is_selected_and_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "podcast-microphone.png"
            source.write_bytes(b"png")
            words, duration = timed_words("This podcast is the product people remember .")
            plan = plan_graphics(words, duration=duration, platform="reels", niche="podcast", asset_dirs=[root])
            selected = [cue for cue in plan.cues if cue.asset_path]
            self.assertTrue(selected)
            with tempfile.TemporaryDirectory() as project:
                paths = compose.write_project(plan, project)
                self.assertTrue(paths["index"].exists())
                self.assertTrue((Path(project) / "assets" / f"{selected[0].id}.png").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and compose.runtime.tool("hyperframes_cli", required=False),
                         "ffmpeg and configured HyperFrames are required for the real-media lint regression")
    def test_real_mp4_asset_is_root_managed_timed_media_and_hyperframes_lints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "podcast-studio.mp4"
            result = subprocess.run([
                shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i",
                "testsrc2=size=96x96:rate=30", "-t", "1.0", "-an",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(asset),
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(result.returncode, 0, result.stderr)
            words, duration = timed_words("This podcast product is easy to remember .")
            plan = plan_graphics(words, duration=duration, platform="reels", niche="podcast", asset_dirs=[root])
            selected = next(cue for cue in plan.cues if cue.asset_path)
            # npx can briefly retain its cwd on Windows after the lint process
            # reports completion; do not turn that OS cleanup race into a test
            # failure after the actual regression assertions have passed.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as project:
                paths = compose.write_project(plan, project)
                staged = Path(project) / "assets" / f"{selected.id}.mp4"
                self.assertTrue(staged.exists())
                page = paths["index"].read_text(encoding="utf-8")
                parser = MediaParentParser()
                parser.feed(page)
                asset_media = next(item for item in parser.media_parents if item[0] == f"asset-video-{selected.id}")
                self.assertEqual(asset_media[1], ("main", "stage"))
                self.assertIn("data-start", asset_media[2])
                self.assertIn("data-duration", asset_media[2])
                self.assertIn("data-track-index", asset_media[2])
                self.assertNotIn('<div class="asset-frame"><video', page)
                compose.lint(project)


class CompositionContractTests(unittest.TestCase):
    def make_plan(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        return plan_graphics(words, duration=duration, platform="reels", niche="tech")

    def test_generated_page_is_offline_seek_safe_and_hyperframes_shaped(self):
        plan = self.make_plan()
        page = compose.build_composition(plan)
        self.assertIn('src="vendor/gsap.min.js"', page)
        self.assertNotIn("https://", page)
        self.assertNotIn("http://", page)
        self.assertIn("gsap.timeline({paused:true})", page)
        self.assertIn("window.__timelines['graphics-main']", page)
        self.assertIn('data-composition-id="graphics-main"', page)
        self.assertIn('class="graphic-card clip', page)
        self.assertNotIn("Math.random", page)
        self.assertNotIn("Date.now", page)
        self.assertNotIn("repeat:-1", page.replace(" ", ""))
        self.assertNotIn("back.out", page)
        self.assertIn('id="stage-background" class="stage-background clip"', page)
        self.assertIn(f"width:{plan.composition['width']}px; height:{plan.composition['height']}px", page)

    def test_packaged_video_declares_audio_and_uses_one_managed_media_track(self):
        plan = self.make_plan()
        page = compose.build_composition(plan, source_ref="media/source-video.mp4")
        self.assertEqual(page.count('id="source-video"'), 1)
        self.assertEqual(page.count('id="source-audio"'), 1)
        self.assertIn('data-track-index="0"', page)
        self.assertIn('data-track-index="10"', page)
        self.assertIn('muted playsinline', page)
        self.assertIn('id="stage-background" class="stage-background clip"', page)
        self.assertNotIn("video-wrap", page)
        self.assertNotRegex(page, r"tl\.(?:to|fromTo)\([^\n]+(?:left|top|width|height)")
        parser = MediaParentParser()
        parser.feed(page)
        self.assertTrue(parser.media_parents)
        self.assertTrue(all(parent == ("main", "stage") for _, parent, _ in parser.media_parents))

    def test_project_stages_local_runtime_fonts_plan_and_qa(self):
        plan = self.make_plan()
        with tempfile.TemporaryDirectory() as tmp:
            paths = compose.write_project(plan, tmp)
            self.assertTrue((Path(tmp) / "vendor" / "gsap.min.js").exists())
            self.assertTrue((Path(tmp) / "fonts" / "Inter-400-latin.woff2").exists())
            self.assertTrue(paths["index"].exists())
            self.assertTrue(paths["plan"].exists())
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            self.assertEqual(qa["schema"], "arete-graphics-qa/v1")
            self.assertEqual(qa["status"], "pass")
            self.assertTrue(qa["automatedChecksPassed"])
            self.assertTrue(qa["timingContract"]["meaningEstablishedByAnchor"])
            self.assertEqual(qa["timingContract"]["checkedCues"], len(plan.cues))
            self.assertTrue(qa["engagementContract"]["mobileStageLegibilityPassed"])
            self.assertTrue(qa["engagementContract"]["wordTriggeredItemsPassed"])
            self.assertEqual(qa["engagementContract"]["minimumTypographyPx"]["hero"], 64)
            self.assertFalse(qa["readiness"]["readyForDelivery"])
            self.assertEqual(qa["readiness"]["status"], "review-required")
            self.assertEqual(
                {review["status"] for review in qa["readiness"]["requiredReviews"]},
                {"pending"},
            )

    def test_bespoke_visual_mode_requires_one_in_cue_anchor_per_item(self):
        plan = self.make_plan()
        cue = plan.cues[0]
        second_anchor = min(cue.end_sec - 0.1, cue.anchor_sec + 0.3)
        cue.content = {
            "visualMode": "key-terms-hit",
            "items": ["KEY", "TERMS"],
            "itemAnchors": [cue.anchor_sec, second_anchor],
            "kicker": "LEARN THE LANGUAGE",
        }
        self.assertFalse(compose.validate_engagement_contract(plan))
        page = compose.build_composition(plan)
        self.assertIn("mode-key-terms-hit", page)
        self.assertIn(", " + compose._fmt(cue.anchor_sec) + ");", page)
        self.assertIn("perspective:1400px", page)

        cue.content["itemAnchors"] = [cue.anchor_sec]
        issues = compose.validate_engagement_contract(plan)
        self.assertEqual(issues[0]["code"], "visual_mode_anchor_count")
        with self.assertRaisesRegex(ValueError, "engagement contract"):
            compose.build_composition(plan)

    def test_trigger_specific_reveal_is_scheduled_to_finish_by_anchor(self):
        plan = self.make_plan()
        stat = next(cue for cue in plan.cues if cue.graphic_type == "stat")
        timeline = compose._card_timeline(stat)
        schedule = compose._cue_reveal_schedule(stat)
        self.assertFalse(compose.validate_reveal_deadlines(plan))
        self.assertTrue(all(window["end"] <= stat.anchor_sec + 1e-6 for window in schedule.values()))
        self.assertIn(f"duration:{compose._fmt(schedule['stat-value']['duration'])}", timeline)

    def test_zero_and_subminimum_lead_reveals_never_finish_after_anchor(self):
        zero_stat_words = [
            {"text": "72%", "start": 0.0, "end": 0.08},
            {"text": "retention", "start": 0.09, "end": 0.19},
            {"text": "after", "start": 0.20, "end": 0.28},
            {"text": "the", "start": 0.29, "end": 0.34},
            {"text": "redesign.", "start": 0.35, "end": 0.48},
        ]
        zero_plan = plan_graphics(zero_stat_words, duration=2.0, platform="reels")
        zero_stat = next(cue for cue in zero_plan.cues if cue.graphic_type == "stat")
        self.assertEqual(zero_stat.start_sec, zero_stat.anchor_sec)
        zero_schedule = compose._cue_reveal_schedule(zero_stat)
        self.assertTrue(all(not window["animated"] for window in zero_schedule.values()))
        self.assertNotIn(".stat-value", compose._card_timeline(zero_stat))
        self.assertFalse(compose.validate_reveal_deadlines(zero_plan))

        zero_comparison_words = [
            {"text": "Before", "start": 0.0, "end": 0.07},
            {"text": "the", "start": 0.08, "end": 0.12},
            {"text": "redesign", "start": 0.13, "end": 0.22},
            {"text": "was", "start": 0.23, "end": 0.28},
            {"text": "slow", "start": 0.29, "end": 0.36},
            {"text": "but", "start": 0.37, "end": 0.42},
            {"text": "after", "start": 0.43, "end": 0.50},
            {"text": "it", "start": 0.51, "end": 0.55},
            {"text": "improved.", "start": 0.56, "end": 0.68},
        ]
        comparison_plan = plan_graphics(zero_comparison_words, duration=2.0, platform="reels")
        comparison = next(cue for cue in comparison_plan.cues if cue.graphic_type == "comparison")
        self.assertTrue(all(not window["animated"] for window in compose._cue_reveal_schedule(comparison).values()))
        self.assertNotIn(".comparison-side", compose._card_timeline(comparison))

        short_lead_words = [
            {"text": "We", "start": 0.0, "end": 0.01},
            {"text": "reached", "start": 0.012, "end": 0.025},
            {"text": "72%", "start": 0.04, "end": 0.06},
            {"text": "retention", "start": 0.07, "end": 0.14},
            {"text": "today.", "start": 0.15, "end": 0.23},
        ]
        short_plan = plan_graphics(short_lead_words, duration=2.0, platform="reels")
        short_stat = next(cue for cue in short_plan.cues if cue.graphic_type == "stat")
        self.assertGreater(short_stat.anchor_sec, short_stat.start_sec)
        self.assertLess(short_stat.anchor_sec - short_stat.start_sec, 0.06)
        for window in compose._cue_reveal_schedule(short_stat).values():
            self.assertGreaterEqual(window["start"], short_stat.start_sec - 1e-6)
            self.assertLessEqual(window["end"], short_stat.anchor_sec + 1e-6)
        self.assertFalse(compose.validate_reveal_deadlines(short_plan))

    def test_render_timeout_is_duration_scaled_and_explicit_override_reaches_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose.write_composition(compose.title_card("Long", duration=217), tmp)
            self.assertGreaterEqual(compose._render_timeout(tmp, None), 4640)
            completed = subprocess.CompletedProcess([], 0, stdout="rendered", stderr="")
            with mock.patch.object(compose, "_npx", return_value=completed) as npx_call:
                compose.render(tmp, Path(tmp) / "out.mp4", timeout=4321)
            self.assertEqual(npx_call.call_args.kwargs["timeout"], 4321)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(compose, "render", return_value="rendered") as render_call:
                result = compose.main([
                    "--title", "Timeout", "--duration", "2", "--project-dir", tmp,
                    "--skip-lint", "--render", str(Path(tmp) / "out.mp4"),
                    "--render-timeout", "7777",
                ])
            self.assertEqual(result, 0)
            self.assertEqual(render_call.call_args.kwargs["timeout"], 7777)

    def test_unverified_speaker_crop_is_metadata_and_warning(self):
        words, duration = timed_words(REFERENCE_LIKE_SCRIPT)
        plan = plan_graphics(
            words, duration=duration, platform="reels", niche="podcast",
            source_video="speaker.mp4",
        )
        cropped = [cue for cue in plan.cues if cue.speaker_bounds]
        self.assertTrue(cropped)
        self.assertTrue(all(cue.speaker_crop_status == "unverified" for cue in cropped))
        self.assertEqual(plan.composition["speakerCropVerification"]["status"], "unverified")
        self.assertIn("speaker_crop_unverified", {issue["code"] for issue in plan.qa})

    def test_legacy_title_card_keeps_api_but_uses_offline_runtime(self):
        page = compose.title_card("ARETE", subtitle="Agentic OS", duration=2.5)
        self.assertIn("ARETE", page)
        self.assertIn("Agentic OS", page)
        self.assertIn('src="vendor/gsap.min.js"', page)
        self.assertNotIn("cdn.jsdelivr", page)
        self.assertIn("paused:true", page)
        self.assertIn('id="background" class="clip"', page)
        self.assertIn("width:1080px;height:1920px;background:#0B1118", page)

    def test_qa_rejects_overlap(self):
        plan = self.make_plan()
        self.assertGreaterEqual(len(plan.cues), 2)
        broken = copy.deepcopy(plan)
        broken.cues[1].start_sec = broken.cues[0].start_sec
        issues = validate_plan(broken)
        self.assertIn("cue_overlap", {issue["code"] for issue in issues})


if __name__ == "__main__":
    unittest.main()

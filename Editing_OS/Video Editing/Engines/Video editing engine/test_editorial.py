"""Focused, media-free tests for the v2 editorial engine.

Run with either:
    python -m unittest -v test_editorial.py
    python test_editorial.py
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import engine
from editorial import (
    EditorialConfig,
    EditorialError,
    build_editorial_plan,
    load_words_json,
    validate_edl,
)


def timed_words(texts, *, start=0.1, duration=0.20, gap=0.05, scores=None):
    words = []
    cursor = start
    scores = scores or [1.0] * len(texts)
    for text, score in zip(texts, scores):
        words.append({
            "text": text,
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "score": score,
        })
        cursor += duration + gap
    return words


class EditorialPlanningTests(unittest.TestCase):
    def test_cleanup_removes_filler_stumble_and_dead_air_without_losing_idea(self):
        words = timed_words(["Um", "we", "built", "we", "built", "a", "faster", "system."])
        # Put a large pause before a second, distinct idea.
        words += timed_words(["It", "keeps", "the", "meaning."], start=3.0)

        plan = build_editorial_plan(words, source_path="input.mp4")
        kinds = {issue["kind"] for issue in plan["analysis"]["issues"]}
        self.assertTrue({"filler", "false_start", "dead_air"} <= kinds)
        self.assertTrue(plan["validation"]["valid"], plan["validation"])

        kept = " ".join(item["quote"] for item in plan["edl"]["ranges"])
        self.assertNotIn("Um", kept)
        self.assertNotIn("we built we built", kept)
        self.assertIn("built a faster system.", kept)
        self.assertIn("It keeps the meaning.", kept)

    def test_balanced_cleanup_preserves_semantic_you_know_phrase(self):
        words = timed_words(["The", "people", "you", "know", "can", "open", "doors."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        phrase = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "filler_phrase" and issue["text"] == "you know"
        )
        self.assertEqual(output, "The people you know can open doors.")
        self.assertFalse(phrase["automatic"])
        self.assertEqual(phrase["recommended_action"], "review_remove")

    def test_balanced_cleanup_preserves_semantic_i_mean_phrase(self):
        words = timed_words(["What", "I", "mean", "is", "precision", "matters."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        phrase = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "filler_phrase" and issue["text"].lower() == "i mean"
        )
        self.assertEqual(output, "What I mean is precision matters.")
        self.assertFalse(phrase["automatic"])

    def test_balanced_cleanup_preserves_semantic_kind_of_phrase(self):
        words = timed_words(["This", "kind", "of", "tool", "saves", "time."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        phrase = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "filler_phrase" and issue["text"] == "kind of"
        )
        self.assertEqual(output, "This kind of tool saves time.")
        self.assertFalse(phrase["automatic"])

    def test_true_discourse_phrase_is_flagged_for_review_not_silently_deleted(self):
        words = timed_words(["Well,", "you", "know,", "this", "can", "work."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        phrase = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "filler_phrase" and issue["text"] == "you know,"
        )
        self.assertEqual(output, "Well, you know, this can work.")
        self.assertFalse(phrase["automatic"])
        self.assertIn(phrase["id"], {item["id"] for item in plan["analysis"]["review_required"]})

    def test_hard_nonlexical_filler_remains_safe_automatic_cleanup(self):
        words = timed_words(["Um", "this", "works."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        filler = next(issue for issue in plan["analysis"]["issues"] if issue["kind"] == "filler")
        self.assertEqual(output, "this works.")
        self.assertTrue(filler["automatic"])

    def test_balanced_cleanup_preserves_very_very_emphasis(self):
        words = timed_words(["This", "is", "very", "very", "important."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        repetition = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "false_start" and issue["text"] == "very"
        )
        self.assertEqual(output, "This is very very important.")
        self.assertFalse(repetition["automatic"])
        self.assertEqual(repetition["recommended_action"], "review_remove")

    def test_balanced_cleanup_preserves_no_no_no_emphasis(self):
        words = timed_words(["No", "no", "no,", "that", "is", "wrong."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        repetitions = [
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "false_start"
        ]
        self.assertEqual(output, "No no no, that is wrong.")
        self.assertTrue(repetitions)
        self.assertTrue(all(not issue["automatic"] for issue in repetitions))

    def test_balanced_cleanup_preserves_go_go_go_emphasis(self):
        words = timed_words(["Go", "go", "go!"])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        repetition = next(
            issue for issue in plan["analysis"]["issues"]
            if issue["kind"] == "false_start"
        )
        self.assertEqual(output, "Go go go!")
        self.assertFalse(repetition["automatic"])

    def test_broken_prefix_stumble_remains_safe_automatic_cleanup(self):
        words = timed_words(["th-", "the", "answer", "works."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = " ".join(word["text"] for word in plan["edl"]["editorial"]["retimed_words"])
        stumble = next(issue for issue in plan["analysis"]["issues"] if issue["kind"] == "stumble")
        self.assertEqual(output, "the answer works.")
        self.assertTrue(stumble["automatic"])

    def test_dead_air_is_compressed_to_configured_breath(self):
        words = timed_words(["First", "idea."])
        words += timed_words(["Second", "idea."], start=2.0)
        cfg = EditorialConfig(platform="tiktok", pacing="tight", dead_air_threshold_s=0.4)
        plan = build_editorial_plan(words, source_path="input.mp4", config=cfg)

        dead_air = next(issue for issue in plan["analysis"]["issues"] if issue["kind"] == "dead_air")
        self.assertLess(dead_air["keep_s"], dead_air["gap_s"])
        self.assertEqual(len(plan["edl"]["ranges"]), 2)
        self.assertTrue(plan["validation"]["checks"]["word_safe_edges"])

        first, second = plan["edl"]["ranges"]
        output_pause = (first["end"] - first["word_end_s"]) + (second["word_start_s"] - second["start"])
        self.assertAlmostEqual(output_pause, dead_air["keep_s"], places=2)

    def test_explicit_comedic_or_emotional_pause_is_preserved(self):
        words = timed_words(["Wait..."])
        words += timed_words(["what?"], start=2.0)
        plan = build_editorial_plan(words, source_path="input.mp4")
        pause = next(issue for issue in plan["analysis"]["issues"] if issue["kind"] == "dead_air")
        self.assertEqual(pause["recommended_action"], "preserve")
        self.assertFalse(pause["automatic"])
        self.assertEqual(len(plan["edl"]["ranges"]), 1)

    def test_adjacent_retake_keeps_exactly_one_delivery(self):
        words = timed_words(
            ["This", "is", "the", "result.", "This", "is", "the", "result."],
            scores=[0.70] * 4 + [0.98] * 4,
        )
        plan = build_editorial_plan(words, source_path="input.mp4")
        output = [word["text"] for word in plan["edl"]["editorial"]["retimed_words"]]
        self.assertEqual(output, ["This", "is", "the", "result."])
        self.assertTrue(plan["validation"]["valid"])

    def test_semantic_similarity_is_review_only_when_not_safe(self):
        words = timed_words([
            "The", "tool", "saves", "editing", "time.",
            "Now", "look", "at", "the", "timeline.",
            "This", "tool", "saves", "a", "lot", "of", "editing", "time.",
        ])
        plan = build_editorial_plan(words, source_path="input.mp4")
        reviews = [issue for issue in plan["analysis"]["review_required"] if issue.get("kind") == "semantic_repetition"]
        self.assertTrue(reviews)
        self.assertTrue(all(not issue["automatic"] for issue in reviews))

    def test_hook_retention_and_graphics_handoffs_are_explainable(self):
        words = timed_words([
            "Why", "do", "90%", "of", "edits", "lose", "viewers?",
            "Because", "dead", "air", "breaks", "momentum.",
        ])
        plan = build_editorial_plan(words, source_path="input.mp4")
        first = plan["analysis"]["sentence_scores"][0]
        self.assertGreaterEqual(first["hook_score"], 70)
        self.assertTrue(first["hook_reasons"])

        handoffs = plan["edl"]["editorial"]["handoffs"]
        self.assertEqual(handoffs["captions"]["timing_basis"], "output_timeline_seconds")
        self.assertTrue(handoffs["captions"]["cues"][0]["emphasis_words"])
        self.assertEqual(handoffs["graphics"]["cues"][0]["type"], "stat_or_number")
        self.assertIn("caption-safe composition", handoffs["graphics"]["cues"][0]["guardrails"])
        timeline_map = plan["edl"]["editorial"]["timeline_map"]
        self.assertEqual(timeline_map[0]["output_start"], 0.0)
        self.assertIn("source_to_output_offset", timeline_map[0])

    def test_rhythm_plan_varies_macro_pacing_and_marks_long_shots(self):
        words = timed_words(
            ["Hook."] + [f"word{i}" for i in range(35)] + ["payoff."],
            duration=0.20,
            gap=0.04,
        )
        plan = build_editorial_plan(words, source_path="input.mp4")
        rhythm = plan["edl"]["editorial"]["rhythm_plan"]
        self.assertEqual(rhythm["macro_shape"], "tight hook -> varied build -> accelerate into peak -> release")
        self.assertGreaterEqual(len(rhythm["phases"]), 3)
        self.assertTrue(any(shot["visual_refresh_due"] for shot in rhythm["shots"]))

    def test_short_form_rhythm_phases_never_overlap(self):
        words = timed_words(["Hook.", "One", "tight", "payoff."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        phases = plan["edl"]["editorial"]["rhythm_plan"]["phases"]
        for left, right in zip(phases, phases[1:]):
            self.assertLessEqual(left["end"], right["start"])

    def test_qa_plan_carries_cross_engine_mobile_sync_and_visual_world_checks(self):
        words = timed_words(["Every", "word", "and", "graphic", "lands", "cleanly."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        checks = plan["edl"]["editorial"]["qa_plan"]["mandatory_checks"]
        self.assertTrue(any("one output frame" in check for check in checks))
        self.assertTrue(any("50% linear scale" in check for check in checks))
        self.assertTrue(any("retimed-word anchors" in check for check in checks))
        self.assertTrue(any("coherent visual world" in check for check in checks))
        self.assertTrue(any("video and dialogue streams" in check for check in checks))

    def test_plan_is_byte_deterministic_for_identical_inputs(self):
        words = timed_words(["You", "can", "cut", "dead", "air.", "Try", "this", "method."])
        first = build_editorial_plan(words, source_path="input.mp4")
        second = build_editorial_plan(words, source_path="input.mp4")
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.words = timed_words(["Clean", "cuts", "protect", "every", "word."])
        self.plan = build_editorial_plan(self.words, source_path="input.mp4")

    def test_validator_rejects_cut_inside_word(self):
        broken = copy.deepcopy(self.plan["edl"])
        broken["ranges"][0]["start"] = self.words[0]["start"] + 0.05
        broken["ranges"][0]["pad_in_s"] = -0.05
        report = validate_edl(broken, {"main": self.words})
        self.assertFalse(report["valid"])
        self.assertIn("cut_inside_word", {error["code"] for error in report["errors"]})

    def test_validator_rejects_bad_total_and_out_of_bounds_cue(self):
        broken = copy.deepcopy(self.plan["edl"])
        broken["total_duration_s"] += 2
        broken["editorial"]["handoffs"]["graphics"]["cues"][0]["start_in_output"] = 99
        report = validate_edl(broken, {"main": self.words})
        codes = {error["code"] for error in report["errors"]}
        self.assertTrue({"duration_mismatch", "cue_bounds"} <= codes)

    def test_validator_rejects_drifted_source_to_output_map(self):
        broken = copy.deepcopy(self.plan["edl"])
        broken["editorial"]["timeline_map"][0]["output_start"] = 0.25
        report = validate_edl(broken, {"main": self.words})
        self.assertFalse(report["valid"])
        self.assertIn("timeline_map", {error["code"] for error in report["errors"]})

    def test_validator_reconstructs_retimed_words_from_sources_and_ranges(self):
        broken = copy.deepcopy(self.plan["edl"])
        broken["editorial"]["retimed_words"][1]["text"] = "tampered"
        broken["editorial"]["retimed_words"][1]["start"] += 0.01
        report = validate_edl(broken, {"main": self.words})
        self.assertFalse(report["valid"])
        mismatches = [item for item in report["errors"] if item["code"] == "retimed_words"]
        self.assertTrue(any("source_words+ranges" in item["message"] for item in mismatches))

    def test_config_rejects_padding_outside_verified_window(self):
        with self.assertRaises(EditorialError):
            EditorialConfig(breath_padding_before_s=0.01).checked()

    def test_planner_rejects_large_word_timing_overlap(self):
        words = timed_words(["These", "words", "overlap."])
        words[1]["start"] = words[0]["start"] + 0.03
        words[1]["end"] = words[0]["end"] + 0.15
        with self.assertRaisesRegex(EditorialError, "overlaps"):
            build_editorial_plan(words, source_path="input.mp4")

    def test_multi_source_edl_requires_transcript_evidence_for_every_source(self):
        broken = copy.deepcopy(self.plan["edl"])
        broken["sources"]["second"] = "second.mp4"
        with self.assertRaisesRegex(engine.EngineError, "source_words_by_source"):
            engine._edl_words_by_source(broken)


class IntegrationContractTests(unittest.TestCase):
    def test_loads_hyperframes_caption_shape_and_writes_plan_files(self):
        words = timed_words(["A", "reviewable", "plan", "comes", "first."])
        payload = {"clips": [{"words": words[:2]}, {"words": words[2:]}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            words_path = root / "captions.json"
            # PowerShell 5 commonly writes UTF-8 with a BOM; accept it.
            words_path.write_text(json.dumps(payload), encoding="utf-8-sig")
            self.assertEqual(len(load_words_json(str(words_path))), len(words))

            fake_video = root / "source.mp4"
            fake_video.write_bytes(b"not read in plan-only mode with supplied words")
            plan, edl_path, plan_path = engine.plan_edits(
                fake_video,
                words_json=words_path,
                work_dir=root / "work",
                edl_out=root / "approved.edl.json",
                plan_out=root / "analysis.json",
            )
            self.assertTrue(plan["validation"]["valid"])
            self.assertTrue(edl_path.exists())
            self.assertTrue(plan_path.exists())

    def test_retimed_caption_assets_use_output_timeline(self):
        words = timed_words(["Perfect", "timing", "after", "cuts."])
        plan = build_editorial_plan(words, source_path="input.mp4")
        retimed = plan["edl"]["editorial"]["retimed_words"]
        with tempfile.TemporaryDirectory() as tmp:
            ass_path, json_path = engine.write_timeline_caption_assets(
                retimed, Path(tmp) / "captions"
            )
            self.assertIn("Dialogue:", ass_path.read_text(encoding="utf-8"))
            caption_data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(caption_data["clips"][0]["words"][0]["start"], retimed[0]["start"])

    def test_overlay_pts_shift_precedes_captions_in_filtergraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.mp4"
            overlay = root / "overlay.mp4"
            captions = root / "captions.ass"
            for path in (base, overlay, captions):
                path.write_bytes(b"fixture")
            captured = []

            def fake_run(command, **_kwargs):
                captured.append(command)

            with mock.patch.object(engine, "_run", side_effect=fake_run):
                engine.composite_overlays_and_captions(
                    base,
                    root / "out.mp4",
                    overlays=[{"file": str(overlay), "start_in_output": 2.0, "duration": 1.5}],
                    ass_path=captions,
                )
            command = captured[0]
            graph = command[command.index("-filter_complex") + 1]
            self.assertIn("setpts=PTS-STARTPTS+2.000000/TB", graph)
            self.assertLess(graph.index("overlay="), graph.index("subtitles="))

    def test_hdr_sources_prepend_tonemap_before_grade(self):
        with mock.patch.object(engine, "_ffprobe_color_transfer", return_value="arib-std-b67"):
            chain = engine._source_video_filter("source.mp4", "subtle")
        self.assertTrue(chain.startswith("zscale=t=linear"))
        self.assertLess(chain.index("tonemap="), chain.index("eq=contrast"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

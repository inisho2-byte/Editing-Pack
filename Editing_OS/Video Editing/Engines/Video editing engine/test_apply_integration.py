"""Fast integration contracts for the approved-EDL render path."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import engine
from editorial import EditorialConfig, build_editorial_plan


def timed_words(texts, *, start=0.1, duration=0.24, gap=0.05):
    words = []
    cursor = start
    for text in texts:
        words.append({
            "text": text,
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "score": 1.0,
        })
        cursor += duration + gap
    return words


class CaptionHandoffTests(unittest.TestCase):
    def test_edl_platform_drives_caption_profile_and_writes_qa(self):
        words = timed_words(["This", "timing", "belongs", "to", "TikTok."])
        with tempfile.TemporaryDirectory() as tmp:
            ass_path, json_path, qa_path = engine.write_timeline_caption_assets(
                words,
                Path(tmp) / "captions",
                platform="tiktok",
                include_qa=True,
            )
            caption_data = json.loads(json_path.read_text(encoding="utf-8"))
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            self.assertTrue(ass_path.exists())
            self.assertEqual(caption_data["platform"], "tiktok")
            self.assertEqual(qa["style"]["platform"], "tiktok")
            self.assertNotEqual(qa["status"], "fail")


class GraphicsHandoffTests(unittest.TestCase):
    def _modules(self, plan):
        def fake_render(_project_dir, out_path, **_kwargs):
            Path(out_path).write_bytes(b"graphics render")

        planner = SimpleNamespace(plan_graphics=mock.Mock(return_value=plan))
        compose = SimpleNamespace(
            write_project=mock.Mock(),
            lint=mock.Mock(),
            render=mock.Mock(side_effect=fake_render),
        )
        return planner, compose

    def test_graphics_uses_exact_retimed_words_platform_and_clean_cut_source(self):
        retimed = timed_words(["Why", "do", "90%", "of", "edits", "lose", "viewers?"])
        plan = SimpleNamespace(
            cues=[SimpleNamespace(id="graphic-01")],
            qa=[],
            composition={"fps": 30},
            to_dict=lambda: {"cues": [{"id": "graphic-01"}]},
        )
        planner, compose = self._modules(plan)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.mkv"
            base.write_bytes(b"clean-cut fixture")
            project = root / "graphics_project"
            compose.write_project.return_value = {
                "index": project / "index.html",
                "plan": project / "graphics-plan.json",
                "qa": project / "graphics-qa.json",
            }
            with mock.patch.object(engine, "_load_graphics_engine", return_value=(planner, compose)), \
                    mock.patch.object(engine, "_ffprobe_dimensions", return_value=(1080, 1920)):
                rendered, handoff = engine.render_edl_graphics(
                    base,
                    retimed,
                    duration_s=retimed[-1]["end"],
                    platform="shorts",
                    work_dir=root,
                    niche="tech",
                    asset_dirs=[root / "assets"],
                    quality="draft",
                )

            kwargs = planner.plan_graphics.call_args.kwargs
            self.assertIs(planner.plan_graphics.call_args.args[0], retimed)
            self.assertEqual(kwargs["platform"], "shorts")
            self.assertEqual(kwargs["niche"], "tech")
            self.assertEqual(kwargs["source_video"], str(base.resolve()))
            self.assertEqual((kwargs["width"], kwargs["height"]), (1080, 1920))
            compose.write_project.assert_called_once_with(plan, project, source_video=base.resolve())
            compose.lint.assert_called_once_with(project)
            compose.render.assert_called_once()
            self.assertEqual(rendered, root / "graphics_composited.mp4")
            self.assertEqual(handoff["status"], "rendered")
            self.assertTrue(Path(handoff["plan"]).name == "graphics-plan.json")
            self.assertTrue(Path(handoff["qa"]).name == "graphics-qa.json")

    def test_zero_cue_plan_is_persisted_and_skips_reencode(self):
        plan = SimpleNamespace(
            cues=[], qa=[], composition={"fps": 30},
            to_dict=lambda: {"cues": []},
        )
        planner, compose = self._modules(plan)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.mkv"
            base.write_bytes(b"fixture")
            with mock.patch.object(engine, "_load_graphics_engine", return_value=(planner, compose)), \
                    mock.patch.object(engine, "_ffprobe_dimensions", return_value=(1920, 1080)):
                rendered, handoff = engine.render_edl_graphics(
                    base,
                    timed_words(["A", "quiet", "sentence."]),
                    duration_s=1.0,
                    platform="youtube",
                    work_dir=root,
                )
            self.assertEqual(rendered, base.resolve())
            self.assertEqual(handoff["status"], "skipped_no_cues")
            self.assertTrue(Path(handoff["plan"]).exists())
            self.assertTrue(Path(handoff["qa"]).exists())
            compose.write_project.assert_not_called()
            compose.render.assert_not_called()


class ApplyEdlTests(unittest.TestCase):
    def _edl(self, source):
        words = timed_words(["Why", "90%", "of", "edits", "lose", "viewers?"])
        return build_editorial_plan(
            words,
            source_path=str(source),
            config=EditorialConfig(platform="shorts"),
        )["edl"]

    def test_apply_graphics_and_captions_share_edl_clock_captions_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"fixture")
            edl = self._edl(source)
            out = root / "final.mp4"
            work = root / "work"
            graphics_video = work / "graphics_composited.mp4"
            captured = {}

            def fake_base(_edl, path, _work):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"base")

            def fake_graphics(base, words, **kwargs):
                captured["graphics_words"] = words
                captured["graphics_platform"] = kwargs["platform"]
                graphics_video.write_bytes(b"graphics")
                return graphics_video, {
                    "status": "rendered", "qa_passed": True,
                    "plan": str(work / "graphics-plan.json"),
                    "qa": str(work / "graphics-qa.json"),
                }

            def fake_captions(words, prefix, **kwargs):
                captured["caption_words"] = words
                captured["caption_platform"] = kwargs["platform"]
                ass = Path(f"{prefix}.ass")
                data = Path(f"{prefix}.captions.json")
                qa = Path(f"{prefix}.qa.json")
                ass.write_text("fixture", encoding="utf-8")
                data.write_text("{}", encoding="utf-8")
                qa.write_text(json.dumps({
                    "status": "pass",
                    "style": {"platform": "youtube-shorts"},
                }), encoding="utf-8")
                return ass, data, qa

            def fake_composite(base, output, **kwargs):
                captured["composite_base"] = Path(base)
                captured["caption_ass"] = kwargs["ass_path"]
                Path(output).write_bytes(b"final")

            with mock.patch.object(engine, "_ffprobe_color_transfer", return_value="bt709"), \
                    mock.patch.object(engine, "_ffprobe_dimensions", return_value=(1080, 1920)), \
                    mock.patch.object(engine, "_ffprobe_duration", return_value=float(edl["total_duration_s"])), \
                    mock.patch.object(engine, "_ffprobe_stream_manifest", return_value={"streams": [
                        {"codec_type": "video", "codec_name": "h264"},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ]}), \
                    mock.patch.object(engine, "render_edl_base", side_effect=fake_base), \
                    mock.patch.object(engine, "render_edl_graphics", side_effect=fake_graphics), \
                    mock.patch.object(engine, "write_timeline_caption_assets", side_effect=fake_captions), \
                    mock.patch.object(engine, "composite_overlays_and_captions", side_effect=fake_composite), \
                    mock.patch.object(engine, "extract_audio") as extract_audio, \
                    mock.patch.object(engine, "generate_captions") as generate_captions:
                report = engine.apply_edl(
                    edl, out, work_dir=work, make_graphics=True, make_captions=True,
                )

            retimed = edl["editorial"]["retimed_words"]
            self.assertIs(captured["graphics_words"], retimed)
            self.assertIs(captured["caption_words"], retimed)
            self.assertEqual(captured["graphics_platform"], "shorts")
            self.assertEqual(captured["caption_platform"], "shorts")
            self.assertEqual(captured["composite_base"], graphics_video)
            self.assertTrue(str(captured["caption_ass"]).endswith("captions.ass"))
            self.assertIn("graphics_handoff", report)
            self.assertIn("qa", report["caption_handoff"])
            self.assertTrue(report["qa"]["export_streams"]["video_present"])
            self.assertTrue(report["qa"]["export_streams"]["audio_present"])
            self.assertEqual(report["qa"]["export_review"]["status"], "pending-human-review")
            self.assertIn("voice_activation", report["qa"]["export_review"]["checks"])
            self.assertIn("color_and_background", report["qa"]["export_review"]["checks"])
            extract_audio.assert_not_called()
            generate_captions.assert_not_called()

    def test_apply_without_graphics_preserves_clean_base_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"fixture")
            edl = self._edl(source)
            out = root / "final.mp4"
            work = root / "work"
            captured = {}

            def fake_base(_edl, path, _work):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"base")

            def fake_composite(base, output, **_kwargs):
                captured["base"] = Path(base)
                Path(output).write_bytes(b"final")

            with mock.patch.object(engine, "_ffprobe_color_transfer", return_value="bt709"), \
                    mock.patch.object(engine, "_ffprobe_duration", return_value=float(edl["total_duration_s"])), \
                    mock.patch.object(engine, "_ffprobe_stream_manifest", return_value={"streams": [
                        {"codec_type": "video", "codec_name": "h264"},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ]}), \
                    mock.patch.object(engine, "render_edl_base", side_effect=fake_base), \
                    mock.patch.object(engine, "render_edl_graphics") as render_graphics, \
                    mock.patch.object(engine, "composite_overlays_and_captions", side_effect=fake_composite):
                report = engine.apply_edl(
                    edl, out, work_dir=work, make_graphics=False, make_captions=False,
                )

            self.assertEqual(captured["base"], work / "base.mkv")
            self.assertNotIn("graphics_handoff", report)
            render_graphics.assert_not_called()

    def test_apply_cli_does_not_require_input(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(engine, "apply_edl", return_value={"mode": "approved_edl"}) as apply:
            result = engine.main([
                "--apply-edits", "--edl-in", "approved.json", "--out", str(Path(tmp) / "final.mp4")
            ])
        self.assertEqual(result, 0)
        apply.assert_called_once()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
class AudioDriftRegressionTests(unittest.TestCase):
    def test_five_segment_concat_does_not_accumulate_aac_priming(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mkv"
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=2.55",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.55",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", str(source),
            ], check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ranges = [
                {"source": "main", "start": index * 0.51, "end": (index + 1) * 0.51,
                 "grade": "none", "id": f"range-{index}"}
                for index in range(5)
            ]
            edl = {
                "version": 1,
                "sources": {"main": str(source)},
                "ranges": ranges,
                "total_duration_s": 2.55,
            }
            output = root / "base.mkv"
            engine.render_edl_base(edl, output, root / "work")
            # 510ms is deliberately not aligned to a 30fps frame. The concat
            # manifest must honor EDL durations instead of accumulating each
            # segment container's rounded frame duration.
            self.assertLessEqual(abs(engine._ffprobe_duration(output) - 2.55), 0.03)


if __name__ == "__main__":
    unittest.main(verbosity=2)

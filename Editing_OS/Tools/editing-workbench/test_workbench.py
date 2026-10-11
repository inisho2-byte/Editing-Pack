"""Regression checks; approval fixtures are synthetic, never operator consent."""
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

import workbench as w

KIT = w.toolkit_root() / w.KIT_REL


def media(fps="30000/1001"):
    return {"main": {"path": str(KIT / "source & test.mp4"), "sha256": "a" * 64,
                     "fps": fps, "display_width": 1080, "display_height": 1920,
                     "rotation": 0, "sample_aspect_ratio": "1:1", "frame_count": 300,
                     "constant_frame_rate": True, "first_pts": "0", "has_audio": True,
                     "timecode_start_frame": 107892}}


class FrameTests(unittest.TestCase):
    def test_atomic_write_recovers_from_transient_windows_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result.json"
            original = Path.replace
            attempts = []
            def replace(source, destination):
                attempts.append(source)
                if len(attempts) == 1:
                    raise PermissionError("transient scanner lock")
                return original(source, destination)
            with patch.object(Path, "replace", replace), patch.object(w.time, "sleep"):
                w.write(target, {"complete": True})
            self.assertEqual(w.load(target), {"complete": True})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_failed_atomic_write_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result.json"
            target.write_text('{"original":true}', encoding="utf-8")
            with patch.object(Path, "replace", side_effect=PermissionError("locked")), patch.object(w.time, "sleep"):
                with self.assertRaises(PermissionError):
                    w.write(target, {"new": True})
            self.assertEqual(w.load(target), {"original": True})
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_fractional_rate_half_up(self):
        self.assertEqual(w.frame("1.001", Fraction(30000, 1001)), 30)
        self.assertEqual(w.frame("0.05", Fraction(30)), 2)
        self.assertEqual(w.rational_time(30, Fraction(30000, 1001)), "1001/1000s")

    def test_drop_frame_hour(self):
        self.assertEqual(w.timecode_frames("01:00:00;00", Fraction(30000, 1001)), 107892)
        self.assertEqual(w.timecode_frames("01:00:00;00", Fraction(60000, 1001)), 215784)
        with self.assertRaises(ValueError):
            w.timecode_frames("00:01:00;00", Fraction(30000, 1001))

    def test_three_real_edit_points_and_timecode(self):
        edl = {"sources": {"main": "source.mp4"}, "ranges": [
            {"source": "main", "start": 0, "end": 1.001},
            {"source": "main", "start": 2.002, "end": 3.003},
            {"source": "main", "start": 5.005, "end": 6.006}]}
        plan = w.normalize(edl, media(), approved=True)
        self.assertEqual(plan["total_frames"], 90)
        with tempfile.TemporaryDirectory() as folder:
            root = ET.fromstring(w.fcpxml(plan, "test & name", Path(folder) / "new.fcpbundle"))
        clips = root.findall("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[1].get("offset"), "1001/1000s")
        expected = w.rational_time(107892 + 60, Fraction(30000, 1001))
        self.assertEqual(clips[1].get("start"), expected)
        self.assertEqual(len(root.findall(".//audio")), 0)
        self.assertIn("source%20%26%20test.mp4", root.find(".//media-rep").get("src"))
        self.assertFalse(plan["publishable"])
        self.assertEqual(root[0].tag, "import-options")

    def test_dtd_version_must_match(self):
        w.require_dtd_version(Path("FCPXMLv1_10.dtd"), "1.10")
        with self.assertRaisesRegex(ValueError, "matching installed"):
            w.require_dtd_version(Path("FCPXMLv1_10.dtd"), "1.13")

    def test_all_canonical_scene_roles_are_documented(self):
        schema = w.load(KIT / "Editing_OS/Video Editing/Contracts/schemas/editorial-intent.v1.schema.json")
        def enums(node):
            if isinstance(node, dict):
                if "enum" in node and "stop_hook" in node["enum"]:
                    return node["enum"]
                for value in node.values():
                    found = enums(value)
                    if found:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = enums(value)
                    if found:
                        return found
        roles = enums(schema)
        self.assertEqual(len(roles), 12)
        guide = (KIT / "Editing_OS/Skills/SCENE_PATTERNS.md").read_text(encoding="utf-8")
        for role in roles:
            self.assertIn(f"| `{role}` |", guide)

    def test_no_silent_resnap_after_approval(self):
        edl = {"sources": {"main": "x"}, "ranges": [{"source": "main", "start": .123, "end": 1.01}]}
        self.assertEqual(w.normalize(edl, media())["status"], "draft-needs-edl-reapproval")
        with self.assertRaisesRegex(ValueError, "reapprove"):
            w.normalize(edl, media(), approved=True)

    def test_vfr_and_mixed_rate_fail(self):
        edl = {"sources": {"main": "x"}, "ranges": [{"source": "main", "start": 0, "end": 1.001}]}
        info = media()
        info["main"]["constant_frame_rate"] = False
        with self.assertRaisesRegex(ValueError, "VFR"):
            w.normalize(edl, info)
        info = media()
        info["other"] = dict(info["main"], fps="30")
        with self.assertRaisesRegex(ValueError, "Mixed"):
            w.normalize(edl, info)

    def test_readback_detects_one_frame_and_missing_edit(self):
        plan = w.normalize({"sources": {"main": "x"}, "ranges": [
            {"source": "main", "start": 0, "end": 1.001},
            {"source": "main", "start": 2.002, "end": 3.003}]}, media())
        actual = copy.deepcopy(plan)
        self.assertTrue(w.compare(plan, actual)["passed"])
        actual["clips"][1]["source_start_frame"] += 1
        self.assertFalse(w.compare(plan, actual)["passed"])
        actual["clips"].pop()
        self.assertIn("Clip count differs", w.compare(plan, actual)["errors"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.source = cls.root / "source space.mp4"
        w.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
               "testsrc2=size=180x320:rate=30:duration=3", "-f", "lavfi", "-i",
               "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(cls.source)])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self):
        root = self.root / self._testMethodName
        root.mkdir()
        owner = w.editorial(KIT)
        words = [{"text": "One", "start": .12, "end": .38, "score": 1},
                 {"text": "idea.", "start": .44, "end": .7, "score": 1},
                 {"text": "Clear", "start": 1.5, "end": 1.72, "score": 1},
                 {"text": "proof.", "start": 1.78, "end": 2.02, "score": 1}]
        edl = owner.build_editorial_plan(words, source_id="main", source_path=str(self.source),
                                         source_duration_s=3, grade="none")["edl"]
        path = root / "draft.json"
        w.write(path, edl)
        snapped = w.snap_edl(KIT, path)
        approved = root / "frame-edl.json"
        w.write(approved, snapped)
        contract_dir = KIT / "Editing_OS/Video Editing/Contracts/examples"
        context = w.load(contract_dir / "production-context.v1.example.json")
        adapter = w.adapter(KIT)
        context["governing_documents"] = [{"role": role, "path": relative,
            "sha256": w.sha(KIT / "Editing_OS" / relative)}
            for role, relative in adapter.GOVERNING_DOCUMENTS.items()]
        context_path = root / "context.json"
        w.write(context_path, context)
        taste_path = root / "taste.json"
        taste = w.load(contract_dir / "taste-selection.v1.example.json")
        w.write(taste_path, taste)
        timeline = root / "timeline.json"
        retimed = root / "words.json"
        w.write(timeline, {"timeline_map": snapped["editorial"]["timeline_map"]})
        w.write(retimed, {"retimed_words": snapped["editorial"]["retimed_words"]})
        approval = w.load(contract_dir / "edl-approval.v1.example.json")
        preview = root / "preview.mp4"
        shutil.copyfile(self.source, preview)
        for key, value in [("production_context", context_path), ("edl", approved),
                           ("preview", preview), ("timeline_map", timeline), ("retimed_words", retimed)]:
            approval[key] = {"path": str(value), "sha256": w.sha(value)}
        approval["approval"].update(approved_edl_sha256=w.sha(approved),
            selected_taste_selection_sha256=w.sha(taste_path),
            timeline_fingerprint=adapter.caption_timeline_fingerprint(
                snapped["editorial"]["timeline_map"], snapped["editorial"]["retimed_words"]))
        approval_path = root / "approval.json"
        w.write(approval_path, approval)
        auth = adapter.check_edl_approval(approval_path, edl_path=approved, taste_selection_path=taste_path)
        auth_path = root / "authorization.json"
        w.write(auth_path, auth)
        return approved, auth_path

    def test_probe_cfr_portrait_and_audio(self):
        info = w.inspect(self.source)
        self.assertEqual(info["frame_count"], 90)
        self.assertEqual(info["fps"], "30")
        self.assertTrue(info["constant_frame_rate"])
        self.assertTrue(info["has_audio"])
        self.assertEqual((info["display_width"], info["display_height"]), (180, 320))

    def test_real_approval_consumed_and_changed_edl_refused(self):
        edl, auth = self.fixture()
        plan = w.make_plan(KIT, edl, auth)
        w.verify_plan(plan, KIT)
        self.assertGreaterEqual(len(plan["clips"]), 2)
        edl.write_text(edl.read_text() + " ", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            w.verify_plan(plan, KIT)

    def test_changed_source_refused(self):
        edl, auth = self.fixture()
        plan = w.make_plan(KIT, edl, auth)
        source_copy = self.source.read_bytes()
        try:
            self.source.write_bytes(source_copy + b"changed bytes")
            with self.assertRaisesRegex(ValueError, "stale"):
                w.verify_plan(plan, KIT)
        finally:
            self.source.write_bytes(source_copy)

    def test_forged_authorization_refused(self):
        edl, auth = self.fixture()
        value = w.load(auth)
        value["timeline_fingerprint"] = "0" * 64
        w.write(auth, value)
        with self.assertRaisesRegex(RuntimeError, "stale"):
            w.make_plan(KIT, edl, auth)


if __name__ == "__main__":
    unittest.main()

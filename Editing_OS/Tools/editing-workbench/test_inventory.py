"""Inventory diagnostics must preserve complete-file and review-depth evidence."""
import os
from pathlib import Path
import tempfile
import unittest
import inventory as i
import workbench as w

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"


class InventoryTests(unittest.TestCase):
    def test_complete_tail_link_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("one", "two"):
                skill = root / "Editing_OS/Tools" / name / "SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text("# Skill\n" + "long body\n" * 1000 + "[tail](missing.md)\n", encoding="utf-8")
            result = i.inventory(root, root)
            self.assertEqual(len(result["components"]), 2)
            self.assertEqual(result["read_failures"], [])
            for record in result["components"]:
                self.assertEqual(len(record["identical_copies"]), 1)
                self.assertEqual(record["reference_findings"][0]["target"], "missing.md")
                self.assertFalse(record["semantic_human_review"])
                self.assertFalse(record["execution_verified"])

    def test_scene_interval_and_anchor_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "graphics-plan.json"
            data = '{"cues":[{"id":"bad","graphic_type":"stat","start_sec":2,"end_sec":1,"anchor_sec":4}]}'
            path.write_text(data, encoding="utf-8")
            record = i.inspect_component(path, data, root, root)
            self.assertEqual(record["scene_items"][0]["type"], "stat")
            self.assertEqual(len(record["scene_timing_findings"]), 2)

    def test_ansi_vendor_text_is_labeled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "SKILL.md").write_bytes(b"# Vendor\nWindows \x96 text\n")
            result = i.inventory(root, root)
            self.assertEqual(result["read_failures"], [])
            self.assertEqual(result["source_files"][0]["encoding"], "cp1252")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ideogram4_hosted as engine


def valid_prompt() -> dict:
    return {
        "high_level_description": (
            "A clean editorial technology thumbnail with a restrained cyan accent."
        ),
        "style_description": {
            "aesthetics": "clean, modern, precise, generous negative space",
            "lighting": "soft controlled studio light with restrained contrast",
            "medium": "graphic_design",
            "art_style": "premium editorial technology poster",
            "color_palette": ["#0B1220", "#EAF2F8", "#43D9D1"],
        },
        "compositional_deconstruction": {
            "background": "A deep slate field with a subtle cool gradient.",
            "elements": [
                {
                    "type": "obj",
                    "bbox": [220, 520, 880, 940],
                    "desc": "A precise abstract glass interface form.",
                    "color_palette": ["#43D9D1", "#EAF2F8"],
                },
                {
                    "type": "text",
                    "bbox": [120, 70, 430, 620],
                    "text": "EDIT SMARTER",
                    "desc": "Bold geometric sans-serif headline, left aligned.",
                    "color_palette": ["#EAF2F8"],
                },
            ],
        },
    }


class PromptValidationTests(unittest.TestCase):
    def test_valid_prompt_and_summary(self) -> None:
        warnings = engine.validate_prompt(valid_prompt())
        self.assertEqual([], warnings)
        summary = engine.prompt_summary(valid_prompt())
        self.assertEqual("EDIT SMARTER", summary["literal_text"][0]["text"])
        self.assertEqual("#43D9D1", summary["style"]["color_palette"][2])

    def test_rejects_lowercase_palette(self) -> None:
        prompt = valid_prompt()
        prompt["style_description"]["color_palette"][0] = "#0b1220"
        with self.assertRaisesRegex(
            engine.PromptValidationError, "uppercase #RRGGBB"
        ):
            engine.validate_prompt(prompt)

    def test_rejects_invalid_bbox(self) -> None:
        prompt = valid_prompt()
        prompt["compositional_deconstruction"]["elements"][0]["bbox"] = [
            900,
            100,
            100,
            800,
        ]
        with self.assertRaisesRegex(engine.PromptValidationError, "y_min < y_max"):
            engine.validate_prompt(prompt)

    def test_rejects_wrong_style_key_order(self) -> None:
        prompt = valid_prompt()
        prompt["style_description"] = {
            "lighting": "soft",
            "aesthetics": "clean",
            "medium": "graphic_design",
            "art_style": "editorial",
        }
        with self.assertRaisesRegex(engine.PromptValidationError, "key order"):
            engine.validate_prompt(prompt)

    def test_rejects_unknown_key(self) -> None:
        prompt = valid_prompt()
        prompt["unexpected"] = True
        with self.assertRaisesRegex(engine.PromptValidationError, "unknown key"):
            engine.validate_prompt(prompt)

    def test_warns_when_layout_text_has_no_bbox(self) -> None:
        prompt = valid_prompt()
        prompt["compositional_deconstruction"]["elements"][1].pop("bbox")
        warnings = engine.validate_prompt(prompt)
        self.assertTrue(any("critical text placement" in item for item in warnings))


class AdapterTests(unittest.TestCase):
    def test_aspect_ratio(self) -> None:
        self.assertEqual("1:1", engine.aspect_ratio("2048x2048"))
        self.assertEqual("1:2", engine.aspect_ratio("1440x2880"))
        self.assertEqual("16:9", engine.aspect_ratio("2560x1440"))

    def test_multipart_contains_structured_fields(self) -> None:
        body, boundary = engine.encode_multipart(
            {
                "json_prompt": '{"hello":"world"}',
                "rendering_speed": "DEFAULT",
            }
        )
        self.assertIn(boundary.encode("ascii"), body)
        self.assertIn(b'name="json_prompt"', body)
        self.assertIn(b'{"hello":"world"}', body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode("ascii")))

    def test_dry_run_never_requires_key_or_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            prompt_path = temp / "prompt.json"
            output_path = temp / "output.png"
            prompt_path.write_text(
                json.dumps(valid_prompt(), ensure_ascii=False),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = engine.main(
                    [
                        "--prompt-json",
                        str(prompt_path),
                        "--output",
                        str(output_path),
                        "--purpose",
                        "thumbnail",
                        "--platform",
                        "YouTube",
                    ]
                )
            self.assertEqual(0, status)
            self.assertFalse(output_path.exists())
            plan = json.loads(stdout.getvalue())
            self.assertFalse(plan["executed"])
            self.assertEqual(0.06, plan["cost"]["estimated_cost_usd"])
            self.assertIn("no cost was incurred", stderr.getvalue())

    def test_execute_is_blocked_without_terms_acknowledgment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            prompt_path = temp / "prompt.json"
            prompt_path.write_text(
                json.dumps(valid_prompt(), ensure_ascii=False),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = engine.main(
                    [
                        "--prompt-json",
                        str(prompt_path),
                        "--output",
                        str(temp / "output.png"),
                        "--purpose",
                        "thumbnail",
                        "--platform",
                        "YouTube",
                        "--execute",
                        "--max-cost-usd",
                        "0.06",
                    ]
                )
            self.assertEqual(2, status)
            self.assertIn("--acknowledge-api-terms", stderr.getvalue())

    def test_execute_is_blocked_without_environment_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            prompt_path = temp / "prompt.json"
            prompt_path.write_text(
                json.dumps(valid_prompt(), ensure_ascii=False),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with (
                mock.patch.dict(engine.os.environ, {engine.SECRET_ENV: ""}),
                contextlib.redirect_stderr(stderr),
            ):
                status = engine.main(
                    [
                        "--prompt-json",
                        str(prompt_path),
                        "--output",
                        str(temp / "output.png"),
                        "--purpose",
                        "thumbnail",
                        "--platform",
                        "YouTube",
                        "--execute",
                        "--acknowledge-api-terms",
                        "--max-cost-usd",
                        "0.06",
                    ]
                )
            self.assertEqual(2, status)
            self.assertIn(engine.SECRET_ENV, stderr.getvalue())

    def test_output_targets_are_stable(self) -> None:
        output = Path("asset.png")
        self.assertEqual(output, engine._target_for_index(output, 0))
        self.assertEqual(Path("asset_2.png"), engine._target_for_index(output, 1))


if __name__ == "__main__":
    unittest.main()

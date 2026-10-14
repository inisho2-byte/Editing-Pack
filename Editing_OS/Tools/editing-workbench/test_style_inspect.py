from contextlib import redirect_stderr
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import style_inspect as inspector


class StyleObservationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def save(self, image, name="image.png", **kwargs):
        path = self.root / name
        image.save(path, **kwargs)
        return path

    def test_known_palette_coverage_and_source_identity(self):
        image = Image.new("RGB", (20, 10), "white")
        image.paste("red", (0, 0, 5, 10))
        path = self.save(image)
        result = inspector.inspect_image(path)
        self.assertEqual(result["source_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual({p["hex"]:p["fraction_of_included_samples"] for p in result["palette"]}, {"#FFFFFF":0.75,"#FF0000":0.25})
        self.assertAlmostEqual(result["relative_luminance"]["mean"], 0.75 + 0.25 * 0.2126)

    def test_roi_excludes_wrapper_pixels_and_bounds_are_relative(self):
        image = Image.new("RGB", (100, 80), "black")
        image.paste("white", (20, 10, 80, 70))
        result = inspector.inspect_image(self.save(image), (20,10,60,60), (35,25,30,30))
        self.assertEqual(result["palette"][0]["hex"], "#FFFFFF")
        self.assertEqual(result["declared_subject"]["normalized_xywh_in_roi"], [0.25,0.25,0.5,0.5])
        self.assertEqual(result["declared_subject"]["bounding_box_area_fraction"], 0.25)

    def test_hidden_rgb_does_not_pollute_visible_palette(self):
        image = Image.new("RGBA", (4, 1), (255,0,0,0))
        image.putpixel((0,0), (0,0,255,255))
        image.putpixel((1,0), (0,255,0,128))
        result = inspector.inspect_image(self.save(image))
        self.assertEqual(result["included_samples"],1)
        self.assertEqual(result["partial_alpha_samples"],1)
        self.assertEqual(result["palette"][0]["hex"],"#0000FF")

    def test_explicit_matte_changes_appearance_with_recorded_policy(self):
        path = self.save(Image.new("RGBA", (2,2), (255,0,0,0)))
        result = inspector.inspect_image(path, matte="#FFFFFF")
        self.assertEqual(result["palette"][0]["hex"],"#FFFFFF")
        self.assertEqual(result["alpha_policy"],"encoded_RGB_composite")
        self.assertEqual(result["included_samples"],4)

    def test_all_transparent_image_has_no_invented_palette_or_luminance(self):
        result=inspector.inspect_image(self.save(Image.new("RGBA",(2,2),(7,8,9,0))))
        self.assertEqual(result["palette"],[])
        self.assertIsNone(result["relative_luminance"]["mean"])

    def test_exif_rotation_uses_display_coordinates(self):
        exif=Image.Exif(); exif[274]=6
        path=self.save(Image.new("RGB",(20,10),"white"),"rotated.jpg",exif=exif)
        result=inspector.inspect_image(path, (0,0,10,20))
        self.assertEqual(result["display_dimensions"],[10,20])
        self.assertTrue(result["exif_orientation_normalized"])

    def test_invalid_or_outside_rectangles_and_matte_fail(self):
        path=self.save(Image.new("RGB",(20,20),"white"))
        for kwargs in [{"roi":(-1,0,2,2)},{"roi":(0,0,0,1)},{"roi":(0,0,21,1)},{"roi":(True,0,2,2)},{"roi":(4,4,8,8),"subject":(0,0,2,2)},{"matte":"blue"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                inspector.inspect_image(path,**kwargs)

    def test_animation_is_not_silently_reduced_to_a_still(self):
        path=self.save(Image.new("RGB",(4,4),"red"),"animated.webp",save_all=True,append_images=[Image.new("RGB",(4,4),"blue")],duration=100,loop=0)
        with self.assertRaises(ValueError): inspector.inspect_image(path)

    def test_sampling_is_bounded_and_deterministic(self):
        path=self.save(Image.new("RGB",(2001,1103),"white"))
        first=inspector.inspect_image(path)
        self.assertLessEqual(first["sample_count"],inspector.MAX_SAMPLES)
        self.assertEqual(first,inspector.inspect_image(path))

    def test_existing_output_and_source_are_preserved(self):
        path=self.save(Image.new("RGB",(4,4),"blue"))
        output=self.root/"observations.json"; output.write_text("keep")
        original=path.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(inspector.main([str(path),"--out",str(output)]),1)
        self.assertEqual(output.read_text(),"keep")
        self.assertEqual(path.read_bytes(),original)

    def test_failed_analysis_creates_no_output(self):
        path=self.save(Image.new("RGB",(4,4),"blue"))
        output=self.root/"observations.json"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(inspector.main([str(path),"--roi","0","0","9","9","--out",str(output)]),1)
        self.assertFalse(output.exists())

    def test_large_dimension_limit_applies_before_pixel_analysis(self):
        path=self.save(Image.new("RGB",(inspector.MAX_DIMENSION+1,1),"white"))
        with self.assertRaises(ValueError): inspector.inspect_image(path)


if __name__ == "__main__": unittest.main()

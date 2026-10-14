"""Local still-image observations, not style recognition or production approval."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import runtime_paths as runtime

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None
_DECOMPRESSION_BOMB = Image.DecompressionBombError if Image is not None else ValueError

MAX_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DIMENSION = 20_000
MAX_SAMPLES = 200_000
FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "BMP"}


def rect(value, width, height, label):
    if value is None:
        return (0, 0, width, height)
    if len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError(f"{label} must be four integer display-pixel coordinates")
    x, y, w, h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError(f"{label} is empty or outside the display image")
    return tuple(value)


def linear_srgb(channel):
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def inspect_image(path: Path, roi=None, subject=None, matte=None):
    if Image is None:
        raise ValueError("Missing optional Pillow; install requirements-style.lock.txt in the selected environment")
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Local image does not exist: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Image file exceeds the 64 MiB limit")
    if matte is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", matte):
        raise ValueError("Matte must be #RRGGBB")
    content = path.read_bytes()
    if len(content) > MAX_BYTES:
        raise ValueError("Image file exceeds the 64 MiB limit")
    digest = hashlib.sha256(content)
    # Decode the same bounded byte snapshot that was hashed, even if the source changes.
    with Image.open(io.BytesIO(content)) as source:
        if source.format not in FORMATS:
            raise ValueError("Use a PNG, JPEG, WebP, TIFF or BMP still")
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("Animated or multi-page inputs must be extracted to one still")
        raw_size = source.size
        if max(raw_size) > MAX_DIMENSION or raw_size[0] * raw_size[1] > MAX_PIXELS:
            raise ValueError("Image dimensions exceed the diagnostic limits")
        orientation = source.getexif().get(274, 1)
        if type(orientation) is not int or orientation not in range(1, 9):
            raise ValueError("Unsupported EXIF orientation; use a verified display still")
        image = ImageOps.exif_transpose(source).convert("RGBA")
    width, height = image.size
    x, y, w, h = rect(roi, width, height, "ROI")
    subject_box = rect(subject, width, height, "Subject") if subject is not None else None
    if subject_box:
        sx, sy, sw, sh = subject_box
        if sx < x or sy < y or sx + sw > x + w or sy + sh > y + h:
            raise ValueError("Declared subject must be inside the ROI")
    # No resampling: palette observations should not manufacture blended colors.
    stride = max(1, math.ceil(math.sqrt(w * h / MAX_SAMPLES)))
    while math.ceil(w / stride) * math.ceil(h / stride) > MAX_SAMPLES:
        stride += 1
    pixels = image.load()
    colors = Counter()
    sums = {}
    sampled = included = partial = invisible = 0
    luminance_sum = 0.0
    dark = light = 0
    matte_rgb = tuple(int(matte[i:i + 2], 16) for i in (1, 3, 5)) if matte else None
    for py in range(y, y + h, stride):
        for px in range(x, x + w, stride):
            r, g, b, a = pixels[px, py]
            sampled += 1
            invisible += int(a == 0)
            partial += int(0 < a < 255)
            if matte_rgb is None and a != 255:
                continue
            if matte_rgb is not None:
                r, g, b = [round(c * a / 255 + m * (1 - a / 255)) for c, m in zip((r, g, b), matte_rgb)]
            included += 1
            key = (r // 16, g // 16, b // 16)
            colors[key] += 1
            accumulator = sums.setdefault(key, [0, 0, 0])
            for index, channel in enumerate((r, g, b)):
                accumulator[index] += channel
            lum = 0.2126 * linear_srgb(r) + 0.7152 * linear_srgb(g) + 0.0722 * linear_srgb(b)
            luminance_sum += lum
            dark += int(lum < 0.05)
            light += int(lum > 0.8)
    palette = []
    for key, count in sorted(colors.items(), key=lambda pair: (-pair[1], pair[0]))[:12]:
        rgb = [round(v / count) for v in sums[key]]
        palette.append({"mean_rgb": rgb, "hex": "#" + "".join(f"{v:02X}" for v in rgb), "sample_count": count, "fraction_of_included_samples": round(count / included, 6)})
    report = {
        "path": str(path.resolve()), "source_sha256": digest.hexdigest(),
        "raw_dimensions": list(raw_size), "display_dimensions": [width, height],
        "exif_orientation": orientation, "exif_orientation_normalized": orientation not in (None, 1),
        "roi_display_xywh": [x, y, w, h], "sample_stride_pixels": stride,
        "sample_count": sampled, "included_samples": included,
        "transparent_samples": invisible, "partial_alpha_samples": partial,
        "alpha_policy": "opaque_only" if matte is None else "encoded_RGB_composite",
        "matte_rgb": list(matte_rgb) if matte_rgb else None,
        "color_interpretation": "Stored RGB values interpreted as sRGB; embedded ICC profiles are not converted.",
        "palette_quantization_step": 16, "palette": palette,
        "relative_luminance": {"mean": round(luminance_sum / included, 6) if included else None, "fraction_below_0_05": round(dark / included, 6) if included else None, "fraction_above_0_8": round(light / included, 6) if included else None},
        "declared_subject": None,
        "limitations": ["Sampled color buckets do not assign semantic palette roles.", "Declared bounds are not segmentation or visible silhouette area.", "No font, material, light, motion, artistic similarity or readiness inference.", "Sampling can miss thin lines, small accents and texture."],
    }
    if subject_box:
        sx, sy, sw, sh = subject_box
        report["declared_subject"] = {"display_xywh": list(subject_box), "normalized_xywh_in_roi": [round((sx - x) / w, 6), round((sy - y) / h, 6), round(sw / w, 6), round(sh / h, 6)], "bounding_box_area_fraction": round(sw * sh / (w * h), 6)}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime.common_args(parser)
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--subject", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--matte", help="Explicit #RRGGBB ground for alpha compositing")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        runtime.configure_args(args)
        args.out = runtime.output(args.out, require_workspace=True)
        if args.out.exists():
            raise ValueError("Output exists; choose a new path")
        observations = [inspect_image(p, args.roi, args.subject, args.matte) for p in args.images]
        payload = {"record_type": "local-style-reference-observations", "images": observations, "production_authority": False}
        encoded = json.dumps(payload, indent=2, allow_nan=False)
        # Exclusive creation also protects against a path appearing during analysis.
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    except (OSError, ValueError, _DECOMPRESSION_BOMB) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Observed {len(observations)} still(s): {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

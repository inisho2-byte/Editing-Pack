"""Signal and boundary regression coverage for the owned audio-motion helper."""
import importlib.util
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

spec = importlib.util.spec_from_file_location("audio_motion", Path(__file__).with_name("audio_motion.py"))
motion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motion)


class AudioMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def wav(self, name="signal.wav", frequency=1000, channels=1, seconds=0.4, silent=False):
        path = self.root / name
        with wave.open(str(path), "wb") as handle:
            handle.setparams((channels, 2, 16000, 0, "NONE", "not compressed"))
            values = []
            for i in range(int(16000 * seconds)):
                value = 0 if silent else round(16384 * math.sin(2 * math.pi * frequency * i / 16000))
                values.extend([value] if channels == 1 else [value, -value])
            handle.writeframes(struct.pack("<" + "h" * len(values), *values))
        return path

    def test_fft_impulse_and_tone(self):
        impulse = motion.fft([1.0] + [0.0] * 7)
        self.assertTrue(all(abs(v - 1) < 1e-10 for v in impulse))
        tone = motion.fft([math.sin(2 * math.pi * i / 8) for i in range(8)])
        self.assertAlmostEqual(abs(tone[1]), 4)
        self.assertAlmostEqual(abs(tone[7]), 4)

    def test_silence_is_zero(self):
        data = motion.analyze(self.wav(silent=True))
        self.assertEqual(data["frame_count"], 12)
        self.assertTrue(all(f["rms"] == f["peak"] == 0 and not any(f["bands"]) for f in data["frames"]))

    def test_spectrum_tracks_actual_frequency(self):
        for frequency in (250, 2000):
            data = motion.analyze(self.wav(f"{frequency}.wav", frequency=frequency), attack_ms=0, release_ms=0)
            row = data["frames"][5]
            band = max(range(24), key=lambda i: row["bands"][i])
            self.assertLessEqual(data["band_edges_hz"][band], frequency)
            self.assertGreater(data["band_edges_hz"][band + 1], frequency)
            self.assertAlmostEqual(row["rms"], 0.5 / math.sqrt(2), places=3)

    def test_stereo_phase_does_not_cancel_visualizer(self):
        mono = motion.analyze(self.wav())
        stereo = motion.analyze(self.wav("stereo.wav", channels=2))
        self.assertEqual(mono["frames"], stereo["frames"])

    def test_rational_fps_and_last_frame(self):
        data = motion.analyze(self.wav(seconds=0.41), fps="30000/1001")
        self.assertEqual(data["fps"], "30000/1001")
        self.assertEqual(data["frame_count"], 13)
        self.assertLess((data["frame_count"] - 1) / (30000 / 1001), data["duration_seconds"])

    def test_repeated_analysis_and_out_of_order_access(self):
        path = self.wav()
        first = motion.analyze(path)
        second = motion.analyze(path)
        self.assertEqual(first, second)
        self.assertEqual([first["frames"][i] for i in (10, 0, 5, 10)],
                         [second["frames"][i] for i in (10, 0, 5, 10)])
        self.assertTrue(all(0 <= v <= 1 for f in first["frames"] for v in f["bands"]))

    def test_invalid_inputs(self):
        path = self.wav()
        for kwargs in ({"fps": "0"}, {"fps": "nan"}, {"bands": 0},
                       {"fft_size": 1000}, {"attack_ms": float("nan")}, {"release_ms": -1}):
            with self.assertRaises((ValueError, ZeroDivisionError)):
                motion.analyze(path, **kwargs)
        wrong = self.root / "eight-bit.wav"
        with wave.open(str(wrong), "wb") as handle:
            handle.setparams((1, 1, 16000, 0, "NONE", "not compressed"))
            handle.writeframes(b"\x80" * 512)
        with self.assertRaisesRegex(ValueError, "16-bit PCM"):
            motion.analyze(wrong)

    def test_empty_and_truncated_audio_fail(self):
        empty = self.wav("empty.wav", seconds=0)
        with self.assertRaisesRegex(ValueError, "empty"):
            motion.analyze(empty)
        truncated = self.wav("truncated.wav")
        truncated.write_bytes(truncated.read_bytes()[:-50])
        with self.assertRaisesRegex(ValueError, "truncated"):
            motion.analyze(truncated)

    def test_cli_never_overwrites(self):
        path = self.wav()
        original = path.read_bytes()
        result = subprocess.run([sys.executable, "-B", str(Path(motion.__file__)), str(path), "--out", str(path)], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), original)
        out = self.root / "motion.json"
        args = [sys.executable, "-B", str(Path(motion.__file__)), str(path), "--out", str(out)]
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
        saved = out.read_bytes()
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
        self.assertEqual(out.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()

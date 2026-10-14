"""Offline, frame-indexed music analysis. No third-party runtime or render authority."""
from __future__ import annotations

import argparse
from array import array
import cmath
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import runtime_paths as runtime
import wave


def fft(values: list[float]) -> list[complex]:
    """Radix-2 FFT; input length must be a power of two."""
    n = len(values)
    if n < 2 or n & (n - 1):
        raise ValueError("FFT size must be a power of two >= 2")
    output = [complex(v) for v in values]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            output[i], output[j] = output[j], output[i]
    size = 2
    while size <= n:
        rotation = cmath.exp(-2j * math.pi / size)
        for start in range(0, n, size):
            weight = 1 + 0j
            for k in range(size // 2):
                left = output[start + k]
                right = weight * output[start + k + size // 2]
                output[start + k] = left + right
                output[start + k + size // 2] = left - right
                weight *= rotation
        size *= 2
    return output


def analyze(path: Path, fps: str = "30", bands: int = 24,
            fft_size: int = 1024, attack_ms: float = 35,
            release_ms: float = 180) -> dict:
    rate = Fraction(fps)
    if not 1 <= rate <= 120:
        raise ValueError("FPS must be between 1 and 120; rational rates supported")
    if not 4 <= bands <= 64:
        raise ValueError("bands must be between 4 and 64")
    if fft_size not in (512, 1024, 2048, 4096):
        raise ValueError("FFT size must be 512, 1024, 2048 or 4096")
    if not all(math.isfinite(v) and 0 <= v <= 2000 for v in (attack_ms, release_ms)):
        raise ValueError("smoothing times must be finite, from 0 to 2000 ms")
    with path.open("rb") as handle:
        identity = hashlib.file_digest(handle, "sha256").hexdigest()
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (fft_size - 1))
              for i in range(fft_size)]
    gain = 2 / sum(window)
    with wave.open(str(path), "rb") as source:
        sample_rate, channels, samples = source.getframerate(), source.getnchannels(), source.getnframes()
        if source.getsampwidth() != 2 or source.getcomptype() != "NONE":
            raise ValueError("analysis requires uncompressed signed 16-bit PCM WAV")
        if samples <= 0 or not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 8:
            raise ValueError("empty or unsupported audio geometry")
        duration = Fraction(samples, sample_rate)
        frame_count = math.ceil(duration * rate)
        if frame_count > 72000:
            raise ValueError("analysis exceeds 72000 frames; analyze a reviewed excerpt")
        edges = [40 * (sample_rate / 2 / 40) ** (i / bands) for i in range(bands + 1)]
        bins = []
        for lo, hi in zip(edges, edges[1:]):
            indices = [k for k in range(1, fft_size // 2 + 1)
                       if lo <= k * sample_rate / fft_size < hi]
            bins.append(indices or [max(1, min(fft_size // 2, round(math.sqrt(lo * hi) * fft_size / sample_rate)))])
        attack = math.exp(-1 / (float(rate) * attack_ms / 1000)) if attack_ms else 0
        release = math.exp(-1 / (float(rate) * release_ms / 1000)) if release_ms else 0
        previous = [0.0] * bands
        frames = []
        for frame in range(frame_count):
            center = int(Fraction(frame, 1) / rate * sample_rate)
            left = center - fft_size // 2
            begin, end = max(0, left), min(samples, left + fft_size)
            source.setpos(begin)
            raw = source.readframes(end - begin)
            if len(raw) != (end - begin) * channels * 2:
                raise ValueError("truncated PCM data")
            pcm = array("h")
            pcm.frombytes(raw)
            if sys.byteorder != "little":
                pcm.byteswap()
            energy = [0.0] * (fft_size // 2 + 1)
            square_sum = 0.0
            peak = 0.0
            for channel in range(channels):
                signal = [0.0] * fft_size
                for i in range(end - begin):
                    value = pcm[i * channels + channel] / 32768
                    signal[begin - left + i] = value
                    square_sum += value * value
                    peak = max(peak, abs(value))
                spectrum = fft([v * w for v, w in zip(signal, window)])
                for k in range(len(energy)):
                    energy[k] += (abs(spectrum[k]) * gain) ** 2 / channels
            levels = []
            for band, indices in enumerate(bins):
                amplitude = math.sqrt(sum(energy[k] for k in indices) / len(indices))
                dbfs = 20 * math.log10(max(amplitude, 1e-12))
                target = max(0.0, min(1.0, (dbfs + 80) / 80))
                coefficient = attack if target > previous[band] else release
                previous[band] = coefficient * previous[band] + (1 - coefficient) * target
                levels.append(round(previous[band], 6))
            # Mean channel energy prevents opposite-phase stereo from becoming false silence.
            rms = math.sqrt(square_sum / ((end - begin) * channels))
            frames.append({"rms": round(rms, 6), "peak": round(peak, 6), "bands": levels})
    return {"format": "editing-pack-audio-motion/v1", "source_sha256": identity,
            "sample_rate_hz": sample_rate, "channels": channels,
            "duration_seconds": float(duration), "fps": str(rate), "frame_count": frame_count,
            "fft_size": fft_size, "band_edges_hz": [round(v, 3) for v in edges],
            "scale": {"floor_dbfs": -80, "ceiling_dbfs": 0,
                      "attack_ms": attack_ms, "release_ms": release_ms}, "frames": frames}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    runtime.common_args(parser)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fps", default="30")
    parser.add_argument("--bands", type=int, default=24)
    parser.add_argument("--fft-size", type=int, default=1024)
    parser.add_argument("--attack-ms", type=float, default=35)
    parser.add_argument("--release-ms", type=float, default=180)
    args = parser.parse_args()
    try:
        runtime.configure_args(args)
        args.out = runtime.output(args.out, require_workspace=True)
        if args.audio.resolve() == args.out.resolve() or args.out.exists():
            raise ValueError("output must be new and must not replace the source")
        data = analyze(args.audio, args.fps, args.bands, args.fft_size, args.attack_ms, args.release_ms)
        with args.out.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            handle.write("\n")
        print(f"Analyzed {data['frame_count']} frames at {data['fps']} FPS. Not render/QA approval.")
        return 0
    except (OSError, ValueError, ZeroDivisionError, wave.Error) as exc:
        print(f"Audio analysis failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

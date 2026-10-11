"""Word-level alignment and corrected-script remapping.

WhisperX is the production backend because it performs phoneme forced alignment.
The openai-whisper backend remains available only as an explicit diagnostic
choice; its raw ASR word timestamps are never treated as equivalent alignment
evidence.

``force_align_to_script`` does not pretend to hear audio.  It preserves exact
ASR anchors where the script matches and explicitly marks any replacement or
interpolated timings as approximate so the QA layer can surface them.
"""

from __future__ import annotations

# Resolve only this standalone toolkit's owned shared runtime module.
import sys as _runtime_sys
from pathlib import Path as _RuntimePath
for _runtime_parent in _RuntimePath(__file__).resolve().parents:
    if (_runtime_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_runtime_parent))
        break
import runtime_paths as runtime

import difflib
import math
import re
import warnings


class AlignmentError(RuntimeError):
    """Raised when trustworthy word timing cannot be produced."""


def transcribe_words(audio, model="base", backend="auto"):
    """Return normalized word dictionaries for ``audio``.

    Each word contains ``text``, ``start``, ``end``, ``score`` and
    ``timing_source``. ``auto`` means "select the production forced aligner";
    it deliberately does not downgrade to raw Whisper timestamps. Operators
    must request ``backend='whisper'`` explicitly to accept lower-confidence
    timing.
    """
    if backend not in {"auto", "whisperx", "whisper"}:
        raise ValueError(f"unknown alignment backend: {backend}")

    if backend in ("auto", "whisperx"):
        try:
            words = _whisperx(audio, model)
            return normalize_words(words, source="whisperx-forced")
        except (ImportError, ModuleNotFoundError) as exc:
            raise AlignmentError(
                "WhisperX is required for production forced alignment but is "
                "not installed. Install whisperx, supply --words-json from a "
                "forced aligner, or explicitly choose --backend whisper for "
                "lower-confidence raw ASR timestamps."
            ) from exc

    warnings.warn(
        "Using explicitly requested raw Whisper word timestamps. These timings "
        "are lower-confidence than forced alignment and require waveform review.",
        RuntimeWarning,
        stacklevel=2,
    )
    return normalize_words(
        _whisper(audio, model), source="whisper-word-timestamp-low-confidence"
    )


def _whisper(audio, model_name):
    import whisper

    cache = runtime.model_environment()
    model = whisper.load_model(model_name, download_root=str(cache / "whisper"))
    result = model.transcribe(audio, word_timestamps=True)
    words = []
    for seg in result.get("segments", []):
        for word in seg.get("words", []):
            words.append(
                {
                    "text": word["word"].strip(),
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                    "score": float(word.get("probability", 1.0)),
                }
            )
    return words


def _whisperx(audio, model_name):
    import whisperx

    cache = runtime.model_environment()

    device = "cpu"
    asr = whisperx.load_model(model_name, device, compute_type="int8", download_root=str(cache / "whisperx"))
    audio_arr = whisperx.load_audio(audio)
    result = asr.transcribe(audio_arr)
    align_model, metadata = whisperx.load_align_model(
        language_code=result["language"], device=device, model_dir=str(cache / "alignment")
    )
    aligned = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio_arr,
        device,
        return_char_alignments=False,
    )
    words = []
    for seg in aligned.get("segments", []):
        for word in seg.get("words", []):
            if "start" in word and "end" in word:
                words.append(
                    {
                        "text": str(word["word"]).strip(),
                        "start": float(word["start"]),
                        "end": float(word["end"]),
                        "score": float(word.get("score", 1.0)),
                    }
                )
    return words


def normalize_words(words, source=None):
    """Copy and normalize a word list without inventing or reordering timing."""
    normalized = []
    for index, word in enumerate(words):
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        try:
            start = float(word["start"])
            end = float(word["end"])
            score = float(word.get("score", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise AlignmentError(f"word {index} has invalid timing fields") from exc
        if not (math.isfinite(start) and math.isfinite(end) and math.isfinite(score)):
            raise AlignmentError(f"word {index} contains non-finite timing")
        item = dict(word)
        item.update(
            {
                "text": text,
                "start": round(start, 6),
                "end": round(end, 6),
                "score": max(0.0, min(1.0, score)),
                "timing_source": word.get("timing_source") or source or "provided",
            }
        )
        normalized.append(item)
    if not normalized:
        raise AlignmentError("alignment produced no spoken words; refusing to fabricate captions")
    return normalized


def _tokenize(text):
    return re.findall(r"\S+", text)


def _norm(token):
    return re.sub(r"[^\w]", "", token, flags=re.UNICODE).casefold()


def _weight(token):
    """Approximate spoken share; sublinear length avoids starving short words."""
    return max(1.0, len(_norm(token)) ** 0.72)


def _script_relatedness(hypothesis, reference):
    """Return conservative evidence that two token streams describe one speech.

    Exact anchors are the decisive signal. Character similarity only helps
    short corrections such as ``North`` -> ``NorthStar``; it cannot rescue a
    five-token-or-longer script with only one exact anchor.
    """
    matcher = difflib.SequenceMatcher(a=hypothesis, b=reference, autojunk=False)
    exact = sum(block.size for block in matcher.get_matching_blocks())
    longest = max(len(hypothesis), len(reference), 1)
    token_ratio = matcher.ratio()
    character_ratio = difflib.SequenceMatcher(
        a=" ".join(hypothesis), b=" ".join(reference), autojunk=False
    ).ratio()
    if longest >= 5 and exact <= 1:
        return False, exact, token_ratio, character_ratio
    if longest >= 5 and exact / longest < 0.30:
        return character_ratio >= 0.66, exact, token_ratio, character_ratio
    if longest < 5 and exact == 0:
        return character_ratio >= 0.58, exact, token_ratio, character_ratio
    return token_ratio >= 0.35 or character_ratio >= 0.58, exact, token_ratio, character_ratio


def _allocate(tokens, first, last, start, end, source, score=0.0):
    if end <= start:
        raise AlignmentError("script alignment has no audio span for inserted words")
    weights = [_weight(tokens[i]["text"]) for i in range(first, last)]
    total = sum(weights)
    cursor = start
    for offset, idx in enumerate(range(first, last)):
        boundary = end if idx == last - 1 else cursor + (end - start) * weights[offset] / total
        tokens[idx]["start"] = round(cursor, 6)
        tokens[idx]["end"] = round(boundary, 6)
        tokens[idx]["score"] = score
        tokens[idx]["timing_source"] = source
        cursor = boundary


def force_align_to_script(asr_words, script_text):
    """Map a corrected reference script onto real ASR timing anchors.

    Exact token matches retain their original timing and confidence. Replaced
    blocks are distributed across the corresponding ASR audio span. Script-only
    insertions use available pause time, or split the nearest anchored word span
    when ASR likely collapsed multiple spoken words into one. Every approximation
    carries ``timing_source`` metadata for validation and review.

    This function is intentionally correction-only. A reference script may fix
    names, terminology, punctuation, or tokenization, but may not silently omit
    words present in the aligned speech. Editorial deletions belong in the EDL;
    captions must then be regenerated from the post-cut alignment.
    """
    asr_words = normalize_words(asr_words)
    reference = _tokenize(script_text)
    if not reference:
        return asr_words

    hypothesis = [_norm(word["text"]) for word in asr_words]
    ref_norm = [_norm(token) for token in reference]
    out = [
        {
            "text": token,
            "start": None,
            "end": None,
            "score": 0.0,
            "timing_source": "script-unresolved",
        }
        for token in reference
    ]

    matcher = difflib.SequenceMatcher(a=hypothesis, b=ref_norm, autojunk=False)
    related, matching_tokens, token_ratio, character_ratio = _script_relatedness(
        hypothesis, ref_norm
    )
    if not related:
        raise AlignmentError(
            "corrected script is not recognizably related to the transcript; "
            "verify the script or rerun ASR with a stronger model "
            f"(exact anchors={matching_tokens}, token similarity={token_ratio:.2f}, "
            f"character similarity={character_ratio:.2f})"
        )
    opcodes = matcher.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "delete":
            omitted = " ".join(word["text"] for word in asr_words[i1:i2])
            raise AlignmentError(
                "corrected script omits aligned spoken token(s): "
                f"{omitted!r}. --script only corrects names/terminology; make "
                "editorial deletions in the video edit and regenerate captions "
                "from post-cut word timings"
            )
        if tag == "replace" and (i2 - i1) > (j2 - j1):
            # A harmless tokenization merge ("North Star" -> "NorthStar") keeps
            # every normalized character. Any other shortening could conceal
            # audible words and is therefore refused.
            source_compact = "".join(hypothesis[i1:i2])
            reference_compact = "".join(ref_norm[j1:j2])
            if source_compact != reference_compact:
                omitted = " ".join(word["text"] for word in asr_words[i1:i2])
                replacement = " ".join(reference[j1:j2])
                raise AlignmentError(
                    "corrected script shortens an aligned spoken block: "
                    f"{omitted!r} -> {replacement!r}. --script cannot remove "
                    "spoken content; edit the source and realign first"
                )

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for offset in range(j2 - j1):
                source_word = asr_words[i1 + offset]
                out[j1 + offset].update(
                    {
                        "start": source_word["start"],
                        "end": source_word["end"],
                        "score": source_word.get("score", 1.0),
                        "timing_source": source_word.get("timing_source", "asr-anchor"),
                    }
                )
        elif tag == "replace" and i2 > i1:
            timing_source = (
                "script-tokenization"
                if (i2 - i1) > (j2 - j1)
                else "script-replacement"
            )
            _allocate(
                out,
                j1,
                j2,
                asr_words[i1]["start"],
                asr_words[i2 - 1]["end"],
                timing_source,
            )
        # Insert remains unresolved and is filled from neighboring audio.

    _interpolate_missing(out)
    return normalize_words(out)


def _missing_runs(tokens):
    index = 0
    while index < len(tokens):
        if tokens[index]["start"] is not None and tokens[index]["end"] is not None:
            index += 1
            continue
        first = index
        while index < len(tokens) and (
            tokens[index]["start"] is None or tokens[index]["end"] is None
        ):
            index += 1
        yield first, index


def _interpolate_missing(tokens):
    """Resolve script-only runs while keeping all timing inside known audio."""
    known = [
        index
        for index, token in enumerate(tokens)
        if token["start"] is not None and token["end"] is not None
    ]
    if not known:
        raise AlignmentError(
            "corrected script has no token anchors in the transcript; "
            "use a better ASR model or verify the script"
        )

    for first, last in list(_missing_runs(tokens)):
        left = first - 1 if first > 0 else None
        right = last if last < len(tokens) else None

        if left is not None and right is not None:
            gap_start = tokens[left]["end"]
            gap_end = tokens[right]["start"]
            if gap_end - gap_start >= 0.02 * (last - first):
                _allocate(tokens, first, last, gap_start, gap_end, "script-interpolated")
            else:
                # No usable pause: ASR likely collapsed the inserted word(s).
                span_start = tokens[left]["start"]
                span_end = tokens[right]["end"]
                _allocate(
                    tokens,
                    left,
                    right + 1,
                    span_start,
                    span_end,
                    "script-interpolated",
                )
        elif right is not None:
            # Share the first anchored word's audio span with leading script words.
            _allocate(
                tokens,
                first,
                right + 1,
                tokens[right]["start"],
                tokens[right]["end"],
                "script-interpolated",
            )
        elif left is not None:
            # Share the final anchored word's audio span with trailing script words.
            _allocate(
                tokens,
                left,
                last,
                tokens[left]["start"],
                tokens[left]["end"],
                "script-interpolated",
            )

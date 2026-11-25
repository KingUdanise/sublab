"""Trascrizione locale (faster-whisper) con timing per parola e divisione in cue.

Il modello gira su GPU se CTranslate2 la supporta, altrimenti ripiega su CPU int8.
"""
from __future__ import annotations

import glob
import math
import os
import re
import site
import sys

DEFAULT_MODEL = "large-v3"
_models: dict[tuple[str, str, str], object] = {}
_dll_ready = False


def _ensure_cuda_dlls():
    """CTranslate2 cerca cublas64_12.dll / cudnn: li prendiamo da torch o dai pacchetti nvidia."""
    global _dll_ready
    if _dll_ready or os.name != "nt":
        return
    _dll_ready = True
    roots = []
    try:
        roots += site.getsitepackages()
    except Exception:
        pass
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    dirs = []
    for root in roots:
        dirs += glob.glob(os.path.join(root, "torch", "lib"))
        dirs += glob.glob(os.path.join(root, "nvidia", "*", "bin"))
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def _load(model_size: str, device: str, compute_type: str):
    _ensure_cuda_dlls()
    from faster_whisper import WhisperModel

    key = (model_size, device, compute_type)
    if key in _models:
        return _models[key]
    m = WhisperModel(model_size, device=device, compute_type=compute_type)
    _models[key] = m
    return m


def _pick_model(model_size: str):
    """Prova cuda/float16, poi cuda/int8_float16, infine cpu/int8."""
    last = None
    for device, ctype in (("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")):
        try:
            return _load(model_size, device, ctype), device, ctype
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"impossibile caricare il modello {model_size}: {last}")


def transcribe(audio_path: str, model_size: str = DEFAULT_MODEL, language: str | None = "it",
               progress=None) -> dict:
    """Trascrive un wav e restituisce {'language':..., 'words': [...], 'segments': [...]}."""
    def run(model, device, ctype):
        segments, info = model.transcribe(
            audio_path,
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 250},
            condition_on_previous_text=False,
        )
        words, segs = [], []
        for seg in segments:                     # l'errore CUDA emerge qui, in streaming
            segs.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
            for w in (seg.words or []):
                txt = w.word.strip()
                if not txt:
                    continue
                words.append({"w": txt, "s": float(w.start), "e": float(w.end)})
            if progress:
                progress(f"{seg.end:6.1f}s  {seg.text.strip()[:60]}")
        return {
            "language": getattr(info, "language", language),
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
            "duration": float(getattr(info, "duration", 0.0) or 0.0),
            "device": f"{device}/{ctype}",
            "words": words,
            "segments": segs,
        }

    model, device, ctype = _pick_model(model_size)
    if progress:
        progress(f"modello {model_size} su {device}/{ctype}")
    try:
        return run(model, device, ctype)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if device == "cpu" or not any(k in msg for k in ("cublas", "cudnn", "cuda", "gpu")):
            raise
        if progress:
            progress(f"GPU non utilizzabile ({e}) → ripiego su CPU int8")
        model = _load(model_size, "cpu", "int8")
        return run(model, "cpu", "int8")


# --------------------------------------------------------------------------- cue builder

PUNCT_BREAK = re.compile(r"[.!?…]+$")


def build_cues(words: list[dict], max_chars: int = 38, max_dur: float = 2.6,
               min_dur: float = 0.4, gap_break: float = 0.40) -> list[dict]:
    """Raggruppa le parole in sottotitoli leggibili, senza spezzare frasi a meta'."""
    cues: list[dict] = []
    cur: list[dict] = []

    def flush():
        if not cur:
            return
        text = " ".join(w["w"] for w in cur)
        cues.append({
            "start": round(cur[0]["s"], 3),
            "end": round(max(cur[-1]["e"], cur[0]["s"] + min_dur), 3),
            "text": text,
            "words": [dict(w) for w in cur],
        })
        cur.clear()

    for w in words:
        if cur:
            gap = w["s"] - cur[-1]["e"]
            dur = w["e"] - cur[0]["s"]
            chars = len(" ".join([x["w"] for x in cur] + [w["w"]]))
            if gap >= gap_break or dur > max_dur or chars > max_chars:
                flush()
        cur.append(w)
        if PUNCT_BREAK.search(w["w"]) and len(" ".join(x["w"] for x in cur)) > 12:
            flush()
    flush()

    # niente cue sovrapposti
    for a, b in zip(cues, cues[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + min_dur, round(b["start"], 3))

    return _merge_tiny(cues, max_chars=max_chars)


def _merge_tiny(cues: list[dict], max_chars: int, min_words: int = 3, min_chars: int = 12) -> list[dict]:
    """Fonde i sottotitoli troppo corti ("Un", "E poi") con il vicino, se la lunghezza lo consente."""
    def ws(c):
        return list(c.get("words") or [{"w": w, "s": c["start"], "e": c["end"]} for w in c["text"].split()])

    out: list[dict] = []
    for c in cues:
        if not out:
            out.append(c)
            continue
        prev = out[-1]
        tiny = len(ws(c)) < min_words or len(c["text"]) < min_chars
        merged = f"{prev['text']} {c['text']}".strip()
        if tiny and (c["start"] - prev["end"]) <= 0.45 and len(merged) <= max_chars:
            prev["text"] = merged
            prev["end"] = c["end"]
            prev["words"] = ws(prev) + ws(c)
        else:
            out.append(c)

    if len(out) > 1:
        first, second = out[0], out[1]
        merged = f"{first['text']} {second['text']}".strip()
        if (len(ws(first)) < min_words or len(first["text"]) < min_chars) and \
                (second["start"] - first["end"]) <= 0.45 and len(merged) <= max_chars:
            second["text"] = merged
            second["start"] = first["start"]
            second["words"] = ws(first) + ws(second)
            out.pop(0)
    return out


def cue_frames(cues: list[dict], fps: float, offset: float = 0.0) -> list[dict]:
    """Converte i cue in frame (interi) di timeline, con timing parola per parola."""
    out = []
    for c in cues:
        s = int(round((c["start"] + offset) * fps))
        e = int(round((c["end"] + offset) * fps))
        if e <= s:
            e = s + 1
        words = []
        for w in c.get("words", []):
            ws = int(round((w["s"] + offset) * fps))
            we = int(round((w["e"] + offset) * fps))
            words.append({"w": w["w"], "s": max(s, min(ws, e - 1)), "e": max(ws + 1, min(we, e))})
        out.append({"start": s, "end": e, "text": c["text"], "words": words})
    return out


def stats(cues: list[dict]) -> dict:
    if not cues:
        return {"count": 0}
    d = [c["end"] - c["start"] for c in cues]
    return {
        "count": len(cues),
        "chars": sum(len(c["text"]) for c in cues),
        "avg_dur": round(sum(d) / len(d), 2),
        "min_dur": round(min(d), 2),
        "max_dur": round(max(d), 2),
        "cps": round(sum(len(c["text"]) / max(x, 0.1) for c, x in zip(cues, d)) / len(cues), 1),
        "median_words": int(math.floor(sorted(len(c.get("words", [])) for c in cues)[len(cues) // 2])),
    }

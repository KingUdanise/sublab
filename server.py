"""SubLab - backend locale del plugin sottotitoli per DaVinci Resolve.

    python server.py            -> http://127.0.0.1:8777

Gira in locale: ASR faster-whisper + scrittura stile sulle Fusion Text+ via API Resolve.
"""
from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
sys_path = HERE
import sys  # noqa: E402

if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import asr  # noqa: E402
import bridge  # noqa: E402
import cues4  # noqa: E402
import fonts  # noqa: E402

OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)
STATE_FILE = os.path.join(OUT_DIR, "state.json")

app = FastAPI(title="SubLab")

STATE: dict = {
    "style": {
        "font": "Helvetica Now Display",
        "font_style": "Bold",
        "size": 0.07,
        "cx": 0.5,
        "cy": 0.12,
        "fill_on": 1,
        "fill": [1.0, 0.666666666666667, 0.0],
        "outline_on": 0,
        "outline": [0.0, 0.0, 0.0],
        "outline_thickness": 0.02,
        "shadow_on": 0,
        "shadow": [0.0, 0.0, 0.0],
        "shadow_offset": [0.004, -0.004],
        "highlight_on": 0,
        "highlight": [0.0, 0.208, 1.0],
    },
    "cues": [],
    "meta": {},
    "job": {"state": "idle", "progress": 0.0, "log": []},
}


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                saved = json.load(fh)
            for k in ("style", "cues", "meta"):
                if k in saved:
                    STATE[k] = saved[k]
        except Exception:
            traceback.print_exc()


def _save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump({k: STATE[k] for k in ("style", "cues", "meta")}, fh, ensure_ascii=False, indent=1)
    except Exception:
        traceback.print_exc()


# --------------------------------------------------------------------------- API

@app.get("/api/info")
def api_info():
    try:
        data = bridge.info()
        data["style"] = bridge.style_of_first_sub() or STATE["style"]
        data["subs"] = bridge.sub_clips()
        return data
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e), "offline": True}, status_code=200)


@app.get("/api/fonts")
def api_fonts():
    return {"fonts": fonts.catalog()}


@app.get("/fonts/{filename}")
def api_font_file(filename: str):
    p = fonts.font_file(filename)
    if not p:
        raise HTTPException(404, "font non trovato")
    return FileResponse(p, media_type="font/ttf" if p.lower().endswith(".ttf") else "font/otf")


@app.get("/api/state")
def api_state():
    return {"style": STATE["style"], "cues": STATE["cues"], "meta": STATE["meta"], "job": STATE["job"]}


class StyleBody(BaseModel):
    style: dict


@app.post("/api/style")
def api_set_style(body: StyleBody):
    STATE["style"].update(body.style)
    _save_state()
    return {"ok": True, "style": STATE["style"]}


def _fused_style(style: dict) -> dict:
    """Normalizza font e stile sui nomi DICHIARATI nel file: Fusion risponde
    "Font Not Found: HelveticaNowDisplay Bold" se scriviamo il nome del registro."""
    s = dict(style or {})
    fam = fonts.resolve_family(s.get("font"))
    s["font"] = fam
    s["font_style"] = fonts.resolve_style(fam, s.get("font_style"))
    return s


class ApplyBody(BaseModel):
    target: str = "all"          # all | selected
    style: dict | None = None
    only_font: bool = False      # ripara solo Font/Stile senza toccare i colori
    frames: list[int] | None = None  # start frame dei cue selezionati nella UI


@app.post("/api/apply")
def api_apply(body: ApplyBody):
    style = _fused_style(body.style or STATE["style"])
    if body.only_font:
        style = {"font": style.get("font"), "font_style": style.get("font_style")}
    try:
        if body.target == "selected":
            t = bridge.timeline()
            items = []
            if body.frames:
                wanted = {int(fr) for fr in body.frames}
                items = [it for it in bridge.subtitle_items(t) if int(it.GetStart()) in wanted]
            if not items:
                sel = t.GetSelectedClips() or []
                items = [it for it in sel if bridge._is_subtitle_item(it)]
            if not items:
                raise bridge.ResolveError("Nessuna clip sub selezionata (né in UI né in timeline).")
        else:
            items = None
        res = bridge.apply_style(style, items)
        return {"ok": True, **res}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


@app.get("/api/still")
def api_still(frame: int | None = None):
    """Frame corrente (o a un certo frame) come PNG base64, per la preview."""
    try:
        t = bridge.timeline()
        saved = None
        if frame is not None:
            saved = t.GetCurrentTimecode()
            t.SetCurrentTimecode(_tc(frame, bridge.fps(t)))
        img = t.GetCurrentClipThumbnailImage() or {}
        if saved:
            t.SetCurrentTimecode(saved)
        data = img.get("data") or img.get("Data")
        if not data:
            return {"ok": False}
        if isinstance(data, str):
            b64 = data
        else:
            b64 = base64.b64encode(bytes(data)).decode()
        return {"ok": True, "width": img.get("width"), "height": img.get("height"), "data": b64}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _tc(frame: int, fps: float) -> str:
    fps_i = max(1, int(round(fps)))
    f = max(0, int(round(frame)))
    total_s, ff = divmod(f, fps_i)
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{ff:02d}"


class TranscribeBody(BaseModel):
    mode: str = "io"             # io | selection | all
    model: str = asr.DEFAULT_MODEL
    language: str | None = "it"
    max_chars: int = 38
    max_dur: float = 2.6
    max_words: int = cues4.MAX_WORDS
    use_cues4: bool = True       # usa il motore italiano cues4 (elisioni, no parole appese)


class _Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"
        self.progress = 0.0
        self.log: list[str] = []
        self.error = None

    def try_start(self) -> bool:
        with self.lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.progress = 0.0
            self.error = None
            self.log = []
            return True

    def finish(self, state: str, error: str | None = None):
        with self.lock:
            self.state = state
            self.error = error

    def add(self, msg: str, prog: float | None = None):
        with self.lock:
            self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")
            self.log = self.log[-200:]
            if prog is not None:
                self.progress = prog

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "progress": self.progress, "log": list(self.log), "error": self.error}


JOB = _Job()
STATE["job"] = JOB.snapshot()


@app.get("/api/job")
def api_job():
    snap = JOB.snapshot()
    STATE["job"] = snap
    return snap


@app.post("/api/transcribe")
def api_transcribe(body: TranscribeBody):
    if not JOB.try_start():
        return JSONResponse({"ok": False, "error": "trascrizione già in corso"}, status_code=409)

    def run():
        try:
            JOB.add(f"range mode = {body.mode}", 0.02)
            start, end, why = bridge.subtitle_range(body.mode)
            f = bridge.fps()
            JOB.add(f"range {start}..{end} frame ({why}) = {(end - start) / f:.2f}s @ {f}fps", 0.05)

            def progress(msg):
                JOB.add(msg, None)

            target = os.path.join(OUT_DIR, "range_audio.wav")
            JOB.add("render audio del range dalla timeline…", 0.1)
            audio_path = bridge.render_range_audio(start, end, target, progress=progress)
            JOB.add(f"audio pronto: {os.path.basename(audio_path)} "
                    f"({os.path.getsize(audio_path) / 1e6:.1f} MB)", 0.35)

            res = asr.transcribe(audio_path, body.model, body.language, progress=progress)
            JOB.add(f"trascritto: {len(res['words'])} parole, lingua {res['language']} "
                    f"({res['device']})", 0.8)

            warnings: list[str] = []
            validation_errors: list[dict] = []
            if body.use_cues4:
                built = cues4.build(res["words"], fps=f, max_words=body.max_words, max_dur=body.max_dur)
                cues_sec = built["cues"]
                warnings = built.get("warnings", [])
                validation_errors = cues4.errors_only(
                    cues4.validate(cues_sec, fps=f, max_words=body.max_words, max_dur=body.max_dur)
                )
                if warnings:
                    JOB.add(f"cues4: {len(warnings)} avvisi, {len(validation_errors)} errori residui", 0.9)
            else:
                cues_sec = asr.build_cues(res["words"], max_chars=body.max_chars, max_dur=body.max_dur)

            cues = asr.cue_frames(cues_sec, f, offset=start / f)
            STATE["cues"] = cues
            STATE["meta"] = {
                "range": [start, end],
                "range_why": why,
                "fps": f,
                "language": res["language"],
                "model": body.model,
                "device": res["device"],
                "engine": "cues4" if body.use_cues4 else "asr",
                "warnings": warnings,
                "validation_errors": len(validation_errors),
                "stats": asr.stats(cues_sec),
                "audio": audio_path,
            }
            _save_state()
            JOB.add(f"{len(cues)} sottotitoli pronti", 1.0)
            JOB.finish("done")
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            JOB.add("ERRORE: " + err)
            traceback.print_exc()
            JOB.finish("error", err)

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "job": JOB.snapshot()}


class CuesBody(BaseModel):
    cues: list[dict]


@app.post("/api/cues")
def api_cues(body: CuesBody):
    STATE["cues"] = body.cues
    _save_state()
    return {"ok": True, "count": len(body.cues)}


def export_backup() -> str | None:
    """Salva un .drp di sicurezza prima di scrivere in timeline."""
    try:
        p = bridge.project()
        pm = bridge.pm()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUT_DIR, "backup", f"{p.GetName()}_{stamp}.drp")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path if pm.ExportProject(p.GetName(), path, True) else None
    except Exception:
        traceback.print_exc()
        return None


@app.post("/api/backup")
def api_backup():
    path = export_backup()
    return {"ok": bool(path), "path": path}


def _unique_timeline_name(p, base: str) -> str:
    existing = set()
    try:
        for i in range(1, int(p.GetTimelineCount() or 0) + 1):
            t = p.GetTimelineByIndex(i)
            if t:
                existing.add(t.GetName())
    except Exception:
        pass
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def duplicate_timeline() -> str | None:
    """Crea una copia della timeline corrente con nome univoco e ci si sposta sopra."""
    try:
        p = bridge.project()
        tl = bridge.timeline()
        name = _unique_timeline_name(p, f"{tl.GetName()} · SubLab")
        dup = tl.DuplicateTimeline(name)
        if dup is None:
            return None
        p.SetCurrentTimeline(dup)
        return p.GetCurrentTimeline().GetName()
    except Exception:
        traceback.print_exc()
        return None


@app.post("/api/push")
def api_push(payload: dict):
    """Crea i sottotitoli in timeline (modulo push.py). Backup automatico prima di scrivere."""
    try:
        import push
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"push non disponibile: {e}"}
    try:
        dry = bool(payload.get("dry_run", True))
        backup = None if dry else export_backup()
        copied = None
        if not dry and payload.get("on_copy"):
            copied = duplicate_timeline()
            if not copied:
                raise bridge.ResolveError("Impossibile duplicare la timeline: push annullato per sicurezza.")
        res = push.push_cues(STATE["cues"], _fused_style(STATE["style"]),
                             payload.get("track"), dry_run=dry)
        return {"ok": True, "backup": backup, "copied": copied, **res}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- UI

app.mount("/", StaticFiles(directory=os.path.join(HERE, "web"), html=True), name="web")

_load_state()

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("SUBLAB_PORT", "8777"))
    print(f"SubLab -> http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

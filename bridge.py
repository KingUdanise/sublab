"""Livello Resolve del plugin SubLab.

Tutte le chiamate all'API di scripting passano da qui, con le regole imparate sul campo:
  * Input.GetData() -> None ; usare Tool.GetInput()/SetInput()
  * Tool.GetData()  -> puo' bloccare Resolve (render sincrono): vietato
  * AppendToTimeline opera sulla timeline CORRENTE: settarla prima
  * non importare .comp scritte a mano: solo comp esportate da clip funzionanti
"""
from __future__ import annotations

import os
import sys
import time
import traceback

RESOLVE_LIB = r"C:\Program Files\Blackmagic Design\DaVinci Resolve"
MODULES = os.path.join(RESOLVE_LIB, "ResolvePython", "lib", "modules")

os.environ.setdefault("PYTHONPATH", MODULES)
os.environ.setdefault("RESOLVE_SCRIPT_LIB", os.path.join(RESOLVE_LIB, "fusionscript.dll"))
if MODULES not in sys.path:
    sys.path.insert(0, MODULES)

import DaVinciResolveScript as dvr  # noqa: E402


class ResolveError(RuntimeError):
    pass


# --------------------------------------------------------------------------- connessione

_APP = None


def _app():
    """Handle dell'applicazione, cachato: scriptapp() apre una connessione, e
    Resolve ne tiene poche — troppe tornano None senza sollevare."""
    global _APP
    if _APP is None:
        _APP = dvr.scriptapp("Resolve")
    if _APP is None:
        raise ResolveError("Resolve non raggiungibile: avvialo e riprova.")
    return _APP


def _retry(fn, attempts: int = 4, delay: float = 0.35):
    """I proxy remoti di Resolve a volte perdono i metodi ('NoneType' not callable):
    riprova riottenendo l'handle (il cache _APP viene svuotato, cosi' la
    chiamata successiva a _app() apre una connessione fresca)."""
    global _APP
    last = None
    for i in range(attempts):
        try:
            return fn()
        except TypeError as e:
            last = e
            if "NoneType" not in str(e) or i == attempts - 1:
                raise
            _APP = None  # il proxy e' morto: costringi il ri-connetto
            time.sleep(delay * (i + 1))
    raise last  # pragma: no cover


def pm():
    """ProjectManager sempre da un handle fresco (GetProjectManager cade a volte)."""
    return _retry(lambda: _app().GetProjectManager())


def project():
    p = _retry(lambda: _app().GetProjectManager().GetCurrentProject())
    if p is None:
        raise ResolveError("Nessun progetto aperto in Resolve.")
    return p


def timeline():
    t = _retry(lambda: _app().GetProjectManager().GetCurrentProject().GetCurrentTimeline())
    if t is None:
        raise ResolveError("Nessuna timeline aperta.")
    return t


def delete_timeline_by_name(name: str) -> bool:
    """Elimina una timeline per nome.

    Su 21.1 Project.RemoveTimeline / DeleteTimeline NON esistono e
    MediaPool.DeleteTimelines risponde False: la strada provata (cutlab) e'
    che le timeline sono clip del media pool -> DeleteClips sulla clip.
    """
    p = project()
    pool = p.GetMediaPool()

    def walk(folder, depth: int = 0):
        if folder is None or depth > 12:
            return
        yield folder
        for sub in (folder.GetSubFolderList() or []):
            yield from walk(sub, depth + 1)

    ok = False
    for folder in walk(pool.GetRootFolder()):
        hits = [c for c in (folder.GetClipList() or []) if c.GetName() == name]
        if not hits:
            continue
        pool.SetCurrentFolder(folder)
        try:
            ok = bool(pool.DeleteClips(hits)) or ok
        except Exception:
            pass
    return ok


def export_backup() -> str | None:
    """Salva un .drp di sicurezza in sublab/out/backup/ (richiamata dal batch prima di ogni scrittura)."""
    try:
        p = project()
        pmgr = pm()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "backup", f"{p.GetName()}_{stamp}.drp")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path if pmgr.ExportProject(p.GetName(), path, True) else None
    except Exception:
        traceback.print_exc()
        return None


def fps(t=None) -> float:
    t = t or timeline()
    try:
        return float(t.GetSetting("timelineFrameRate"))
    except Exception:
        try:
            return float(project().GetSetting("timelineFrameRate"))
        except Exception:
            return 24.0


def info() -> dict:
    """Stato del progetto/timeline + range selezionato in DaVinci."""
    r = _app()
    p = project()
    t = timeline()
    f = fps(t)
    start, end = int(t.GetStartFrame()), int(t.GetEndFrame())

    mark_in, mark_out = _marks(t)
    sel = t.GetSelectedClips() or []
    sel_info = []
    for it in sel:
        try:
            sel_info.append({
                "name": it.GetName(),
                "start": int(it.GetStart()),
                "end": int(it.GetStart()) + int(it.GetDuration()),
                "track": _track_of(t, it),
            })
        except Exception:
            continue

    return {
        "resolve": r.GetVersionString() if hasattr(r, "GetVersionString") else "",
        "project": p.GetName(),
        "timeline": t.GetName(),
        "fps": f,
        "width": int(t.GetSetting("timelineResolutionWidth") or 1080),
        "height": int(t.GetSetting("timelineResolutionHeight") or 1920),
        "start": start,
        "end": end,
        "mark_in": mark_in,
        "mark_out": mark_out,
        "selection": sel_info,
        "tracks": {
            "video": t.GetTrackCount("video"),
            "audio": t.GetTrackCount("audio"),
        },
    }


def open_project_by_name(name: str, max_depth: int = 4) -> dict:
    """Cerca un progetto per nome in tutta la project library e lo apre."""
    pm = _app().GetProjectManager()
    cur = pm.GetCurrentProject()
    if cur and cur.GetName() == name and cur.GetCurrentTimeline():
        return {"opened": True, "folder": pm.GetCurrentFolder()}

    hit = {"folder": None}

    def walk(depth: int) -> bool:
        for pname in pm.GetProjectListInCurrentFolder() or []:
            if pname == name:
                hit["folder"] = pm.GetCurrentFolder()
                return True
        if depth >= max_depth:
            return False
        for folder in pm.GetFolderListInCurrentFolder() or []:
            if pm.OpenFolder(folder) and walk(depth + 1):
                return True
            pm.GotoParentFolder()
        return False

    pm.GotoRootFolder()
    if not walk(0):
        return {"opened": False, "error": f"progetto {name!r} non trovato"}
    ok = pm.LoadProject(name)
    return {"opened": bool(ok), "folder": hit["folder"]}


def selected_items() -> list:
    """Clip selezionati sulla timeline corrente; se nessuno, quello sotto il
    playhead (GetCurrentVideoItem). Vuoto se non c'e' nulla."""
    items = []
    try:
        items = _retry(lambda: timeline().GetSelectedClips()) or []
    except Exception:
        items = []
    if items:
        return list(items)
    try:
        cur = _retry(lambda: timeline().GetCurrentVideoItem())
    except Exception:
        cur = None
    return [cur] if cur else []


def _marks(t) -> tuple[int, int]:
    """In/Out della timeline in frame (None se non impostati)."""
    try:
        mk = t.GetMarkInOut() or {}
    except Exception:
        return None, None
    vid = mk.get("video") or {}
    ain = (mk.get("audio") or {}).get("in")
    aout = (mk.get("audio") or {}).get("out")
    mi = vid.get("in", ain)
    mo = vid.get("out", aout)
    return (int(mi) if mi is not None else None,
            int(mo) if mo is not None else None)


def _track_of(t, item):
    for kind in ("video", "audio"):
        for i in range(1, t.GetTrackCount(kind) + 1):
            for x in t.GetItemListInTrack(kind, i) or []:
                if x.GetStart() == item.GetStart() and x.GetName() == item.GetName():
                    return i
    return None


def subtitle_range(mode: str = "io") -> tuple[int, int, str]:
    """Restituisce (start, end, descrizione) del range da sottotitolare.

    mode: "io"      -> segni In/Out della timeline (fallback: tutto)
          "selection" -> dalle clip selezionate
          "all"     -> tutto
    """
    t = timeline()
    s0, e0 = int(t.GetStartFrame()), int(t.GetEndFrame())
    if mode == "selection":
        clips = t.GetSelectedClips() or []
        if clips:
            a = min(int(c.GetStart()) for c in clips)
            b = max(int(c.GetStart()) + int(c.GetDuration()) for c in clips)
            return a, b, "clip selezionate"
        return s0, e0, "tutto (nessuna selezione)"
    if mode == "all":
        return s0, e0, "tutto"
    mi, mo = _marks(t)
    if mi is None and mo is None:
        return s0, e0, "tutto (nessun In/Out impostato)"
    a = s0 if mi is None else max(s0, mi)
    b = e0 if mo is None else min(e0, mo)
    return a, b, "In/Out timeline"


# --------------------------------------------------------------------------- clip sub / stile

SUBTITLE_KEY = "SubLab"          # scritte in SetClipColor/name per riconoscere i nostri clip
FONT_SUFFIX = "HLN"              # segnaposto per riconoscere i Text+ AutoSubs


def sub_clips() -> list[dict]:
    """Tutti i clip che possiamo stilizzare: i nostri + i Text+ AutoSubs esistenti."""
    t = timeline()
    out = []
    for tr in range(1, t.GetTrackCount("video") + 1):
        for it in t.GetItemListInTrack("video", tr) or []:
            if not _is_subtitle_item(it):
                continue
            out.append({
                "name": it.GetName(),
                "track": tr,
                "start": int(it.GetStart()),
                "end": int(it.GetStart()) + int(it.GetDuration()),
                "comps": int(it.GetFusionCompCount() or 0),
                "ours": it.GetClipColor() == SUBTITLE_KEY.lower() or _has_our_comp(it),
            })
    return out


def _has_our_comp(item) -> bool:
    try:
        names = item.GetFusionCompNameList() or []
        return any(str(n).startswith("SubLab") for n in names)
    except Exception:
        return False


def _is_subtitle_item(item) -> bool:
    if _has_our_comp(item):
        return True
    if item.GetName() != "Text+":
        return False
    try:
        if int(item.GetFusionCompCount() or 0) < 1:
            return False
        comp = item.GetFusionCompByName((item.GetFusionCompNameList() or ["Comp 1"])[0]) \
            if item.GetFusionCompNameList() else item.GetFusionCompByIndex(1)
        names = {v.GetAttrs().get("TOOLS_Name") for v in (comp.GetToolList() or {}).values()}
        return "AutoSubs" in names or "Template" in names
    except Exception:
        return False


STYLE_INPUTS = ("Font", "Style", "Size", "Center")


def read_style(item) -> dict:
    """Legge lo stile da una clip sub (template TextPlus dentro la comp)."""
    comp, tpl, fol = _tools(item)
    if tpl is None:
        raise ResolveError(f"{item.GetName()}: nessun tool Text+ trovato")

    def g(tool, key, default=None):
        try:
            return tool.GetInput(key)
        except Exception:
            return default

    center = g(tpl, "Center") or {}
    return {
        "font": g(tpl, "Font"),
        "font_style": g(tpl, "Style"),
        "size": g(tpl, "Size"),
        "cx": center.get(2, center.get(1, 0.5)) if isinstance(center, dict) else 0.5,
        "cy": center.get(2, 0.12) if isinstance(center, dict) else 0.12,
        "fill_on": g(tpl, "Enabled1", 1),
        "fill": [g(tpl, "Red1", 1), g(tpl, "Green1", 1), g(tpl, "Blue1", 1)],
        "outline_on": g(tpl, "Enabled2", 0),
        "outline": [g(tpl, "Red2", 0), g(tpl, "Green2", 0), g(tpl, "Blue2", 0)],
        "outline_thickness": g(tpl, "Thickness2", 0.02),
        "shadow_on": g(tpl, "Enabled3", 0),
        "shadow": [g(tpl, "Red3", 0), g(tpl, "Green3", 0), g(tpl, "Blue3", 0)],
        "highlight_on": g(tpl, "HighlightEnabled", 0),
        "highlight": [g(tpl, "HighlightColorRed", 0), g(tpl, "HighlightColorGreen", 0),
                      g(tpl, "HighlightColorBlue", 1)],
    }


def apply_style(style: dict, items=None) -> dict:
    """Scrive lo stile su una o tutte le clip sub. Nessun bottone Update: solo input.

    Scrive sia sul TextPlus (Template) sia sul Follower1, perche' e' il follower a
    disegnare il testo: e' esattamente cio' che fa il bottone "Update Fill Color",
    ma senza cuocere keyframe -> l'effetto e' immediato.
    """
    if items is None:
        items = [it for it in _iter_items() if _is_subtitle_item(it)]
    if not items:
        return {"updated": 0, "skipped": 0, "errors": []}

    errs, updated = [], 0
    for it in items:
        try:
            comp, tpl, fol = _tools(it)
            if tpl is None:
                errs.append(f"{it.GetName()}: no Text+")
                continue
            for tool in (tpl, fol):
                if tool is None:
                    continue
                _write_style(tool, style)
            updated += 1
        except Exception as e:
            errs.append(f"{it.GetName()}: {type(e).__name__} {e}")
    return {"updated": updated, "skipped": len(items) - updated, "errors": errs}


def _write_style(tool, s: dict):
    def si(key, val):
        if val is not None:
            tool.SetInput(key, val)

    si("Font", s.get("font"))
    si("Style", s.get("font_style"))
    if s.get("size") is not None:
        si("Size", float(s["size"]))
    if s.get("cx") is not None and s.get("cy") is not None:
        si("Center", [float(s["cx"]), float(s["cy"])])

    fill = s.get("fill")
    if fill:
        si("Enabled1", 1 if s.get("fill_on", 1) else 0)
        for k, v in zip(("Red1", "Green1", "Blue1"), fill):
            si(k, float(v))

    if s.get("outline_on") is not None:
        si("Enabled2", 1 if s["outline_on"] else 0)
    if s.get("outline"):
        for k, v in zip(("Red2", "Green2", "Blue2"), s["outline"]):
            si(k, float(v))
    if s.get("outline_thickness") is not None:
        si("Thickness2", float(s["outline_thickness"]))

    if s.get("shadow_on") is not None:
        si("Enabled3", 1 if s["shadow_on"] else 0)
    if s.get("shadow"):
        for k, v in zip(("Red3", "Green3", "Blue3"), s["shadow"]):
            si(k, float(v))
    if s.get("shadow_offset"):
        si("Offset3", [float(s["shadow_offset"][0]), float(s["shadow_offset"][1])])


def _iter_items():
    t = timeline()
    for tr in range(1, t.GetTrackCount("video") + 1):
        for it in t.GetItemListInTrack("video", tr) or []:
            yield it


def _tools(item):
    """(comp, TextPlus 'Template', follower1) della clip sub."""
    n = int(item.GetFusionCompCount() or 0)
    if n < 1:
        return None, None, None
    comp = item.GetFusionCompByIndex(1)
    if comp is None:
        return None, None, None
    tools = comp.GetToolList() or {}
    by_name = {v.GetAttrs().get("TOOLS_Name"): v for v in tools.values()}
    tpl = by_name.get("Template") or by_name.get("Text1")
    if tpl is None:
        for v in tools.values():
            if v.GetAttrs().get("TOOLS_RegID") == "TextPlus":
                tpl = v
                break
    fol = by_name.get("Follower1")
    return comp, tpl, fol


def style_of_first_sub() -> dict | None:
    for it in _iter_items():
        if _is_subtitle_item(it):
            try:
                return read_style(it)
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------- audio per ASR

AUDIO_PRESET = "Audio Only"     # preset di Resolve: Wave / Linear PCM (come AutoSubs)
AUDIO_FORMAT = "Wave"           # nomi "leggibili": 'wav'/'lpcm' vengono RIFIUTATI
AUDIO_CODEC = "Linear PCM"


def render_range_audio(start: int, end: int, out_path: str, progress=None) -> str:
    """Render dell'audio del range [start, end) della timeline corrente.

    Usa il preset "Audio Only" di Resolve; se non c'e', imposta Wave + Linear PCM.
    Ripristina sempre i marchi In/Out originali. Restituisce il file prodotto
    (di solito .wav; se Resolve produce altro, es. .mp4, va bene lo stesso).
    """
    p = project()
    t = timeline()
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(out_path))[0]
    for old in os.listdir(out_dir):
        if old.startswith(stem):
            try:
                os.remove(os.path.join(out_dir, old))
            except OSError:
                pass

    marks = t.GetMarkInOut() or {}

    def restore_marks():
        vid = marks.get("video") or {}
        aud = marks.get("audio") or {}
        mi = vid.get("in", aud.get("in"))
        mo = vid.get("out", aud.get("out"))
        try:
            if mi is None and mo is None:
                t.ClearMarkInOut()
            else:
                t.SetMarkInOut(int(mi if mi is not None else start),
                               int(mo if mo is not None else end))
        except Exception:
            pass

    job = None
    try:
        try:
            presets = p.GetRenderPresetList() or []
        except Exception:
            presets = []
        if AUDIO_PRESET in presets:
            p.LoadRenderPreset(AUDIO_PRESET)
            if progress:
                progress(f"render: preset «{AUDIO_PRESET}»")
        else:
            p.SetCurrentRenderFormatAndCodec(AUDIO_FORMAT, AUDIO_CODEC)
            if progress:
                progress(f"render: {AUDIO_FORMAT} / {AUDIO_CODEC}")

        t.SetMarkInOut(start, end)
        p.SetRenderSettings({"SelectAllFrames": False, "TargetDir": out_dir, "CustomName": stem})
        job = p.AddRenderJob()
        if not job:
            raise ResolveError("Resolve non ha creato il job di render audio")
        if progress:
            progress("render audio in corso…")
        p.StartRendering([job])

        status = ""
        deadline = time.time() + 1200
        while time.time() < deadline:
            st = p.GetRenderJobStatus(job) or {}
            status = st.get("JobStatus") or ""
            pct = st.get("CompletionPercentage")
            if status in ("Complete", "Failed", "Cancelled"):
                break
            if progress and pct:
                progress(f"render audio {pct}%")
            time.sleep(1)
        if status != "Complete":
            raise ResolveError(f"render audio non completato (stato: {status or 'timeout'})")
    finally:
        restore_marks()
        if job:
            try:
                p.DeleteRenderJob(job)
            except Exception:
                pass

    found = [f for f in os.listdir(out_dir) if f.startswith(stem)]
    if not found:
        raise ResolveError(f"render audio non ha prodotto file in {out_dir}")
    found.sort(key=lambda f: os.path.getsize(os.path.join(out_dir, f)), reverse=True)
    produced = os.path.join(out_dir, found[0])
    if produced.lower().endswith(".wav") and produced != out_path:
        os.replace(produced, out_path)
        produced = out_path
    return produced


def audio_items_between(start: int, end: int) -> list[dict]:
    """Alternativa senza render: clip audio della timeline nel range, con path sorgente."""
    t = timeline()
    out = []
    for tr in range(1, t.GetTrackCount("audio") + 1):
        for it in t.GetItemListInTrack("audio", tr) or []:
            s = int(it.GetStart())
            e = s + int(it.GetDuration())
            if e <= start or s >= end:
                continue
            mp = it.GetMediaPoolItem()
            if mp is None:
                continue
            out.append({
                "track": tr,
                "name": it.GetName(),
                "start": s,
                "end": e,
                "path": mp.GetClipProperty("File Path"),
                "src_start": int(it.GetSourceStartFrame() or 0),
                "fps": float(mp.GetClipProperty("FPS") or 0) or None,
            })
    return out

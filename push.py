"""Creazione dei sottotitoli in timeline (la parte che scrive in Resolve).

Per ogni cue:
  1. appende una "plate" invisibile sulla traccia SUBS con frame esatti
  2. aggiunge una Fusion comp con Text+ -> MediaOut (comp valida: niente crash)
  3. scrive testo e stile direttamente negli input (niente bottone Update)

La reveal parola-per-parola (StyledTextFollower) arrivera' in v1.1: richiede un
input secondario collegato per nome e va testata a parte.
"""
from __future__ import annotations

import os
import subprocess

import bridge

HERE = os.path.dirname(os.path.abspath(__file__))
PLATE_DIR = os.path.join(HERE, "assets")
PLATE = os.path.join(PLATE_DIR, "plate.mp4")
PLATE_PREFIX = "plate"
PLATE_SECS = 120
TRACK_NAME = "SUBS"
FOLDER_NAME = "SubLab"


# --------------------------------------------------------------------------- plate

def _plate_path(width: int, height: int, fps: int) -> str:
    """Una plate per combinazione risoluzione/fps, cosi' 25/30/60fps non riusano la 24fps."""
    return os.path.join(PLATE_DIR, f"{PLATE_PREFIX}_{int(width)}x{int(height)}_{int(fps)}fps.mp4")


def ensure_plate_media(media_pool, width=1080, height=1920, fps=24, secs=PLATE_SECS):
    """Importa (una volta per risoluzione/fps) il clip nero base dei sottotitoli."""
    fps_i = max(1, int(round(fps)))
    plate_path = _plate_path(width, height, fps_i)
    plate_name = os.path.basename(plate_path)
    folder = _ensure_folder(media_pool)
    for clip in folder.GetClipList() or []:
        if clip.GetName() == plate_name:
            return clip
    if not os.path.exists(plate_path):
        os.makedirs(os.path.dirname(plate_path), exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                        "-i", f"color=c=black:s={int(width)}x{int(height)}:r={fps_i}:d={int(secs)}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "51",
                        "-pix_fmt", "yuv420p", plate_path], check=True, capture_output=True)
    media_pool.SetCurrentFolder(folder)
    ok = media_pool.ImportMedia([plate_path])
    if not ok:
        raise bridge.ResolveError("import della plate nel media pool fallito")
    for clip in media_pool.GetCurrentFolder().GetClipList() or []:
        if clip.GetName() == plate_name:
            return clip
    raise bridge.ResolveError("plate importata ma non trovata nel media pool")


def _ensure_folder(media_pool):
    root = media_pool.GetRootFolder()
    for sub in root.GetSubFolderList() or []:
        if sub.GetName() == FOLDER_NAME:
            return sub
    return media_pool.AddSubFolder(root, FOLDER_NAME) or root


# --------------------------------------------------------------------------- traccia

def find_track(tl) -> int | None:
    """Indice della traccia SUBS se esiste gia' (non modifica nulla)."""
    for i in range(1, tl.GetTrackCount("video") + 1):
        try:
            if (tl.GetTrackName("video", i) or "").strip().upper() == TRACK_NAME:
                return i
        except Exception:
            pass
    return None


def ensure_track(tl) -> int:
    """Ritorna l'indice della traccia SUBS (la crea in cima se non c'e')."""
    found = find_track(tl)
    if found:
        return found
    tl.AddTrack("video")
    idx = tl.GetTrackCount("video")
    try:
        tl.SetTrackName("video", idx, TRACK_NAME)
    except Exception:
        pass
    return idx


def clear_track(tl, idx: int) -> int:
    """Rimuove i clip che abbiamo creato noi sulla traccia SUBS."""
    items = tl.GetItemListInTrack("video", idx) or []
    ours = [it for it in items if _is_ours(it)]
    if not ours:
        return 0
    # Timeline.DeleteClips rimuove i TimelineItem dalla timeline (non MediaPool.DeleteClips)
    tl.DeleteClips(ours, False)
    return len(ours)


def _is_ours(item) -> bool:
    """Riconosce i clip creati da SubLab (sia vecchia plate.mp4 sia plate_WxH_FPSfps.mp4)."""
    try:
        name = (item.GetName() or "").lower()
        if name.startswith(PLATE_PREFIX):
            return True
        mp = item.GetMediaPoolItem()
        return bool(mp) and (mp.GetName() or "").lower().startswith(PLATE_PREFIX)
    except Exception:
        return False


# --------------------------------------------------------------------------- comp

def _build_comp(item, text: str, style: dict):
    comp = item.GetFusionCompByIndex(1) if int(item.GetFusionCompCount() or 0) else None
    if comp is None:
        comp = item.AddFusionComp()
    if comp is None:
        raise bridge.ResolveError(f"{item.GetName()}: impossibile creare la Fusion comp")

    tools = {v.GetAttrs().get("TOOLS_Name"): v for v in (comp.GetToolList() or {}).values()}
    out = tools.get("MediaOut1")
    t1 = tools.get("Text1")
    if out is None:
        out = comp.AddTool("MediaOut", -1)
    if t1 is None:
        t1 = comp.AddTool("TextPlus", -1)
        t1.SetAttrs({"TOOLS_Name": "Text1"})
        try:
            out.FindMainInput(1).ConnectTo(t1.Output)
        except Exception:
            pass
    set_text(t1, text)
    write_style(t1, style)
    return comp, t1


def set_text(tpl, text: str):
    tpl.SetInput("StyledText", text)


def write_style(tool, s: dict):
    """Scrive lo stile sugli input del TextPlus: effetto immediato, nessun Update."""
    def si(k, v):
        if v is not None:
            tool.SetInput(k, v)

    si("Font", s.get("font"))
    si("Style", s.get("font_style"))
    if s.get("size") is not None:
        si("Size", float(s["size"]))
    if s.get("cx") is not None and s.get("cy") is not None:
        si("Center", [float(s["cx"]), float(s["cy"])])
    si("Wrap", 1)
    si("WrapBoxWidth", 0.86)
    si("VerticalJustificationNew", 3)
    si("HorizontalJustificationNew", 3)

    if s.get("fill"):
        si("Enabled1", 1 if s.get("fill_on", 1) else 0)
        for k, v in zip(("Red1", "Green1", "Blue1"), s["fill"]):
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


# --------------------------------------------------------------------------- push

def merge_overlaps(cues: list[dict]) -> list[dict]:
    """Fonde i cue sovrapposti (stesso start / finestra che si incrocia).

    Senza questo, due AppendToTimeline a stesso recordFrame sulla stessa
    traccia si sovrappongono e ne sopravvive solo uno (Pillar 9, frame 771).
    """
    ordered = sorted(cues, key=lambda c: (int(c["start"]), int(c["end"])))
    out: list[dict] = []
    for c in ordered:
        c_copy = dict(c)
        c_copy["start"] = int(c_copy["start"])
        c_copy["end"] = int(c_copy["end"])
        if out and c_copy["start"] < out[-1]["end"]:
            prev = out[-1]
            prev["text"] = (prev["text"] + " " + c_copy["text"]).strip()
            prev["end"] = max(prev["end"], c_copy["end"])
            if prev.get("words") or c_copy.get("words"):
                prev["words"] = list(prev.get("words") or []) + list(c_copy.get("words") or [])
        else:
            out.append(c_copy)
    return out


def push_cues(cues: list[dict], style: dict, track: int | None = None,
              dry_run: bool = True, replace: bool = True) -> dict:
    tl = bridge.timeline()
    p = bridge.project()
    f = bridge.fps(tl)
    cues = merge_overlaps(cues)
    if not cues:
        raise bridge.ResolveError("nessun sottotitolo da inserire")

    if dry_run:                       # nessuna modifica alla timeline in dry run
        idx = track or find_track(tl) or (tl.GetTrackCount("video") + 1)
        return {"dry_run": True, "track": idx, "create_track": find_track(tl) is None,
                "cues": len(cues),
                "frames": sum(int(c["end"]) - int(c["start"]) for c in cues),
                "first": cues[0]["start"], "last": cues[-1]["end"]}

    idx = track or ensure_track(tl)
    plan = {
        "track": idx,
        "cues": len(cues),
        "frames": sum(int(c["end"]) - int(c["start"]) for c in cues),
        "first": cues[0]["start"],
        "last": cues[-1]["end"],
    }

    removed = clear_track(tl, idx) if replace else 0
    media_pool = p.GetMediaPool()
    fps_i = max(1, int(round(f)))
    max_plate_frames = PLATE_SECS * fps_i
    plate = ensure_plate_media(media_pool, width=int(tl.GetSetting("timelineResolutionWidth") or 1080),
                               height=int(tl.GetSetting("timelineResolutionHeight") or 1920),
                               fps=fps_i, secs=PLATE_SECS)
    p.SetCurrentTimeline(tl)

    made, errors = 0, []
    created_pairs: list[tuple[object | None, dict]] = []
    for c in cues:
        start, end = int(c["start"]), int(c["end"])
        dur = max(1, min(end - start, max_plate_frames))
        ok = media_pool.AppendToTimeline([{
            "mediaPoolItem": plate,
            "startFrame": 0,
            "endFrame": dur,              # endFrame e' esclusivo -> dur frame esatti
            "trackIndex": idx,
            "recordFrame": start,
        }])
        if not ok:
            errors.append(f"cue @{start}: append fallito")
            continue
        made += 1
        item = ok[0] if isinstance(ok, (list, tuple)) and ok else None
        created_pairs.append((item, c))

    # Mappa esatta clip -> cue (mai zip posizionale: un append fallito non deve sfasare i testi)
    items = [it for it in (tl.GetItemListInTrack("video", idx) or []) if _is_ours(it)]
    by_start = {int(it.GetStart()): it for it in items}
    styled = 0
    for item, c in created_pairs:
        target = item if (item is not None and hasattr(item, "AddFusionComp")) else by_start.get(int(c["start"]))
        if target is None:
            errors.append(f"cue @{c['start']}: clip creato non ritrovato in timeline")
            continue
        try:
            _build_comp(target, c["text"], style)
            styled += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"cue @{c['start']}: {type(e).__name__} {e}")

    try:
        bridge.pm().SaveProject()
    except Exception:
        pass

    return {"dry_run": False, **plan, "removed": removed, "created": made,
            "appended": len(items), "styled": styled, "errors": errors}

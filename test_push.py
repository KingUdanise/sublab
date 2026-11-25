"""Test end-to-end del push su una COPIA della timeline (poi la cancella)."""
import sys
import traceback

sys.path.insert(0, r"C:\aivinci\sublab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bridge  # noqa: E402
import push  # noqa: E402

DUP_NAME = "Timeline 1 SUBLAB TEST"

STYLE = {
    "font": "Helvetica Now Display", "font_style": "Bold", "size": 0.07,
    "cx": 0.5, "cy": 0.12,
    "fill_on": 1, "fill": [1.0, 0.666666666666667, 0.0],
    "outline_on": 1, "outline": [0.0, 0.0, 0.0], "outline_thickness": 0.02,
    "shadow_on": 0, "shadow": [0.0, 0.0, 0.0], "shadow_offset": [0.004, -0.004],
}

CUES = [
    {"start": 300, "end": 330, "text": "Prima riga di prova SubLab", "words": []},
    {"start": 340, "end": 372, "text": "secondo sottotitolo più lungo per il wrap", "words": []},
    {"start": 380, "end": 400, "text": "terzo", "words": []},
]

p = bridge.project()
tl0 = bridge.timeline()
print("timeline di partenza:", tl0.GetName())

dup = None
try:
    dup = tl0.DuplicateTimeline(DUP_NAME)
    print("DuplicateTimeline ->", bool(dup), "| nome:", dup.GetName() if dup else None)
    print("SetCurrentTimeline ->", p.SetCurrentTimeline(dup))
    dup = p.GetCurrentTimeline()
    print("timeline corrente:", dup.GetName(), "| tracce:", dup.GetTrackCount("video"))

    print("\n--- DRY RUN ---")
    print(push.push_cues(CUES, STYLE, None, dry_run=True))

    print("\n--- PUSH REALE ---")
    res = push.push_cues(CUES, STYLE, None, dry_run=False)
    print(res)

    idx = res["track"]
    items = dup.GetItemListInTrack("video", idx) or []
    print(f"\nclip su V{idx} ({dup.GetTrackName('video', idx)}):")
    for it in items:
        comp = it.GetFusionCompByIndex(1) if int(it.GetFusionCompCount() or 0) else None
        info = None
        if comp:
            tools = {v.GetAttrs().get("TOOLS_Name"): v for v in (comp.GetToolList() or {}).values()}
            t1 = tools.get("Text1")
            info = {k: t1.GetInput(k) for k in ("StyledText", "Font", "Size", "Red1", "Green1", "Blue1",
                                                "Enabled2", "Thickness2")} if t1 else None
        print(f"   {int(it.GetStart()):>5}..{int(it.GetStart())+int(it.GetDuration()):<5} "
              f"dur={int(it.GetDuration()):<3} comp={bool(comp)} {info}")
except Exception:
    traceback.print_exc()
finally:
    try:
        p.SetCurrentTimeline(tl0)
        if dup is not None:
            print("\nDeleteTimelines([dup]) ->", p.GetMediaPool().DeleteTimelines([dup]))
        print("timeline corrente:", p.GetCurrentTimeline().GetName())
        print("SaveProject ->", p.GetProjectManager().SaveProject())
    except Exception as e:
        print("cleanup ERR", e)

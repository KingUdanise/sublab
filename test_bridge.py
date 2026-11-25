"""Test in sola lettura del livello bridge (nessuna modifica alla timeline)."""
import json
import sys

sys.path.insert(0, r"C:\aivinci\sublab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bridge  # noqa: E402

print("=== INFO ===")
print(json.dumps(bridge.info(), indent=2, ensure_ascii=False))

print("\n=== RANGE ===")
for mode in ("io", "selection", "all"):
    try:
        s, e, why = bridge.subtitle_range(mode)
        print(f"  {mode:10} -> {s}..{e}  ({why})  {e-s} frame")
    except Exception as ex:
        print(f"  {mode:10} ERR {ex}")

print("\n=== CLIP SUB ===")
subs = bridge.sub_clips()
print(f"  {len(subs)} clip sub")
for s in subs[:20]:
    print(f"   V{s['track']}. {s['start']:>5}..{s['end']:<5} ours={s['ours']} comps={s['comps']} {s['name']}")

print("\n=== STILE del primo sub ===")
st = bridge.style_of_first_sub()
print(json.dumps(st, indent=2, ensure_ascii=False) if st else "  nessuno stile leggibile")

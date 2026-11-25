"""Test ASR standalone su un wav gia' presente (nessun Resolve coinvolto)."""
import json
import sys
import time

sys.path.insert(0, r"C:\aivinci\sublab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asr  # noqa: E402

WAV = r"C:\aivinci\asr\speech_16k.wav"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "small"

t0 = time.time()
res = asr.transcribe(WAV, model_size=MODEL, language="it", progress=lambda m: print(" ", m, flush=True))
dt = time.time() - t0
print(f"\nmodello={MODEL} device={res['device']} durata_audio={res['duration']:.1f}s in {dt:.1f}s "
      f"(x{res['duration']/max(dt,0.01):.1f} realtime)")

cues = asr.build_cues(res["words"])
print("\nstatistiche cue:", asr.stats(cues))
print("\nprimi 8 cue:")
for c in cues[:8]:
    print(f"  {c['start']:6.2f} -> {c['end']:6.2f}  {c['text']}")

frames = asr.cue_frames(cues, 24.0, offset=2.0)
print("\nprimi 3 cue in frame (offset 2s @24fps):")
for c in frames[:3]:
    print("  ", json.dumps(c, ensure_ascii=False))

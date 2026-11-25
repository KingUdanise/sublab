"""Verifica il costruttore di cue, incluso il merge dei sottotitoli troppo corti."""
import sys

sys.path.insert(0, r"C:\aivinci\sublab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asr  # noqa: E402

words = [
    {"w": "Un", "s": 0.0, "e": 0.3},
    {"w": "occhiale", "s": 0.4, "e": 0.9},
    {"w": "può", "s": 1.0, "e": 1.1},
    {"w": "essere", "s": 1.1, "e": 1.4},
    {"w": "tecnicamente", "s": 1.4, "e": 2.2},
    {"w": "corretto,", "s": 2.4, "e": 2.9},
    {"w": "ma", "s": 2.9, "e": 3.0},
    {"w": "se", "s": 3.0, "e": 3.1},
    {"w": "non", "s": 3.1, "e": 3.2},
    {"w": "rappresenta", "s": 3.2, "e": 3.9},
    {"w": "chi", "s": 3.9, "e": 4.0},
    {"w": "l'indossa,", "s": 4.0, "e": 4.6},
    {"w": "manca", "s": 4.7, "e": 5.1},
    {"w": "una", "s": 5.1, "e": 5.2},
    {"w": "parte", "s": 5.2, "e": 5.5},
    {"w": "importante", "s": 5.5, "e": 6.2},
    {"w": "del", "s": 6.2, "e": 6.3},
    {"w": "risultato.", "s": 6.3, "e": 6.9},
]

cues = asr.build_cues(words)
print("cue prodotti:")
for c in cues:
    n = len(c["words"])
    print(f"  [{c['start']:5.2f}-{c['end']:5.2f}] {c['text']:45} ({n} parole)")

print("\nstatistiche:", asr.stats(cues))
assert all(len(c["text"]) >= 5 for c in cues), "ci sono ancora cue microscopici"
assert all(len(c["text"]) <= 38 for c in cues), "qualche cue supera max_chars"
print("\nOK: nessun cue microscopico, nessuno oltre 38 caratteri")

frames = asr.cue_frames(cues, 24.0, offset=6695 / 24.0)
print("\nprimi 2 cue in frame:", [(c["start"], c["end"], c["text"]) for c in frames[:2]])

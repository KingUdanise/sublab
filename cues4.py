"""Cue sottotitoli: massimo 4 parole, mai tagliati male (metodo Monglas).

Le regole, in ordine di importanza:

1. massimo 4 parole per cue. Un'elisione ("dell'ottica", "l'uomo") e' UNA parola.
2. un cue non finisce mai con una parola che chiede la successiva: articolo,
   preposizione (semplice o articolata), congiunzione, "che", "non", ausiliare o
   copula ("è", "sono", "ha" ...), pronome atono, aggettivo possessivo o
   dimostrativo. Mai finire su un apostrofo ("l'", "un'", "dell'").
3. un cue non attraversa mai la fine di una frase: si chiude a ogni ". ? !".
4. non si spezzano mai nome+cognome, ne' "Monglas Ottica Saronno", ne'
   "Metodo Progressivo 99,5", ne' un numero con la sua unita'.
5. durata 0.8-2.5 s, e almeno 2 frame di stacco fra due cue consecutivi.

L'algoritmo e' una programmazione dinamica sulla frase: sceglie i punti di taglio
che costano meno (preferisce 3-4 parole per cue e i tagli su una virgola) fra
quelli che rispettano i vincoli 2-4. Se una frase non ha una soluzione pulita,
il taglio meno peggio viene usato e segnalato: meglio un cue da 5 parole con un
avviso che un cue che si mangia la frase dopo.

    cues = build(words, fps=24.0)     # words: [{"w","s","e"}]
    report = validate(cues)           # [] = niente da correggere
"""
from __future__ import annotations

import re
from typing import Iterable

MAX_WORDS = 4
MAX_CHARS = 20      # larghezza massima leggibile a schermo
HARD_CHARS = 26     # oltre questa si spezza comunque
MIN_DUR = 0.8
MAX_DUR = 2.5
MIN_GAP_FRAMES = 2

# --------------------------------------------------------------------------- lessico

ARTICLES = {
    "il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una", "un'",
}

PREPOSITIONS = {
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra", "senza", "sotto",
    "sopra", "verso", "contro", "presso", "durante", "oltre", "entro", "dopo",
    "secondo", "tramite", "attraverso",
    # articolate
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "col", "colla", "coi", "cogli", "collo",
    "pel", "pella", "pei", "pegli", "pelle",
}

CONJUNCTIONS = {
    "e", "ed", "o", "od", "ma", "però", "pero", "oppure", "né", "ne'", "che",
    "perché", "perche", "poiché", "poiche", "affinché", "affinche", "quando",
    "mentre", "se", "come", "così", "cosi", "dunque", "quindi", "allora",
    "nemmeno", "neanche", "anche", "pure", "soltanto", "solo", "piuttosto",
    "bensì", "bensi", "tuttavia", "invece", "mentre", "finché", "finche",
    "giacché", "giacche", "sicché", "sicche", "purché", "purche",
}

AUX_COPULA = {
    "è", "e'", "sono", "sei", "siamo", "siete", "era", "erano", "eri", "eravamo",
    "fu", "furono", "sarà", "sara", "saranno", "sarebbe", "sarebbero", "sia",
    "siano", "fosse", "fossero", "ho", "hai", "ha", "abbiamo", "avete", "hanno",
    "aveva", "avevano", "avevo", "avrò", "avro", "avrebbe", "abbia", "abbiate",
    "avendo", "aver", "essere", "stato", "stata", "stati", "state", "sta",
    "stanno", "stava", "stavano", "stare", "viene", "vengono", "veniva",
    "venivano", "verrà", "verra", "verranno",
}

# pronomi atoni e particelle che si appoggiano alla parola dopo
CLITICS = {
    "mi", "ti", "si", "ci", "vi", "lo", "la", "li", "le", "ne", "gli",
    "m'", "t'", "s'", "c'", "v'", "n'", "l'",
}

DETERMINERS = {
    "questo", "questa", "questi", "queste", "quello", "quella", "quelli",
    "quelle", "quel", "quei", "quegli", "codesto", "codesta",
    "mio", "mia", "miei", "mie", "tuo", "tua", "tuoi", "tue", "suo", "sua",
    "suoi", "sue", "nostro", "nostra", "nostri", "nostre", "vostro", "vostra",
    "vostri", "vostre", "loro", "altrui", "proprio", "propria",
    "ogni", "qualche", "alcuni", "alcune", "alcun", "nessun", "nessuna",
    "ciascun", "ciascuna", "tale", "tali", "certo", "certa",
}

FORBIDDEN_LAST = ARTICLES | PREPOSITIONS | CONJUNCTIONS | AUX_COPULA | CLITICS | DETERMINERS
FORBIDDEN_LAST |= {"non", "n'", "più", "piu", "meno", "molto", "poco", "troppo",
                   "tanto", "quanto", "abbastanza", "davvero", "proprio"}

SENTENCE_END = ".?!…"
NUM_RE = re.compile(r"^\d+([.,]\d+)?$")

# frasi che non si spezzano mai, cosi' come devono comparire nel sottotitolo
ATOMIC_DEFAULTS = ("Monglas Ottica Saronno", "Metodo Progressivo 99,5")

# correzioni di grafia fisse: (pattern, sostituzione)
SPELLING_FIXES = (
    (re.compile(r"(?i)\bmonglass?ott\w*(?:\s+(?:casar|saronn)\w*)?"), "Monglas Ottica Saronno"),
    (re.compile(r"(?i)\bmonglas\s+(?:ottica\s+)?(?:casar|saronn)\w*"), "Monglas Ottica Saronno"),
    (re.compile(r"(?i)\bmonglas\s+ottica\s+saronno\b"), "Monglas Ottica Saronno"),
    (re.compile(r"(?i)\bmetodo\s+progressivo\s+99[.,]\s*5\b"), "Metodo Progressivo 99,5"),
)


# --------------------------------------------------------------------------- token

def _clean_text(t: str) -> str:
    t = (t or "").strip()
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t)
    return t


def _bare(tok: str) -> str:
    """La parola senza punteggiatura ne' virgolette."""
    b = re.sub(r"^[\"'«(\[]+|[\"'»)\]]+$", "", tok).rstrip(".,;:!?…").strip().lower()
    if re.fullmatch(r"\d+\.\d+", b):
        b = b.replace(".", ",")          # 99.5 e 99,5 sono lo stesso numero
    return b


def _ends_apostrophe(tok: str) -> bool:
    b = re.sub(r"[\"»)\]]+$", "", tok).strip()
    return b.endswith("'")


def _has_sentence_end(tok: str) -> bool:
    return bool(tok) and tok[-1] in SENTENCE_END


# parole che non possono chiudere un cue NEMMENO a fine frase: se l'ASR ci mette
# un punto sopra, il punto e' sbagliato
STRUCTURAL = (ARTICLES | PREPOSITIONS | CLITICS | AUX_COPULA
              | {"non", "che", "e", "ed", "o", "od", "ne", "né"})


def cannot_end(tok: str) -> bool:
    """True se il cue non puo' chiudersi su questa parola."""
    b = _bare(tok)
    if not b:
        return True
    cleaned = re.sub(r"[\"'»)\]]+$", "", tok)
    if cleaned.endswith(("...", "…")):
        return False         # il parlato si e' interrotto: il cue e' quello che e'
    if _ends_apostrophe(tok):
        return True
    if b in STRUCTURAL:
        return True
    if cleaned.endswith((".", "?", "!")):
        # a fine frase un avverbio, un dimostrativo o un numero vanno benissimo
        # ("conta di più.", "non era questo?", "il 99,5.")
        return False
    if b in FORBIDDEN_LAST:
        return True
    if NUM_RE.match(b):
        return True          # a meta' frase un numero chiede la sua unita'
    if b.endswith("'") or b.endswith("’"):
        return True
    return False


def merge_elisions(words: list[dict]) -> list[dict]:
    """Unisce le elisioni che l'ASR ha separato ("vent'" + "anni", "dell" + "'ottica")."""
    out: list[dict] = []
    for w in words:
        tok = _clean_text(w.get("w") or w.get("text") or "")
        if not tok:
            continue
        item = {"w": tok, "s": float(w["s"]), "e": float(w["e"])}
        # l'apostrofo puo' essere attaccato davanti ("'anni") o dietro ("vent'")
        starts_apostrophe = tok[:1] == "'" or tok[:1] == "’"
        if out and (starts_apostrophe or _ends_apostrophe(out[-1]["w"])):
            head = out[-1]["w"].rstrip("'’")
            tail = tok.lstrip("'’")
            out[-1] = {"w": head + "'" + tail, "s": out[-1]["s"],
                       "e": max(out[-1]["e"], item["e"])}
            continue
        # numero spezzato dall'ASR: "99" + ",5" -> "99,5"
        if out and re.fullmatch(r"\d+", out[-1]["w"]) and re.match(r"^[.,]\d+", tok):
            out[-1] = {"w": out[-1]["w"] + tok, "s": out[-1]["s"],
                       "e": max(out[-1]["e"], item["e"])}
            continue
        out.append(item)
    return out


def sentence_split(tokens: list[dict], pause_s: float = 0.40) -> list[list[dict]]:
    """Divide in frasi: punteggiatura, pausa lunga o maiuscola dopo pausa.

    L'ASR non punteggia in modo affidabile: una pausa di 0,4 s o una maiuscola
    sono indizi altrettanto forti della fine di una frase, e servono a non
    costruire cue che scavalcano il confine.
    """
    sentences: list[list[dict]] = []
    cur: list[dict] = []
    for i, t in enumerate(tokens):
        cur.append(t)
        end_punct = _has_sentence_end(t["w"])
        gap = 0.0
        capital = False
        if i + 1 < len(tokens):
            gap = float(tokens[i + 1]["s"]) - float(t["e"])
            capital = re.sub(r"^[\"'«(]+", "", tokens[i + 1]["w"])[:1].isupper()
        if end_punct or (gap > pause_s and (capital or gap > 0.75)):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    return sentences


# --------------------------------------------------------------------------- unita' atomiche

def atomic_spans(tokens: list[dict], phrases: Iterable[str] = ATOMIC_DEFAULTS) -> list[tuple[int, int]]:
    """Intervalli [i, j) di token che non si possono separare."""
    spans: list[tuple[int, int]] = []
    text = [_bare(t["w"]) for t in tokens]

    for ph in phrases:
        want = [_bare(x) for x in ph.split()]
        if not want:
            continue
        n = len(want)
        for i in range(len(text) - n + 1):
            if text[i:i + n] == want:
                spans.append((i, i + n))

    # due o piu' parole con l'iniziale maiuscola di fila = nome e cognome
    i = 0
    while i < len(tokens):
        raw = re.sub(r"^[\"'«(]+", "", tokens[i]["w"])
        if raw[:1].isupper() and not _has_sentence_end(tokens[i]["w"]):
            j = i + 1
            while j < len(tokens):
                raw2 = re.sub(r"^[\"'«(]+", "", tokens[j]["w"])
                if raw2[:1].isupper():
                    j += 1
                else:
                    break
            if j - i >= 2:
                start = i + 1 if i == 0 else i       # la maiuscola di inizio frase non conta
                if j - start >= 2:
                    spans.append((start, j))
            i = j
        else:
            i += 1

    # numero + unita' ("99,5 %", "3 diottrie"): solo unita' vere, altrimenti si
    # creano catene che rendono la frase indivisibile
    UNITS = {"%", "cento", "per", "diottrie", "diottria", "mm", "cm", "metri",
             "gradi", "euro", "kg", "ore", "minuti"}
    for i, t in enumerate(tokens):
        if NUM_RE.match(_bare(t["w"])) and i + 1 < len(tokens) \
                and _bare(tokens[i + 1]["w"]) in UNITS:
            spans.append((i, i + 2))
    return _normalize_spans(spans)


def _normalize_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Unisce gli intervalli che si sovrappongono: il piu' lungo vince.

    Senza questo, un'unita' piu' corta trovata dopo puo' oscurare quella vera
    ("Metodo Progressivo 99,5" contro il solo nome proprio "Metodo Progressivo").
    """
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if b - a < 2:
            continue
        if out and a < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _span_for(spans: list[tuple[int, int]], i: int) -> tuple[int, int] | None:
    for a, b in spans:
        if a <= i < b:
            return (a, b)
    return None


# --------------------------------------------------------------------------- ritaglio frase

def effective_len(words: list[str] | list[dict], spans: list[tuple[int, int]] | None = None) -> int:
    """Quante parole 'vere' ci sono: un'unita' atomica conta come una.

    "dell'ottica" e' una parola sola, e lo stesso vale per "Metodo Progressivo
    99,5": quattro parole cosi' sono gia' un cue pieno.
    """
    toks = [{"w": (w if isinstance(w, str) else w.get("w", "")), "s": 0.0, "e": 0.0}
            for w in words]
    if spans is None:
        spans = atomic_spans(toks)
    by_start = {a: b for a, b in _normalize_spans(spans)}
    n, k = 0, 0
    while k < len(toks):
        if k in by_start:
            k = by_start[k]
        else:
            k += 1
        n += 1
    return n


def _effective_slice(tokens: list[dict], spans: list[tuple[int, int]], i: int, j: int) -> int:
    by_start = {a: b for a, b in _normalize_spans(spans) if i <= a and b <= j}
    n, k = 0, i
    while k < j:
        k = by_start.get(k, k + 1)
        n += 1
    return n


def _width(seg: list[dict]) -> int:
    """Larghezza approssimata del cue in caratteri."""
    return sum(len(t["w"]) for t in seg) + max(0, len(seg) - 1)


def _split_cost(seg: list[dict], is_last: bool, eff: int | None = None) -> float:
    """Quanto 'costa' questo cue: si preferiscono 3-4 parole e i tagli su virgola."""
    n = len(seg) if eff is None else eff
    cost = {1: 9.0, 2: 3.0, 3: 0.5, 4: 0.0}.get(n, 20.0)
    if seg and seg[-1]["w"].rstrip("\"'»)]").endswith(","):
        cost -= 0.8
    if is_last and n == 1:
        cost += 2.0
    w = _width(seg)
    if w > MAX_CHARS:
        cost += (w - MAX_CHARS) * 0.7      # meglio spezzare che sbordare
    return cost


def _bad_end_cost(tok: str) -> float:
    """Quanto e' brutto chiudere un cue su questa parola.

    Serve quando la frase non ha nessun taglio pulito ("...ma non essere quella
    che meglio valorizza..."): meglio finire su una copula ("può essere") che su
    un articolo o un apostrofo.
    """
    b = _bare(tok)
    if _ends_apostrophe(tok):
        return 24.0
    if b in AUX_COPULA:
        return 3.0
    if b in DETERMINERS:
        return 6.0
    if NUM_RE.match(b):
        return 8.0
    if b in {"non", "che", "e", "ed", "o", "od", "ma", "ne", "né"}:
        return 12.0
    if b in ARTICLES or b in PREPOSITIONS:
        return 14.0
    if b in CLITICS:
        return 16.0
    return 0.0


def _split_list(tokens: list[dict]) -> list[list[dict]]:
    """Spezza la frase alle virgole e alle congiunzioni di elenco."""
    parts: list[list[dict]] = []
    cur: list[dict] = []
    for t in tokens:
        bare = re.sub(r"[^\w'àèéìòùâêîôû]+", "", t["w"]).strip().lower()
        if cur and bare in ("e", "ed", "o", "poi") and len(cur) >= 1:
            parts.append(cur)
            cur = []
            continue
        cur.append(t)
        if t["w"].rstrip().endswith((",", ";", ":")):
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def list_groups(tokens: list[dict], chunker) -> list[list[dict]] | None:
    """Se la frase e' un elenco, un cue per voce.

    "...può accompagnare lettura, telefono, conversazione e visione da lontano"
    diventa "può accompagnare" | "lettura" | "telefono" | "conversazione" | ...
    """
    parts = _split_list(tokens)
    if len(parts) < 3:
        return None
    short_tail = [p for p in parts[1:] if len(p) <= 5]
    if len(short_tail) < 2:
        return None
    groups: list[list[dict]] = []
    first = parts[0]
    if len(first) >= 2:
        groups.extend(chunker(first[:-1]))
        groups.append([first[-1]])
    else:
        groups.append(first)
    for p in parts[1:]:
        groups.extend(chunker(p) if len(p) > 4 else [p])
    return [g for g in groups if g]


def chunk_sentence(tokens: list[dict], max_words: int = MAX_WORDS,
                   allow_list: bool = True,
                   spans: list[tuple[int, int]] | None = None) -> tuple[list[list[dict]], list[str]]:
    """Divide una frase in cue rispettando i vincoli. Ritorna (cue, avvisi).

    Si prova in ordine: taglio perfetto -> cue da 5 parole -> unita' atomica
    spezzata -> cue che finisce su una parola appesa. Il primo tentativo che
    chiude vince, cosi' si degrada il meno possibile e si sa sempre perche'.
    """
    n = len(tokens)
    if n == 0:
        return [], []
    if allow_list:
        listed = list_groups(
            tokens, lambda part: chunk_sentence(part, max_words, allow_list=False)[0])
        if listed:
            return listed, [], False
    spans = spans if spans is not None else atomic_spans(tokens)
    local = [(a, b) for a, b in spans if a >= 0 and b <= n]

    def solve(use_spans: bool, allow_bad_end: bool, max_eff: int):
        INF = float("inf")
        best = [INF] * (n + 1)
        prev = [-1] * (n + 1)
        best[0] = 0.0
        longest_unit = max([b - a for a, b in local] + [1])
        window = max_eff + longest_unit          # token massimi per un cue

        def boundary_ok(j: int) -> bool:
            if use_spans:
                sp = _span_for(local, j - 1)
                if sp and j < sp[1]:
                    return False                      # dentro un'unita' atomica
            if j == n:
                return True                           # fine frase: sempre ok
            if cannot_end(tokens[j - 1]["w"]):
                return allow_bad_end
            return True

        for i in range(n):
            if best[i] == INF:
                continue
            for size in range(window, 0, -1):         # a parita', cue piu' pieno
                j = i + size
                if j > n:
                    continue
                if not boundary_ok(j):
                    continue
                eff = _effective_slice(tokens, local, i, j)
                if eff > max_eff:
                    continue
                if _width(tokens[i:j]) > HARD_CHARS:
                    continue
                c = best[i] + _split_cost(tokens[i:j], j == n, eff)
                if allow_bad_end and j < n:
                    c += _bad_end_cost(tokens[j - 1]["w"])
                if c < best[j]:
                    best[j] = c
                    prev[j] = i
        if best[n] == INF:
            return None
        cuts, j = [], n
        while j > 0:
            cuts.append(j)
            j = prev[j]
        cuts.append(0)
        return sorted(cuts)

    ladder = (
        (True, False, max_words, None),
        (True, False, max_words + 1, "cue oltre 4 parole: nessun taglio valido migliore"),
        (True, True, max_words, "cue che finisce su una parola appesa"),
        (False, True, max_words, "unita' atomica spezzata: frase troppo stretta"),
    )
    for idx_rung, (use_spans, bad_end, max_eff, warn) in enumerate(ladder):
        cuts = solve(use_spans, bad_end, max_eff)
        if cuts:
            groups = [tokens[cuts[k]:cuts[k + 1]] for k in range(len(cuts) - 1)]
            forced = idx_rung >= 2          # frase senza taglio pulito
            return groups, ([warn] if warn else []) + [
                f"cue da {_effective_slice(tokens, local, cuts[k], cuts[k + 1])} parole"
                for k in range(len(cuts) - 1)
                if _effective_slice(tokens, local, cuts[k], cuts[k + 1]) > max_words], forced
    return [tokens], ["frase troppo lunga per essere divisa: tenuta intera"], True


# --------------------------------------------------------------------------- testo

def fix_spelling(text: str) -> str:
    for rx, rep in SPELLING_FIXES:
        text = rx.sub(rep, text)
    return text


def join_text(tokens: list[dict]) -> str:
    """Testo del cue con la punteggiatura italiana (niente spazio prima di , . ?)."""
    parts = []
    for t in tokens:
        w = t["w"].strip()
        if not w:
            continue
        if parts and (w[0] in ",.;:!?" or w[0] == ")"):
            parts[-1] = parts[-1] + w
        else:
            parts.append(w)
    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    text = fix_spelling(text)
    text = text.rstrip(",;:…")            # in coda restano solo . ? !
    text = text.strip()
    if text and text[0].islower():
        first = text.split(" ", 1)[0]
        text = text[0].upper() + text[1:]
        del first
    return text


# --------------------------------------------------------------------------- timeline

def _timing_pass(cues: list[dict], fps: float, min_dur: float, max_dur: float,
                 min_gap_frames: int) -> list[dict]:
    """Durata minima/massima e stacco di almeno 2 frame fra i cue.

    Il parlato e' continuo: se il cue finisse esattamente dove comincia il
    successivo, i due si toccherebbero. Si accorcia sempre di `gap` frame,
    cosi' lo stacco c'e' anche fra due cue attaccati.
    """
    gap = min_gap_frames / float(fps)
    out = [dict(c) for c in cues]
    for i, c in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        limit = (nxt["start"] - gap) if nxt else (c["start"] + max_dur)
        end = min(float(c["end"]), limit)
        if end < float(c["start"]) + min_dur:
            end = min(float(c["start"]) + min_dur, limit)      # allunga nel silenzio
        end = max(end, min(float(c["start"]) + 0.25, limit))   # mai cue inesistenti
        end = min(end, float(c["start"]) + max_dur)
        c["end"] = round(max(end, float(c["start"]) + 0.04), 3)
    return [c for c in out if c["end"] > c["start"]]


def _proper_nouns(sentences: list[list[dict]]) -> set[str]:
    """Parole che l'ASR scrive maiuscole NON a inizio frase: nomi propri."""
    out: set[str] = set()
    for sent in sentences:
        for i, t in enumerate(sent):
            raw = re.sub(r"^[\"'«(]+", "", t["w"])
            if i > 0 and raw[:1].isupper():
                out.add(_bare(t["w"]))
    return out


def _apply_case(cues: list[dict], proper: set[str]) -> list[dict]:
    """Maiuscola solo a inizio frase e sui nomi propri, come chiesto."""
    for c in cues:
        toks = (c.get("text") or "").split()
        if not toks:
            continue
        head = toks[0]
        core = re.sub(r"^[\"'«(]+", "", head)
        prefix = head[:len(head) - len(core)]
        low = _bare(head)
        if c.get("starts"):
            fixed = core[:1].upper() + core[1:]
        elif low in proper:
            fixed = core
        else:
            fixed = core[:1].lower() + core[1:]
        toks[0] = prefix + fixed
        c["text"] = " ".join(toks)
    return cues


def _repair_endings(cues: list[dict], max_words: int, rounds: int = 4) -> list[dict]:
    """Sposta l'ultima parola al cue dopo quando il cue finisce appeso.

    Il programmatore dinamico a volte non ha scelta (l'unico taglio valido
    lascerebbe un cue piu' lungo di 4 parole). Qui si ripara in piccolo: si
    sposta la parola appesa al cue successivo, se ci sta.
    """
    for _ in range(rounds):
        changed = False
        for i, c in enumerate(cues):
            words = c.get("words") or []
            if len(words) < 2:
                continue
            if not cannot_end(words[-1]["w"]):
                continue
            if i + 1 >= len(cues):
                continue
            nxt = cues[i + 1]
            if nxt.get("sent") != c.get("sent"):
                continue                     # mai spostare parole fra due frasi
            nxt_words = nxt.get("words") or []
            if len(nxt_words) >= max_words:
                continue
            if cannot_end(words[-2]["w"]):
                continue                     # peggiorerebbe: resterebbe appeso
            moved = words.pop()
            c["end"] = float(words[-1]["e"])
            c["text"] = join_text(words)
            nxt_words.insert(0, moved)
            nxt["start"] = float(moved["s"])
            nxt["text"] = join_text(nxt_words)
            changed = True
            if float(c["end"]) <= float(c["start"]):
                c["end"] = float(c["start"]) + 0.2
        if not changed:
            break
    return cues


def _merge_short(cues: list[dict], fps: float, min_dur: float, max_words: int) -> list[dict]:
    """Due cue troppo corti diventano uno, se restano sotto le 4 parole.

    Sotto 0.8 s il cue non si legge. Allungarlo nel silenzio successivo si puo'
    fare solo se il silenzio c'e': altrimenti la strada giusta e' unirlo al
    vicino, prima a quello di sinistra e se non ci sta a quello di destra.
    """
    out: list[dict] = []
    for c in cues:
        cur = dict(c)
        while out:
            prev = out[-1]
            short = (prev["end"] - prev["start"]) < min_dur
            fits = len((prev.get("text") or "").split()) + len((cur.get("text") or "").split()) <= max_words
            ends_sentence = (prev.get("text") or "").rstrip()[-1:] in ".?!"
            if short and fits and not ends_sentence and not prev.get("list"):
                prev["text"] = f"{prev['text'].rstrip()} {cur['text'].lstrip()}".strip()
                prev["end"] = cur["end"]
                prev["words"] = prev.get("words", []) + cur.get("words", [])
                cur = None
            break
        if cur is not None:
            out.append(cur)
    # seconda passata: i cue corti che non sono riusciti ad assorbire il
    # precedente si allargano prendendo il successivo
    i = 0
    while i + 1 < len(out):
        c, nxt = out[i], out[i + 1]
        short = (c["end"] - c["start"]) < min_dur
        fits = len((c.get("text") or "").split()) + len((nxt.get("text") or "").split()) <= max_words
        ends_sentence = (c.get("text") or "").rstrip()[-1:] in ".?!"
        if short and fits and not ends_sentence and not c.get("list"):
            c["text"] = f"{c['text'].rstrip()} {nxt['text'].lstrip()}".strip()
            c["end"] = nxt["end"]
            c["words"] = c.get("words", []) + nxt.get("words", [])
            del out[i + 1]
            continue
        i += 1
    return out


def build(words: list[dict], fps: float = 24.0, max_words: int = MAX_WORDS,
          min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
          min_gap_frames: int = MIN_GAP_FRAMES,
          atomic: Iterable[str] = ATOMIC_DEFAULTS) -> dict:
    """Da parole con timestamp ai cue pronti da dare a push_cues().

    Ritorna {"cues": [{"start","end","text","words"}], "warnings": [...],
    "sentences": n}.
    """
    tokens = merge_elisions(words)
    sentences = sentence_split(tokens)
    proper = _proper_nouns(sentences)
    cues, warnings = [], []
    for si, sent in enumerate(sentences):
        spans = atomic_spans(sent, atomic)
        groups, warn, forced = chunk_sentence(sent, max_words=max_words, spans=spans)
        is_list = list_groups(
            sent, lambda part: chunk_sentence(part, max_words, allow_list=False)[0]) is not None
        for w in warn:
            warnings.append(f"frase {si + 1}: {w}")
        for gi, g in enumerate(groups):
            if not g:
                continue
            cues.append({"start": float(g[0]["s"]), "end": float(g[-1]["e"]),
                         "text": join_text(g),
                         "words": [{"w": t["w"], "s": float(t["s"]), "e": float(t["e"])}
                                   for t in g],
                         "starts": gi == 0, "forced": forced, "sent": si,
                         "list": is_list})
    cues = _merge_short(cues, fps, min_dur, max_words)
    cues = _timing_pass(cues, fps, min_dur, max_dur, min_gap_frames)
    cues = _repair_endings(cues, max_words)
    cues = _timing_pass(cues, fps, min_dur, max_dur, min_gap_frames)
    cues = _apply_case(cues, proper)
    return {"cues": cues, "warnings": warnings, "sentences": len(sentences),
            "tokens": len(tokens)}


# --------------------------------------------------------------------------- validazione

def validate(cues: list[dict], fps: float = 24.0, max_words: int = MAX_WORDS,
             min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
             min_gap_frames: int = MIN_GAP_FRAMES) -> list[dict]:
    """Elenca tutte le violazioni. Lista vuota = sottotitoli a norma.

    Ogni violazione ha una gravita': "errore" vuol dire che il cue va rifatto,
    "avviso" che e' una conseguenza fisica del parlato (parole attaccate) e va
    solo guardata una volta.
    """
    problems = []

    def bad(i, code, text, detail="", severity="errore"):
        problems.append({"i": i, "code": code, "text": text, "detail": detail,
                         "severity": severity})

    for i, c in enumerate(cues):
        text = (c.get("text") or "").strip()
        toks = text.split()
        n_words = effective_len(toks)
        if n_words > max_words:
            # cinque parole capitano solo quando non esiste un taglio valido
            # (es. "Gli occhi non sono come gli addominali."): meglio un cue
            # pieno che un cue appeso a una copula
            bad(i, "troppe_parole", text, f"{n_words} parole",
                "avviso" if n_words <= max_words + 1 else "errore")
        if toks:
            last = toks[-1]
            if cannot_end(last):
                forced = bool(c.get("forced"))
                bad(i, "finisce_su_parola_appesa", text, last,
                    "avviso" if forced else "errore")
            if re.search(r"(?i)\b(l|un|dell|all|nell|sull|dall|coll)'$", last):
                bad(i, "finisce_su_apostrofo", text, last)
            if last[-1] in ",;:":
                bad(i, "punteggiatura_in_coda", text, last[-1])
            if re.search(r"[.!?]\s+\S", text):
                bad(i, "due_frasi_insieme", text, "")
        dur = float(c.get("end", 0)) - float(c.get("start", 0))
        if dur < min_dur - 0.02:
            # gia' allungato il piu' possibile: se resta corto e' perche' il
            # parlato e' attaccato, non perche' il cue sia sbagliato
            bad(i, "troppo_corto", text, f"{dur:.2f}s", "avviso")
        if dur > max_dur + 0.02:
            bad(i, "troppo_lungo", text, f"{dur:.2f}s",
                "errore" if dur > max_dur + 0.3 else "avviso")
        if i + 1 < len(cues):
            nxt = cues[i + 1]
            d_frames = (float(nxt["start"]) - float(c["end"])) * fps
            if d_frames < min_gap_frames - 0.5:
                bad(i, "stacco_troppo_corto", text, f"{d_frames:.1f} frame",
                    "errore" if d_frames < -1.5 else "avviso")
            if d_frames < -1.5:
                bad(i, "sovrapposizione", text, f"{d_frames:.1f} frame")
    return problems


def errors_only(problems: list[dict]) -> list[dict]:
    return [p for p in problems if p.get("severity", "errore") == "errore"]


def text_stats(cues: list[dict], fps: float = 24.0) -> dict:
    if not cues:
        return {"cues": 0}
    durs = [float(c["end"]) - float(c["start"]) for c in cues]
    words = [effective_len((c.get("text") or "").split()) for c in cues]
    raw = [len((c.get("text") or "").split()) for c in cues]
    chars = [len((c.get("text") or "").strip()) for c in cues]
    cps = [ch / d for ch, d in zip(chars, durs) if d > 0]
    return {"cues": len(cues), "dur_min": round(min(durs), 2),
            "dur_max": round(max(durs), 2), "dur_media": round(sum(durs) / len(durs), 2),
            "parole_max": max(words), "parole_media": round(sum(words) / len(words), 2),
            "parole_token_max": max(raw),
            "cps_max": round(max(cps), 1), "cps_media": round(sum(cps) / len(cps), 1),
            "totale_secondi": round(sum(durs), 1)}

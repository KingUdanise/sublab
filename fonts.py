"""Elenco dei font installati su Windows, con il file da servire alla preview web."""
from __future__ import annotations

import os
import re
try:
    import winreg
except ImportError:  # pragma: no cover - ambienti non-Windows
    winreg = None

FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
]
REG_KEYS = (
    [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]
    if winreg is not None
    else []
)
FONT_EXT = (".ttf", ".otf", ".ttc", ".woff", ".woff2")
STYLE_WORDS = ("Thin", "Light", "Regular", "Book", "Medium", "Semibold", "SemiBold", "Bold",
               "Black", "Heavy", "Italic", "Oblique", "Condensed", "Narrow", "Extended",
               "Now", "Display", "Text", "Roman")


def _find_file(name: str) -> str | None:
    for d in FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


WEIGHT_WORDS = ("ExtraBold", "SemiBold", "Semibold", "Bold", "Black", "Heavy", "Medium", "Book",
                "Regular", "Roman", "Light", "Thin", "Hairline", "Ultra",
                "Italic", "Oblique", "Condensed", "Narrow", "Expanded", "Extended")


def norm(s: str) -> str:
    """chiave di confronto: 'Helvetica Now Display' == 'HelveticaNowDisplay-Bold'."""
    return re.sub(r"[\s_\-\.]", "", (s or "")).lower()


def _declared(path: str) -> tuple[str, str] | None:
    """Nome famiglia/stile dichiarato nel file del font (quello che usa Fusion)."""
    try:
        from PIL import ImageFont

        fam, style = ImageFont.truetype(path, 12).getname()
        fam = (fam or "").strip()
        style = (style or "Regular").strip()
        if not fam:
            return None
        if style.lower() in ("regular", "book", "roman"):
            style = "Regular"
        return fam, style
    except Exception:
        return None


def _ensure_cache() -> list[dict]:
    global _cache
    if _cache is None:
        _cache = installed()
    return _cache


def resolve_family(name: str | None) -> str | None:
    """'HelveticaNowDisplay' -> 'Helvetica Now Display' (nome che Fusion riconosce)."""
    if not name:
        return name
    key = norm(name)
    for f in _ensure_cache():
        if f["key"] == key:
            return f["family"]
    return name


def resolve_style(family: str | None, style: str | None) -> str | None:
    """Riporta lo stile a uno dei nomi dichiarati dalla famiglia (es. 'bold' -> 'Bold')."""
    if not family:
        return style
    entry = next((f for f in _ensure_cache() if norm(f["family"]) == norm(family)), None)
    if entry is None:
        return style
    styles = entry["styles"]
    if style in styles:
        return style
    if style:
        want = norm(style)
        for s in styles:
            if norm(s) == want:
                return s
        # varianti: 'Bold' vs 'Bold Italic'
        for s in styles:
            if norm(s).startswith(want):
                return s
    return "Regular" if "Regular" in styles else styles[0]


def _split_family_style(label: str) -> tuple[str, str]:
    """'HelveticaNowDisplay-Bold (OpenType)' -> ('HelveticaNowDisplay', 'Bold')."""
    s = re.sub(r"\s*\((TrueType|OpenType|All res)\)\s*$", "", label, flags=re.I).strip()
    if "-" in s:
        base, _, tail = s.partition("-")
        style = tail.strip() or "Regular"
        style = re.sub(r"(?i)italic$", " Italic", style).strip()
        return base.strip(), style
    for w in WEIGHT_WORDS:
        m = re.match(rf"^(.*\S)\s+{w}(\s*(Italic|Oblique))?$", s, flags=re.I)
        if m:
            style = w + (m.group(2) or "")
            return m.group(1).strip(), style.strip()
    return s, "Regular"


def installed() -> list[dict]:
    """[{family, file, styles: [..]}] deduplicato per famiglia."""
    fams: dict[str, dict] = {}
    for root, path in REG_KEYS:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    label, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not str(value).lower().endswith(FONT_EXT):
                    continue
                fpath = _find_file(os.path.basename(str(value)))
                if not fpath:
                    continue
                # nome DICHIARATO dentro il font: è quello che Fusion si aspetta.
                # (L'etichetta del registro è tipo "HelveticaNowDisplay-Bold" e Fusion
                #  risponde "Font Not Found: HelveticaNowDisplay Bold".)
                fam, style = _declared(fpath) or _split_family_style(label)
                if not fam:
                    continue
                entry = fams.setdefault(fam, {"family": fam, "files": {}, "styles": set(),
                                              "key": norm(fam)})
                entry["files"].setdefault(style, fpath)
                entry["styles"].add(style)
    out = []
    for fam, e in fams.items():
        styles = sorted(e["styles"], key=lambda s: ("Regular" not in s, s))
        out.append({
            "family": fam,
            "key": e["key"],
            "styles": styles,
            "files": {k: os.path.basename(v) for k, v in e["files"].items()},
            "_paths": e["files"],
        })
    out.sort(key=lambda x: x["family"].lower())
    return out


def _style_from_label(label: str, family: str) -> str:
    rest = re.sub(re.escape(family), "", label, flags=re.I)
    rest = re.sub(r"\s*\((TrueType|OpenType|All res)\)\s*$", "", rest, flags=re.I).strip(" -,")
    if not rest:
        return "Regular"
    if rest.lower() in ("regular", "book", "roman"):
        return "Regular"
    return rest


_cache: list[dict] | None = None


def catalog() -> list[dict]:
    items = _ensure_cache()
    return [{"family": f["family"], "key": f.get("key", norm(f["family"])),
             "styles": f["styles"], "files": f["files"]} for f in items]


def font_file(filename: str) -> str | None:
    """Percorso del file font servibile (solo dalla cartella Fonts)."""
    for d in FONT_DIRS:
        if not d:
            continue
        p = os.path.join(d, os.path.basename(filename))
        if os.path.isfile(p):
            return p
    return None

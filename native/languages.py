"""Supported-language registry, alias normalization and pair validation (FR-02, FR-03).

SUPPORTED_LANGUAGES is the allow-list exposed to users. The OpenAI Realtime
model handles many more languages, but spec §11 says to expose only pairs the
team has validated — prune or extend this list after your fidelity testing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# canonical English name → aliases (lower-case, unaccented forms are added automatically)
SUPPORTED_LANGUAGES: dict[str, list[str]] = {
    "English": ["american english", "british english", "inglés", "ingles"],
    "Spanish": ["español", "espanol", "castilian", "castellano", "mexican spanish"],
    "French": ["français", "francais"],
    "German": ["deutsch"],
    "Italian": ["italiano"],
    "Portuguese": ["português", "portugues", "brazilian portuguese", "brazilian"],
    "Mandarin Chinese": ["mandarin", "putonghua", "standard chinese", "chinese mandarin",
                         "mandarin chinese", "chinese (mandarin)"],
    "Cantonese": ["cantonese chinese", "yue", "chinese (cantonese)"],
    "Japanese": ["nihongo"],
    "Korean": ["hangul", "hanguk-eo"],
    "Arabic": ["modern standard arabic", "al-arabiyya"],
    "Hindi": [],
    "Russian": ["russkiy"],
    "Vietnamese": ["tiếng việt", "tieng viet"],
    "Tagalog": ["filipino"],
    "Polish": ["polski"],
    "Ukrainian": [],
    "Persian": ["farsi"],
}

# Names that map to more than one supported language → ask which one.
AMBIGUOUS_ALIASES: dict[str, list[str]] = {
    "chinese": ["Mandarin Chinese", "Cantonese"],
}

_FILLER = re.compile(r"\b(the|language|languages|lang|please)\b")


def _clean(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[.,!?;:\"']", " ", s)
    s = _FILLER.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _build_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for canon, aliases in SUPPORTED_LANGUAGES.items():
        for a in [canon, *aliases]:
            idx[_clean(a)] = canon
    return idx


_INDEX = _build_index()


@dataclass(frozen=True)
class Normalized:
    canonical: str | None
    candidates: tuple[str, ...] = ()   # filled when ambiguous

    @property
    def ambiguous(self) -> bool:
        return self.canonical is None and len(self.candidates) > 1


def normalize_language(name: str) -> Normalized:
    key = _clean(name)
    if not key:
        return Normalized(None)
    if key in AMBIGUOUS_ALIASES:
        return Normalized(None, tuple(AMBIGUOUS_ALIASES[key]))
    if key in _INDEX:
        return Normalized(_INDEX[key])
    return Normalized(None)


@dataclass(frozen=True)
class PairResult:
    ok: bool
    language_1: str | None
    language_2: str | None
    message: str
    reason: str = ""  # missing | ambiguous | unsupported | duplicate


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def validate_pair(language_1: str, language_2: str) -> PairResult:
    """Normalize two spoken language names and check the pair is usable.

    Never raises; returns a PairResult whose `message` is safe to speak to
    the user in the command-interface language.
    """
    raw = [language_1 or "", language_2 or ""]
    if not raw[0].strip() or not raw[1].strip():
        return PairResult(False, None, None,
                          "I need two languages. Please say both, for example Spanish and French.", "missing")
    norms = [normalize_language(r) for r in raw]
    for r, n in zip(raw, norms):
        if n.ambiguous:
            return PairResult(False, None, None, f"By {r.strip()}, did you mean {_join(list(n.candidates))}?",
                              "ambiguous")
    unsupported = [r.strip() for r, n in zip(raw, norms) if n.canonical is None]
    if unsupported:
        listed = " and ".join(unsupported)
        verb = "isn't" if len(unsupported) == 1 else "aren't"
        return PairResult(False, None, None,
                          f"Sorry, {listed} {verb} supported in this prototype yet.", "unsupported")
    a, b = norms[0].canonical, norms[1].canonical
    if a == b:
        return PairResult(False, None, None, f"Both languages were {a}. Please name two different languages.",
                          "duplicate")
    return PairResult(True, a, b, f"Okay, I'll translate between {a} and {b}.")


def supported_names() -> list[str]:
    return list(SUPPORTED_LANGUAGES.keys())

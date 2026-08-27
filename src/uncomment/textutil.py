"""Small text helpers: identifier splitting, light stemming, word overlap."""

from __future__ import annotations

import re

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WORD_RE = re.compile(r"[A-Za-z]+")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

STOPWORDS = frozenset(
    "the a an of it its this that these those we you i is are be been being was were "
    "will shall should would could must can may might now then just simply also very "
    "to and or with by on in at as from into our their his her".split()
)


def stem(word: str) -> str:
    """Very light stemmer: enough to match 'loops'~'loop', 'incrementing'~'increment'."""
    w = word.lower()
    for suffix in ("ing", "ies", "ied", "es", "ed", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: len(w) - len(suffix)]
            if suffix == "ies" or suffix == "ied":
                w += "y"
            # undouble 'running'->'runn'->'run', but keep call/pass/buzz
            if suffix in ("ing", "ed") and len(w) >= 4 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]
            break
    # normalize the mute 'e' so 'frobnicates'->'frobnicat' matches 'frobnicate'
    if w.endswith("e") and len(w) >= 4:
        w = w[:-1]
    return w


def split_identifier(ident: str) -> list[str]:
    """user_name -> [user, name]; getUserName -> [get, user, name]."""
    parts: list[str] = []
    for chunk in ident.split("_"):
        parts.extend(m.group(0) for m in _CAMEL_RE.finditer(chunk))
    return [p.lower() for p in parts if p and not p.isdigit()]


# operators verbalized: "// increment the counter" restates "counter++" even
# though the operator contributes no identifier. Multi-char operators are
# checked before their single-char prefixes.
_OPERATOR_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("++", ("increment",)),
    ("--", ("decrement",)),
    ("+=", ("add", "increase")),
    ("-=", ("subtract", "decrease")),
    ("*=", ("multiply", "scale")),
    ("/=", ("divide",)),
    ("==", ("equal", "check", "compare")),
    ("!=", ("not", "equal", "differ")),
    ("&&", ("and",)),
    ("||", ("or",)),
    ("=", ("set", "assign", "store")),
    ("+", ("add", "plus", "sum")),
    ("-", ("minus", "subtract")),
    ("*", ("multiply", "times")),
    ("/", ("divide",)),
    ("%", ("modulo", "remainder")),
    ("<", ("less", "below", "compare")),
    (">", ("greater", "above", "compare")),
    ("!", ("not", "negate")),
    ("(", ("call", "invoke")),
]


def code_words(code: str) -> set[str]:
    """Stemmed word set from a line of code: whole and split identifiers,
    plus verbalized operators."""
    words: set[str] = set()
    for ident in _IDENT_RE.findall(code):
        words.add(stem(ident.lower()))  # whole identifier, so 'GetName' in prose matches
        for part in split_identifier(ident):
            words.add(stem(part))
    rest = code
    for op, verbal in _OPERATOR_WORDS:
        if op in rest:
            rest = rest.replace(op, " ")
            for w in verbal:
                words.add(stem(w))
    return words


def comment_words(text: str) -> list[str]:
    """Stemmed, stopword-filtered words from comment prose."""
    words = []
    for m in _WORD_RE.finditer(text):
        w = m.group(0).lower()
        if w not in STOPWORDS and len(w) > 1:
            words.append(stem(w))
    return words


def overlap_ratio(comment_text: str, code: str) -> float:
    """Fraction of comment words that also appear in the code."""
    cwords = comment_words(comment_text)
    if not cwords:
        return 0.0
    kwords = code_words(code)
    hits = sum(1 for w in cwords if w in kwords)
    return hits / len(cwords)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")


def sentences(text: str) -> list[str]:
    """Naive sentence splitter; good enough for comment prose."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(flat) if s.strip()]


def first_line(text: str, limit: int = 72) -> str:
    line = text.splitlines()[0] if text else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"

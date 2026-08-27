"""ASD-STE100-inspired wording rules for comment prose.

Simplified Technical English, applied loosely: short sentences, active voice,
approved simple words. All default to INFO — they guide rewording, not gating.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..config import Config
from ..model import Finding, Severity, SourceFile
from ..textutil import first_line, sentences
from . import is_license_header, rule, wording_text
from .core import _looks_like_code

_URL_RE = re.compile(r"https?://\S+")


def _prose(comment) -> str:
    """Comment content with code-looking and URL lines removed.
    Blank lines stay: they are paragraph boundaries."""
    lines = [ln for ln in comment.content.splitlines() if not _looks_like_code(ln)]
    return _URL_RE.sub("", "\n".join(lines))


def _skip(comment) -> bool:
    return is_license_header(comment) or comment.word_count < 3


@rule(
    "STE01",
    "long-sentence",
    Severity.INFO,
    "Sentence longer than the STE limit (20 words).",
)
def long_sentence(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if _skip(c):
            continue
        paragraphs = re.split(r"\n\s*\n", _prose(c))
        worst = max(
            (s for para in paragraphs for s in sentences(para)),
            key=lambda s: len(s.split()),
            default="",
        )
        n = len(worst.split())
        if n > cfg.ste_max_sentence_words:
            yield Finding(
                rule="STE01",
                severity=Severity.INFO,
                path=c.path,
                line=c.start_line,
                end_line=c.end_line,
                message=f"sentence has {n} words (STE limit: {cfg.ste_max_sentence_words})",
                action="Split it into short sentences. One instruction or fact per sentence.",
                excerpt=first_line(worst),
            )


_PASSIVE_RE = re.compile(
    r"\b(is|are|was|were|be|been|being|gets?|got)\s+(\w+ed|built|chosen|done|driven|found|given|held|hidden|kept|"
    r"known|left|lost|made|meant|put|read|run|said|seen|sent|set|shown|sold|spent|taken|thrown|told|understood|used|written)\b",
    re.IGNORECASE,
)


@rule(
    "STE02",
    "passive-voice",
    Severity.INFO,
    "Passive voice; STE requires active voice.",
)
def passive_voice(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if _skip(c):
            continue
        m = _PASSIVE_RE.search(wording_text(_prose(c), cfg))
        if m:
            yield Finding(
                rule="STE02",
                severity=Severity.INFO,
                path=c.path,
                line=c.start_line,
                end_line=c.end_line,
                message=f"passive voice ('{m.group(0)}')",
                action="Rewrite in active voice: name the actor (the function, the caller, the OS) and use a simple verb.",
                excerpt=first_line(c.content),
            )


# maps a phrase to its approved replacement; phrases match before single words
PHRASES: dict[str, str] = {
    "in order to": "to",
    "prior to": "before",
    "subsequent to": "after",
    "in the event that": "if",
    "with the exception of": "except",
    "at this point in time": "now",
    "in conjunction with": "with",
    "make use of": "use",
    "a number of": "some",
    "due to the fact that": "because",
    "note that": "(delete it)",
    "it should be noted that": "(delete it)",
    "needless to say": "(delete it)",
}

WORDS: dict[str, str] = {
    "utilize": "use", "utilise": "use", "leverage": "use", "employ": "use",
    "facilitate": "help", "commence": "start", "initiate": "start",
    "terminate": "stop", "conclude": "end", "demonstrate": "show",
    "indicate": "show", "attempt": "try", "endeavor": "try",
    "additional": "more", "additionally": "also", "furthermore": "also",
    "moreover": "also", "consequently": "so", "subsequently": "then",
    "approximately": "about", "sufficient": "enough", "numerous": "many",
    "obtain": "get", "acquire": "get", "purchase": "buy",
    "construct": "build", "fabricate": "make", "modify": "change",
    "alter": "change", "transmit": "send", "whilst": "while",
    "amongst": "among", "notwithstanding": "despite", "aforementioned": "this",
    "thus": "so", "hence": "so", "therefore": "so", "nevertheless": "but",
    "assist": "help", "permit": "let", "adequate": "enough",
    "basically": "(delete it)", "essentially": "(delete it)",
    "obviously": "(delete it)", "clearly": "(delete it)",
    "simply": "(delete it)", "actually": "(delete it)",
}

_WORD_SPLIT_RE = re.compile(r"[a-z]+", re.IGNORECASE)


@rule(
    "STE03",
    "unapproved-word",
    Severity.INFO,
    "Word or phrase outside the simple STE-style vocabulary.",
)
def unapproved_word(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if _skip(c):
            continue
        prose = wording_text(_prose(c), cfg).lower()
        hits: list[tuple[str, str]] = []
        for phrase, repl in PHRASES.items():
            if phrase in prose:
                hits.append((phrase, repl))
        for w in _WORD_SPLIT_RE.findall(prose):
            if w in WORDS:
                hits.append((w, WORDS[w]))
        if hits:
            shown = ", ".join(f"'{a}' → {b}" for a, b in dict(hits).items())
            yield Finding(
                rule="STE03",
                severity=Severity.INFO,
                path=c.path,
                line=c.start_line,
                end_line=c.end_line,
                message=f"non-simple wording: {shown}",
                action="Use the simple form. STE style: one common word per meaning.",
                excerpt=first_line(c.content),
            )


@rule(
    "STE04",
    "long-paragraph",
    Severity.INFO,
    "Paragraph longer than the STE limit (6 sentences).",
)
def long_paragraph(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if _skip(c):
            continue
        for para in re.split(r"\n\s*\n", _prose(c)):
            n = len(sentences(para))
            if n > cfg.ste_max_paragraph_sentences:
                yield Finding(
                    rule="STE04",
                    severity=Severity.INFO,
                    path=c.path,
                    line=c.start_line,
                    end_line=c.end_line,
                    message=f"paragraph has {n} sentences (STE limit: {cfg.ste_max_paragraph_sentences})",
                    action="Split the paragraph, or move this prose to documentation.",
                    excerpt=first_line(c.content),
                )
                break

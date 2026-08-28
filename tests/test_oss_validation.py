"""Round 4: false-positive classes from the OSS validation run
(javapoet, jsoup, serilog, okio, Alamofire)."""

from __future__ import annotations

from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.languages import C, JAVA, SWIFT, spec_for_path
from uncomment.rules import run_rules


def _fired(path: str, src: str, spec, cfg: Config | None = None):
    return {f.rule for f in run_rules(extract_source(path, src, spec), cfg or Config())}


# ---- UC007: enum-case docs are required by ecosystem lint ----

def test_documented_enum_case_is_not_redundant():
    src = ("enum TrustError {\n"
           "    /// Certificate pinning failed.\n"
           "    case certificatePinningFailed\n"
           "}\n")
    assert "UC007" not in _fired("t.swift", src, SWIFT)


def test_redundant_method_doc_still_fires():
    src = '/// Writes the byte string.\nfunc writeByteString() -> Int { return 1 }\n'
    assert "UC007" in _fired("t.swift", src, SWIFT)


# ---- UC002: bare "we" needs a process verb ----

def test_state_prose_we_is_spared():
    for text in (
        "We allocated a tail segment, but didn't end up needing it. Recycle!",
        "We have a task, if it's completed the delegate already ran.",
        "We were exhausted before the scan completed.",
        "we made it, so it should",
    ):
        src = f"int f(void) {{\n// {text}\nreturn 1;\n}}\n"
        assert "UC002" not in _fired("t.c", src, C), text


def test_process_we_is_still_narration():
    src = "int f(void) {\n// we check the input and normalize it\nreturn 1;\n}\n"
    assert "UC002" in _fired("t.c", src, C)


# ---- UC005: keyword-led English is prose ----

def test_keyword_prose_is_not_dead_code():
    for text in (
        "if already a valid escape, pass; otherwise, escape",
        "if doc != null it was fully parsed during charset detection; so just re-read",
        "finally: prepare the return struct",
        "for cases where the caller wants a re-read, keep the buffer",
    ):
        src = f"// {text}\nint x;\n"
        assert "UC005" not in _fired("t.java", src, JAVA), text


def test_keyword_code_still_fires():
    py = spec_for_path("x.py")
    cases = [
        ("t.c", "void f(void) {\n// if (fast_path) { return cached; }\nuse(0);\n}\n", C),
        ("t.py", "def f():\n    y = 2\n    # for item in items:\n    return y\n", py),
    ]
    for path, src, spec in cases:
        assert "UC005" in _fired(path, src, spec), src


# ---- UC003: runtime removal prose vs the version-history form ----

def test_runtime_removal_prose_is_clean():
    src = "// if the node was removed from the stack, use the element above it\nint x;\n"
    assert "UC003" not in _fired("t.java", src, JAVA)


def test_version_history_removal_still_errors():
    src = "// this shim was removed in 2.0 of the wire protocol\nint x;\n"
    assert "UC003" in _fired("t.java", src, JAVA)


# ---- UC009: URLs and the 80-char default ----

def test_citation_url_does_not_spend_the_budget():
    src = ("int m = 1; // [GET](https://www.w3.org/Protocols/rfc2616/rfc2616-sec9.html#sec9.3)"
           " - generally idempotent\n")
    assert "UC009" not in _fired("t.java", src, JAVA)


def test_house_style_trailing_under_80_passes():
    src = "int n = 0; // reinitializes the accumulated checksum whenever the stream restarts\n"
    assert len(src) > 62  # over the old 60-char default
    assert "UC009" not in _fired("t.java", src, JAVA)


def test_projects_can_tighten_back_to_60():
    src = "int n = 0; // reinitializes the accumulated checksum whenever the stream restarts\n"
    assert "UC009" in _fired("t.java", src, JAVA, Config(max_trailing_chars=60))

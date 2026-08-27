"""Doc-comment placement awareness: Doxygen/JSDoc/rustdoc structure and
interface files are where documentation belongs — never suggest moving it."""

from __future__ import annotations

from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.languages import C, RUST, TS, is_interface_file
from uncomment.rules import run_rules

DOXYGEN_DOC = (
    "/**\n"
    " * @brief Copies a bounded string.\n"
    " *\n"
    " * @param dst destination buffer\n"
    " * @param src source string\n"
    " * @param n   capacity of dst in bytes\n"
    " * @return number of bytes copied\n"
    " *\n"
    " * @note The destination always ends with a terminator.\n"
    " * @warning dst and src must not overlap.\n"
    " * @sa safe_move\n"
    " * @deprecated use safe_copy2 instead\n"
    " */\n"
)


def _fired(path, src, spec):
    return {f.rule for f in run_rules(extract_source(path, src, spec), Config())}


def test_is_interface_file():
    assert is_interface_file("include/api.h")
    assert is_interface_file("src/types.d.ts")
    assert not is_interface_file("src/impl.c")
    assert not is_interface_file("src/app.ts")


def test_doxygen_doc_in_header_not_flagged():
    src = DOXYGEN_DOC + "size_t safe_copy(char *dst, const char *src, size_t n);\n"
    assert _fired("api.h", src, C) == set()


def test_structured_doxygen_doc_in_impl_file_not_flagged():
    src = DOXYGEN_DOC + "size_t safe_copy(char *dst, const char *src, size_t n) { return 0; }\n"
    assert "UC008" not in _fired("impl.c", src, C)


def test_huge_tagged_doc_still_hints_migration():
    body = "".join(f" * Guide paragraph line {i} about the architecture.\n" for i in range(24))
    src = "/**\n * @brief Frobnicates.\n" + body + " */\nvoid f(void);\n"
    assert "UC008" in _fired("impl.c", src, C)


def test_rustdoc_conventional_sections_not_flagged():
    src = (
        "/// Parses a config file.\n"
        "///\n"
        "/// # Examples\n"
        "///\n"
        "/// Call it with a path to a readable file.\n"
        "///\n"
        "/// # Errors\n"
        "///\n"
        "/// Returns an error when the file does not exist.\n"
        "///\n"
        "/// # Panics\n"
        "///\n"
        "/// Never panics.\n"
        "pub fn parse(path: &str) {}\n"
    )
    assert "UC008" not in _fired("lib.rs", src, RUST)


def test_dts_declaration_docs_not_flagged():
    body = "".join(f" * Detail line {i} of the public contract.\n" for i in range(14))
    src = "/**\n" + body + " */\nexport declare function connect(url: string): void;\n"
    assert "UC008" not in _fired("client.d.ts", src, TS)

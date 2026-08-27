"""Per-language knowledge: file extensions, grammar names, comment node types,
doc-comment prefixes, and function-like node types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LangSpec:
    name: str                       # our canonical name
    grammar: str                    # tree-sitter-language-pack grammar name
    doc_line_prefixes: tuple[str, ...] = ()    # e.g. ///, //!
    doc_block_prefixes: tuple[str, ...] = ()   # e.g. /**, /*!
    function_nodes: frozenset[str] = frozenset()
    # node types whose preceding own-line comment is a doc comment by convention
    doc_by_convention_nodes: frozenset[str] = frozenset()
    keywords: frozenset[str] = frozenset()


_C_LIKE_KEYWORDS = frozenset(
    "if else for while do switch case break continue return goto sizeof "
    "struct union enum typedef static const void int char float double long "
    "short unsigned signed".split()
)

C = LangSpec(
    name="c",
    grammar="c",
    doc_line_prefixes=("///", "//!"),
    doc_block_prefixes=("/**", "/*!"),
    function_nodes=frozenset({"function_definition"}),
    keywords=_C_LIKE_KEYWORDS,
)

CPP = LangSpec(
    name="cpp",
    grammar="cpp",
    doc_line_prefixes=("///", "//!"),
    doc_block_prefixes=("/**", "/*!"),
    function_nodes=frozenset({"function_definition", "lambda_expression"}),
    keywords=_C_LIKE_KEYWORDS
    | frozenset("class namespace template public private protected virtual override new delete this auto".split()),
)

JS = LangSpec(
    name="javascript",
    grammar="javascript",
    doc_block_prefixes=("/**",),
    function_nodes=frozenset(
        {"function_declaration", "function_expression", "arrow_function", "method_definition", "generator_function_declaration"}
    ),
    keywords=frozenset(
        "if else for while do switch case break continue return function const let var new delete typeof "
        "class extends import export default async await try catch throw this".split()
    ),
)

TS = LangSpec(
    name="typescript",
    grammar="typescript",
    doc_block_prefixes=("/**",),
    function_nodes=JS.function_nodes,
    keywords=JS.keywords | frozenset("interface type enum implements readonly public private protected".split()),
)

TSX = LangSpec(name="tsx", grammar="tsx", doc_block_prefixes=("/**",), function_nodes=JS.function_nodes, keywords=TS.keywords)

RUST = LangSpec(
    name="rust",
    grammar="rust",
    doc_line_prefixes=("///", "//!"),
    doc_block_prefixes=("/**", "/*!"),
    function_nodes=frozenset({"function_item", "closure_expression"}),
    keywords=frozenset(
        "fn let mut if else for while loop match return impl struct enum trait pub use mod const static "
        "ref move async await unsafe where type crate self break continue".split()
    ),
)

GO = LangSpec(
    name="go",
    grammar="go",
    function_nodes=frozenset({"function_declaration", "method_declaration", "func_literal"}),
    doc_by_convention_nodes=frozenset(
        {"function_declaration", "method_declaration", "type_declaration", "const_declaration", "var_declaration", "package_clause"}
    ),
    keywords=frozenset(
        "func if else for range switch case break continue return go defer chan select map struct interface "
        "type var const package import nil make new".split()
    ),
)

EXTENSIONS: dict[str, LangSpec] = {
    ".c": C, ".h": C,
    ".cpp": CPP, ".cc": CPP, ".cxx": CPP, ".hpp": CPP, ".hh": CPP, ".hxx": CPP,
    ".js": JS, ".mjs": JS, ".cjs": JS, ".jsx": JS,
    ".ts": TS, ".mts": TS, ".cts": TS,
    ".tsx": TSX,
    ".rs": RUST,
    ".go": GO,
}

COMMENT_NODE_TYPES = frozenset({"comment", "line_comment", "block_comment"})


def spec_for_path(path: str) -> LangSpec | None:
    from pathlib import Path

    return EXTENSIONS.get(Path(path).suffix.lower())

"""Per-language knowledge: file extensions, grammar names, comment node types,
doc-comment prefixes, and function-like node types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LangSpec:
    name: str                       # our canonical name
    grammar: str                    # tree-sitter-language-pack grammar name
    line_marker: str = "//"         # "#" for Python files
    doc_line_prefixes: tuple[str, ...] = ()    # e.g. ///, //!
    doc_block_prefixes: tuple[str, ...] = ()   # e.g. /**, /*!
    function_nodes: frozenset[str] = frozenset()
    # node types whose preceding own-line comment is a doc comment by convention
    doc_by_convention_nodes: frozenset[str] = frozenset()
    # node types whose body's first string statement is a doc comment (Python)
    docstring_containers: frozenset[str] = frozenset()
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

PY = LangSpec(
    name="python",
    grammar="python",
    line_marker="#",
    function_nodes=frozenset({"function_definition", "lambda"}),
    docstring_containers=frozenset({"module", "function_definition", "class_definition"}),
    keywords=frozenset(
        "def class if elif else for while return import from as with try except finally raise "
        "lambda pass break continue global nonlocal yield assert del not and or in is None True False self".split()
    ),
)

JAVA = LangSpec(
    name="java",
    grammar="java",
    doc_block_prefixes=("/**",),
    function_nodes=frozenset({"method_declaration", "constructor_declaration", "lambda_expression"}),
    keywords=frozenset(
        "class interface enum extends implements public private protected static final void int long "
        "short byte char boolean float double new return if else for while do switch case break continue "
        "try catch finally throw throws import package this super abstract synchronized instanceof".split()
    ),
)

CSHARP = LangSpec(
    name="csharp",
    grammar="csharp",
    doc_line_prefixes=("///",),
    doc_block_prefixes=("/**",),
    function_nodes=frozenset(
        {"method_declaration", "constructor_declaration", "local_function_statement", "lambda_expression"}
    ),
    keywords=frozenset(
        "class struct interface enum namespace using public private protected internal static readonly "
        "void var new return if else for foreach while do switch case break continue try catch finally "
        "throw async await string int bool this base override virtual abstract sealed partial get set".split()
    ),
)

KOTLIN = LangSpec(
    name="kotlin",
    grammar="kotlin",
    doc_block_prefixes=("/**",),
    function_nodes=frozenset({"function_declaration", "lambda_literal"}),
    keywords=frozenset(
        "fun val var class object interface enum data sealed if else for while when return import package "
        "this super null true false is in as try catch finally throw suspend override open private public "
        "internal protected companion init".split()
    ),
)

SWIFT = LangSpec(
    name="swift",
    grammar="swift",
    doc_line_prefixes=("///",),
    doc_block_prefixes=("/**",),
    function_nodes=frozenset({"function_declaration", "init_declaration", "lambda_literal"}),
    keywords=frozenset(
        "func let var class struct enum protocol extension if else guard for while switch case return "
        "import init self super nil true false try catch throw throws async await defer private public "
        "internal fileprivate static override final where in is as some any".split()
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
    ".py": PY, ".pyi": PY,
    ".java": JAVA,
    ".cs": CSHARP,
    ".kt": KOTLIN, ".kts": KOTLIN,
    ".swift": SWIFT,
}

COMMENT_NODE_TYPES = frozenset({"comment", "line_comment", "block_comment", "multiline_comment"})

# files whose purpose is the public interface: API documentation BELONGS here
_INTERFACE_SUFFIXES = (".h", ".hpp", ".hh", ".hxx", ".d.ts", ".d.mts", ".d.cts", ".pyi")


def is_interface_file(path: str) -> bool:
    return path.lower().endswith(_INTERFACE_SUFFIXES)


def spec_for_path(path: str) -> LangSpec | None:
    from pathlib import Path

    return EXTENSIONS.get(Path(path).suffix.lower())

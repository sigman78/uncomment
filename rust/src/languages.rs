//! Per-language knowledge, ported from src/unwaffle/languages.py. Grammar
//! crates differ from the Python side's language-pack builds, so each
//! language's node-type quirks are re-verified by the parity harness before
//! its rules are trusted.

use tree_sitter::Language;

pub struct LangSpec {
    pub name: &'static str,
    pub line_marker: &'static str,
    pub doc_line_prefixes: &'static [&'static str],
    pub doc_block_prefixes: &'static [&'static str],
    /// Node types whose preceding own-line comment is a doc comment by
    /// convention (Go).
    pub doc_by_convention_nodes: &'static [&'static str],
    /// Python: containers whose first string statement is a docstring.
    pub docstring_containers: &'static [&'static str],
    pub function_nodes: &'static [&'static str],
}

const NONE: &[&str] = &[];
const C_DOC_LINE: &[&str] = &["///", "//!"];
const C_DOC_BLOCK: &[&str] = &["/**", "/*!"];
const JSDOC: &[&str] = &["/**"];

const JS_FUNCS: &[&str] = &[
    "function_declaration", "function_expression", "arrow_function",
    "method_definition", "generator_function_declaration",
];

macro_rules! spec {
    ($name:ident, $lang:expr, $marker:expr, $dl:expr, $db:expr, $conv:expr, $docstr:expr, $funcs:expr) => {
        pub static $name: LangSpec = LangSpec {
            name: $lang,
            line_marker: $marker,
            doc_line_prefixes: $dl,
            doc_block_prefixes: $db,
            doc_by_convention_nodes: $conv,
            docstring_containers: $docstr,
            function_nodes: $funcs,
        };
    };
}

spec!(C, "c", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE, &["function_definition"]);
spec!(CPP, "cpp", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE,
      &["function_definition", "lambda_expression"]);
spec!(JS, "javascript", "//", NONE, JSDOC, NONE, NONE, JS_FUNCS);
spec!(TS, "typescript", "//", NONE, JSDOC, NONE, NONE, JS_FUNCS);
spec!(TSX, "tsx", "//", NONE, JSDOC, NONE, NONE, JS_FUNCS);
spec!(RUST, "rust", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE,
      &["function_item", "closure_expression"]);
spec!(
    GO, "go", "//", NONE, NONE,
    &["function_declaration", "method_declaration", "type_declaration",
      "const_declaration", "var_declaration", "package_clause"],
    NONE,
    &["function_declaration", "method_declaration", "func_literal"]
);
spec!(PY, "python", "#", NONE, NONE, NONE, &["module", "function_definition", "class_definition"],
      &["function_definition", "lambda"]);
spec!(JAVA, "java", "//", NONE, JSDOC, NONE, NONE,
      &["method_declaration", "constructor_declaration", "lambda_expression"]);
spec!(CSHARP, "csharp", "//", &["///"], JSDOC, NONE, NONE,
      &["method_declaration", "constructor_declaration", "local_function_statement", "lambda_expression"]);
spec!(KOTLIN, "kotlin", "//", NONE, JSDOC, NONE, NONE,
      &["function_declaration", "lambda_literal"]);
spec!(SWIFT, "swift", "//", &["///"], C_DOC_BLOCK, NONE, NONE,
      &["function_declaration", "init_declaration", "lambda_literal"]);

pub fn spec_for_path(path: &str) -> Option<(&'static LangSpec, Language)> {
    let ext = path.rsplit('.').next()?.to_ascii_lowercase();
    Some(match ext.as_str() {
        "c" | "h" => (&C, tree_sitter_c::LANGUAGE.into()),
        "cpp" | "cc" | "cxx" | "hpp" | "hh" | "hxx" => (&CPP, tree_sitter_cpp::LANGUAGE.into()),
        "js" | "mjs" | "cjs" | "jsx" => (&JS, tree_sitter_javascript::LANGUAGE.into()),
        "ts" | "mts" | "cts" => (&TS, tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()),
        "tsx" => (&TSX, tree_sitter_typescript::LANGUAGE_TSX.into()),
        "rs" => (&RUST, tree_sitter_rust::LANGUAGE.into()),
        "go" => (&GO, tree_sitter_go::LANGUAGE.into()),
        "py" | "pyi" => (&PY, tree_sitter_python::LANGUAGE.into()),
        "java" => (&JAVA, tree_sitter_java::LANGUAGE.into()),
        "cs" => (&CSHARP, tree_sitter_c_sharp::LANGUAGE.into()),
        "kt" | "kts" => (&KOTLIN, tree_sitter_kotlin_ng::LANGUAGE.into()),
        "swift" => (&SWIFT, tree_sitter_swift::LANGUAGE.into()),
        _ => return None,
    })
}

pub fn is_comment_node(kind: &str) -> bool {
    matches!(kind, "comment" | "line_comment" | "block_comment" | "multiline_comment")
}

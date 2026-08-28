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
}

const NONE: &[&str] = &[];
const C_DOC_LINE: &[&str] = &["///", "//!"];
const C_DOC_BLOCK: &[&str] = &["/**", "/*!"];
const JSDOC: &[&str] = &["/**"];

macro_rules! spec {
    ($name:ident, $lang:expr, $marker:expr, $dl:expr, $db:expr, $conv:expr, $docstr:expr) => {
        pub static $name: LangSpec = LangSpec {
            name: $lang,
            line_marker: $marker,
            doc_line_prefixes: $dl,
            doc_block_prefixes: $db,
            doc_by_convention_nodes: $conv,
            docstring_containers: $docstr,
        };
    };
}

spec!(C, "c", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE);
spec!(CPP, "cpp", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE);
spec!(JS, "javascript", "//", NONE, JSDOC, NONE, NONE);
spec!(TS, "typescript", "//", NONE, JSDOC, NONE, NONE);
spec!(TSX, "tsx", "//", NONE, JSDOC, NONE, NONE);
spec!(RUST, "rust", "//", C_DOC_LINE, C_DOC_BLOCK, NONE, NONE);
spec!(
    GO, "go", "//", NONE, NONE,
    &["function_declaration", "method_declaration", "type_declaration",
      "const_declaration", "var_declaration", "package_clause"],
    NONE
);
spec!(PY, "python", "#", NONE, NONE, NONE, &["module", "function_definition", "class_definition"]);
spec!(JAVA, "java", "//", NONE, JSDOC, NONE, NONE);
spec!(CSHARP, "csharp", "//", &["///"], JSDOC, NONE, NONE);
spec!(KOTLIN, "kotlin", "//", NONE, JSDOC, NONE, NONE);
spec!(SWIFT, "swift", "//", &["///"], C_DOC_BLOCK, NONE, NONE);

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

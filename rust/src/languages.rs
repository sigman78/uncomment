//! Per-language knowledge. Ported incrementally from src/unwaffle/languages.py;
//! a language absent here is skipped by the harness, never mis-parsed.

use tree_sitter::Language;

pub struct LangSpec {
    pub name: &'static str,
    pub line_marker: &'static str,
    pub doc_line_prefixes: &'static [&'static str],
    pub doc_block_prefixes: &'static [&'static str],
}

pub static C: LangSpec = LangSpec {
    name: "c",
    line_marker: "//",
    doc_line_prefixes: &["///", "//!"],
    doc_block_prefixes: &["/**", "/*!"],
};

pub static PY: LangSpec = LangSpec {
    name: "python",
    line_marker: "#",
    doc_line_prefixes: &[],
    doc_block_prefixes: &[],
};

pub fn spec_for_path(path: &str) -> Option<(&'static LangSpec, Language)> {
    let ext = path.rsplit('.').next()?.to_ascii_lowercase();
    match ext.as_str() {
        "c" | "h" => Some((&C, tree_sitter_c::LANGUAGE.into())),
        "py" | "pyi" => Some((&PY, tree_sitter_python::LANGUAGE.into())),
        _ => None,
    }
}

pub fn is_comment_node(kind: &str) -> bool {
    matches!(kind, "comment" | "line_comment" | "block_comment" | "multiline_comment")
}

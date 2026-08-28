//! Core data types shared by extraction, rules, and reporting.
//! Mirrors src/unwaffle/model.py — the corpus sidecars are the contract
//! both implementations must satisfy.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Line,
    Block,
    Doc,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Attachment {
    FileHeader,
    Preceding,
    Trailing,
    Floating,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Info,
    Warn,
    Error,
}

/// One logical comment: a block comment, a doc comment, or a run of
/// adjacent single-line comments merged into one unit.
#[derive(Debug, Clone, Serialize)]
pub struct Comment {
    pub path: String,
    pub lang: &'static str,
    pub kind: Kind,
    pub attachment: Attachment,
    /// Raw text including comment markers.
    pub text: String,
    /// Marker-stripped text, one string, \n-joined.
    pub content: String,
    /// 1-based, inclusive.
    pub start_line: usize,
    pub end_line: usize,
    /// 0-based byte column of the first marker.
    pub col: usize,
    pub attached_code: String,
    pub in_function: bool,
    pub function_name: String,
    pub is_directive: bool,
}

impl Comment {
    pub fn line_count(&self) -> usize {
        self.end_line - self.start_line + 1
    }

    pub fn word_count(&self) -> usize {
        self.content.split_whitespace().count()
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Finding {
    pub rule: &'static str,
    pub severity: Severity,
    pub path: String,
    pub line: usize,
    pub end_line: usize,
    pub message: String,
    pub action: String,
    pub excerpt: String,
}

/// A function/method span, used for per-function density rules.
#[derive(Debug, Clone, Serialize)]
pub struct FunctionInfo {
    pub path: String,
    pub name: String,
    pub start_line: usize,
    pub end_line: usize,
    pub body_line_count: usize,
}

#[derive(Debug)]
pub struct SourceFile {
    pub path: String,
    pub lang: &'static str,
    pub lines: Vec<String>,
    pub comments: Vec<Comment>,
    pub functions: Vec<FunctionInfo>,
    /// Lines with code on them; comment-only lines excluded.
    pub code_line_count: usize,
    /// Source with comment bytes blanked.
    pub code_lines: Vec<String>,
    pub comment_line_count: usize,
}

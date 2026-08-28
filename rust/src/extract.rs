//! Tree-sitter comment extraction — first slice of the port.
//!
//! Parity with src/unwaffle/extract.py so far: raw comment collection,
//! adjacent line-comment merging (same column, consecutive rows, no code
//! before), comment-byte masking for code_lines/code_line_count, and
//! attachment classification. Not yet ported: docstrings, directive
//! classification, function context, doc-by-convention, the
//! directive-line merge splits.

use crate::languages::{is_comment_node, spec_for_path, LangSpec};
use crate::model::{Attachment, Comment, Kind, SourceFile};
use tree_sitter::{Node, Parser};

struct RawComment {
    text: String,
    start_row: usize,
    start_col: usize,
    end_row: usize,
    end_col: usize,
}

/// Split on \n only: tree-sitter rows do the same, while a \f or U+2028
/// aware split would desync row arithmetic.
fn byte_lines(data: &[u8]) -> Vec<&[u8]> {
    data.split(|&b| b == b'\n').collect()
}

pub fn strip_markers(raw: &str, line_marker: &str) -> String {
    let mut out: Vec<String> = Vec::new();
    for line in raw.split('\n') {
        let mut s = line.trim();
        if line_marker == "#" {
            // one marker only: '#### section' keeps its banner characters
            s = s.strip_prefix('#').unwrap_or(s);
        } else {
            let mut stripped = false;
            for prefix in ["/*!", "/**", "/*", "//!", "///", "//"] {
                if let Some(rest) = s.strip_prefix(prefix) {
                    s = rest;
                    stripped = true;
                    break;
                }
            }
            if !stripped && s.starts_with('*') && !s.starts_with("*/") {
                s = &s[1..];
            }
            s = s.strip_suffix("*/").unwrap_or(s);
        }
        out.push(s.trim().to_string());
    }
    while out.first().is_some_and(|l| l.is_empty()) {
        out.remove(0);
    }
    while out.last().is_some_and(|l| l.is_empty()) {
        out.pop();
    }
    out.join("\n")
}

fn collect_comments(root: Node, data: &[u8]) -> Vec<RawComment> {
    let mut out = Vec::new();
    let mut stack = vec![root];
    while let Some(node) = stack.pop() {
        if is_comment_node(node.kind()) {
            let text = node
                .utf8_text(data)
                .unwrap_or_default()
                .trim_end_matches(['\r', '\n'])
                .to_string();
            let (mut end_row, mut end_col) = (node.end_position().row, node.end_position().column);
            // some grammars include the trailing newline in the node
            if end_col == 0 && end_row > node.start_position().row {
                end_row -= 1;
                end_col = usize::MAX;
            }
            out.push(RawComment {
                text,
                start_row: node.start_position().row,
                start_col: node.start_position().column,
                end_row,
                end_col,
            });
            continue;
        }
        for i in (0..node.child_count() as u32).rev() {
            if let Some(child) = node.child(i) {
                stack.push(child);
            }
        }
    }
    out.sort_by_key(|c| (c.start_row, c.start_col));
    out
}

pub fn extract_source(path: &str, source: &str, spec: &'static LangSpec) -> SourceFile {
    let (_, language) = spec_for_path(path).expect("caller checked the language");
    let mut parser = Parser::new();
    parser
        .set_language(&language)
        .expect("grammar/runtime version mismatch is a build error, not a runtime state");
    let source = source.strip_prefix('\u{feff}').unwrap_or(source);
    let data = source.as_bytes();
    let tree = parser.parse(data, None).expect("tree-sitter returns a tree for any input");

    let raw = collect_comments(tree.root_node(), data);
    let blines = byte_lines(data);
    let lines: Vec<String> = blines
        .iter()
        .map(|bl| {
            String::from_utf8_lossy(bl)
                .trim_end_matches('\r')
                .to_string()
        })
        .collect();

    // per-row comment span masks, byte offsets
    let mut masks: Vec<Vec<(usize, usize)>> = vec![Vec::new(); blines.len()];
    let mut comment_rows = vec![false; blines.len()];
    for rc in &raw {
        for row in rc.start_row..=rc.end_row.min(blines.len().saturating_sub(1)) {
            comment_rows[row] = true;
            let a = if row == rc.start_row { rc.start_col } else { 0 };
            let b = if row == rc.end_row { rc.end_col } else { blines[row].len() };
            masks[row].push((a, b));
        }
    }

    let mut code_lines = Vec::with_capacity(blines.len());
    let mut code_rows = vec![false; blines.len()];
    for (row, bl) in blines.iter().enumerate() {
        let mut buf = bl.to_vec();
        for &(a, b) in &masks[row] {
            for byte in buf.iter_mut().take(b.min(bl.len())).skip(a) {
                *byte = b' ';
            }
        }
        let text = String::from_utf8_lossy(&buf).trim_end_matches('\r').to_string();
        code_rows[row] = !text.trim().is_empty();
        code_lines.push(text);
    }
    let first_code_row = code_rows.iter().position(|&c| c);

    // merge runs of line comments: consecutive rows, same column, own-line
    let is_line = |rc: &RawComment| rc.text.starts_with(spec.line_marker);
    let own_line = |rc: &RawComment| {
        blines[rc.start_row][..rc.start_col.min(blines[rc.start_row].len())]
            .iter()
            .all(|b| b.is_ascii_whitespace())
    };
    let mut groups: Vec<Vec<&RawComment>> = Vec::new();
    for rc in &raw {
        let merges = is_line(rc)
            && own_line(rc)
            && groups.last().is_some_and(|g| {
                let prev = g.last().unwrap();
                is_line(prev)
                    && own_line(prev)
                    && rc.start_row == prev.end_row + 1
                    && rc.start_col == prev.start_col
            });
        if merges {
            groups.last_mut().unwrap().push(rc);
        } else {
            groups.push(vec![rc]);
        }
    }

    let mut comments = Vec::new();
    for group in &groups {
        let first = group[0];
        let last = group[group.len() - 1];
        let text: String = group.iter().map(|rc| rc.text.as_str()).collect::<Vec<_>>().join("\n");
        let head = first.text.trim_start();
        let kind = if spec.doc_block_prefixes.iter().any(|p| head.starts_with(p))
            || spec.doc_line_prefixes.iter().any(|p| head.starts_with(p))
        {
            Kind::Doc
        } else if is_line(first) {
            Kind::Line
        } else {
            Kind::Block
        };

        let end_row = last.end_row;
        let attachment = if !own_line(first) {
            Attachment::Trailing
        } else if first_code_row.is_none_or(|fc| first.start_row < fc) {
            Attachment::FileHeader
        } else if end_row + 1 < code_rows.len() && code_rows[end_row + 1] {
            Attachment::Preceding
        } else {
            Attachment::Floating
        };
        let attached_code = match attachment {
            Attachment::Trailing => code_lines[first.start_row].trim().to_string(),
            Attachment::Preceding => code_lines[end_row + 1].trim().to_string(),
            _ => String::new(),
        };

        comments.push(Comment {
            path: path.to_string(),
            lang: spec.name,
            kind,
            attachment,
            content: strip_markers(&text, spec.line_marker),
            text,
            start_line: first.start_row + 1,
            end_line: end_row + 1,
            col: first.start_col,
            attached_code,
            in_function: false,
            function_name: String::new(),
            is_directive: false,
        });
    }

    SourceFile {
        path: path.to_string(),
        lang: spec.name,
        lines,
        comments,
        code_line_count: code_rows.iter().filter(|&&c| c).count(),
        code_lines,
        comment_line_count: comment_rows.iter().filter(|&&c| c).count(),
    }
}

pub fn extract_path(path: &std::path::Path) -> Option<SourceFile> {
    let (spec, _) = spec_for_path(path.to_str()?)?;
    let source = std::fs::read_to_string(path).ok()?;
    Some(extract_source(&path.to_string_lossy(), &source, spec))
}

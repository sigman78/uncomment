//! Tree-sitter comment extraction, ported from src/unwaffle/extract.py.
//!
//! At parity: raw collection, line-run merging (doc-class, marker, and
//! directive-line splits), comment-byte masking, the attachment cascade,
//! kind classification, Go doc-by-convention, Python docstrings, directive
//! classification, and function context.

use std::collections::{HashMap, VecDeque};
use std::sync::OnceLock;

use regex::Regex;
use tree_sitter::{Node, Parser};

use crate::directives::{is_cgo_preamble, is_directive_text};
use crate::languages::{is_comment_node, spec_for_path, LangSpec};
use crate::model::{Attachment, Comment, FunctionInfo, Kind, SourceFile};

/// A header comment directly above one of these lines documents the file,
/// not the line.
fn import_line_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r#"^\s*(#\s*(include|pragma|ifndef|define)\b|import\b|from\b|package\b|using\b|use\b|namespace\b|extern crate\b|mod\b|module\b|['"]use strict)"#,
        )
        .unwrap()
    })
}

const NAME_NODE_TYPES: &[&str] = &[
    "identifier", "field_identifier", "type_identifier", "property_identifier",
    "destructor_name", "operator_name", "simple_identifier",
];

struct RawComment {
    text: String,
    start_row: usize,
    start_col: usize,
    end_row: usize,
    end_col: usize,
    func_name: String,
    in_function: bool,
    /// (container node type, container start row) for Python docstrings.
    docstring: Option<(&'static str, usize)>,
}

/// Split on \n only: tree-sitter rows do the same, while a \f or U+2028
/// aware split would desync row arithmetic.
fn byte_lines(data: &[u8]) -> Vec<&[u8]> {
    data.split(|&b| b == b'\n').collect()
}

fn trim_blank_edges(mut out: Vec<String>) -> String {
    while out.first().is_some_and(|l| l.is_empty()) {
        out.remove(0);
    }
    while out.last().is_some_and(|l| l.is_empty()) {
        out.pop();
    }
    out.join("\n")
}

pub fn strip_markers(raw: &str, line_marker: &str) -> String {
    let mut out: Vec<String> = Vec::new();
    for line in raw.split('\n') {
        let mut s = line.trim();
        if line_marker == "#" {
            // one marker only: '#### section' keeps its banner characters and
            // '#!' keeps the '!' so the shebang stays recognizable
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
    trim_blank_edges(out)
}

/// Docstring content: quote characters and prefix letters removed.
pub fn strip_docstring_quotes(raw: &str) -> String {
    let prefix_len = raw
        .bytes()
        .take(3)
        .take_while(|b| matches!(b, b'r' | b'R' | b'u' | b'U' | b'b' | b'B' | b'f' | b'F'))
        .count();
    let rest = &raw[prefix_len..];
    let quote = ["\"\"\"", "'''", "\"", "'"].iter().find(|q| rest.starts_with(**q));
    let body = match quote {
        Some(q) => {
            let inner = &rest[q.len()..];
            inner.strip_suffix(*q).unwrap_or(inner)
        }
        None => raw,
    };
    trim_blank_edges(body.split('\n').map(|l| l.trim().to_string()).collect())
}

fn doc_class(text: &str, spec: &LangSpec) -> &'static str {
    for prefix in spec.doc_line_prefixes {
        if text.starts_with(prefix) {
            return prefix;
        }
    }
    ""
}

fn marker_line(text: &str, spec: &LangSpec) -> bool {
    let first = text.split('\n').next().unwrap_or("");
    strip_markers(first, spec.line_marker).starts_with("unwaffle-ignore")
}

fn directive_line(text: &str, spec: &LangSpec) -> bool {
    let first = text.split('\n').next().unwrap_or("");
    is_directive_text(&strip_markers(first, spec.line_marker), spec.name, Some(Kind::Line))
}

fn classify_kind(text: &str, spec: &LangSpec) -> Kind {
    if spec.doc_block_prefixes.iter().any(|p| text.starts_with(p)) && !text.starts_with("/**/") {
        return Kind::Doc; // bare "/**/" separators are not docs
    }
    if spec.doc_line_prefixes.iter().any(|p| text.starts_with(p)) {
        return Kind::Doc;
    }
    if text.starts_with("/*") {
        return Kind::Block;
    }
    Kind::Line
}

fn node_text(node: Node, data: &[u8]) -> String {
    node.utf8_text(data).unwrap_or_default().to_string()
}

fn function_name(node: Node, data: &[u8]) -> String {
    if let Some(name) = node.child_by_field_name("name") {
        return node_text(name, data);
    }
    if let Some(declarator) = node.child_by_field_name("declarator") {
        // depth-first through the declarator: the first name-like node wins
        let mut queue = VecDeque::from([declarator]);
        while let Some(n) = queue.pop_front() {
            if NAME_NODE_TYPES.contains(&n.kind()) {
                return node_text(n, data);
            }
            for i in (0..n.child_count() as u32).rev() {
                queue.push_front(n.child(i).unwrap());
            }
        }
    }
    // kotlin's function_declaration carries no name field: the identifier
    // sits among the direct children
    for i in 0..node.child_count() as u32 {
        let child = node.child(i).unwrap();
        if NAME_NODE_TYPES.contains(&child.kind()) {
            return node_text(child, data);
        }
    }
    "<anonymous>".to_string()
}

fn function_body<'t>(node: Node<'t>) -> Option<Node<'t>> {
    node.child_by_field_name("body").or_else(|| {
        // kotlin/swift bodies are typed children without a field name
        (0..node.child_count() as u32)
            .filter_map(|i| node.child(i))
            .find(|ch| matches!(ch.kind(), "function_body" | "block"))
    })
}

struct Walk {
    raw: Vec<RawComment>,
    functions: Vec<FunctionInfo>,
    /// First named non-comment node starting at each row (outermost wins).
    row_first_node: HashMap<usize, String>,
}

fn walk(root: Node, data: &[u8], path: &str, spec: &'static LangSpec) -> Walk {
    let mut w = Walk { raw: Vec::new(), functions: Vec::new(), row_first_node: HashMap::new() };
    // docstring string-node id -> (container type, container row, outer func context)
    let mut docstring_nodes: HashMap<usize, (&'static str, usize, String, bool)> = HashMap::new();
    let mut stack: Vec<(Node, String, bool)> = vec![(root, String::new(), false)];
    while let Some((node, func_name_ctx, in_func)) = stack.pop() {
        let mut raw_ctx: Option<(String, bool, Option<(&'static str, usize)>)> = None;
        if is_comment_node(node.kind()) {
            raw_ctx = Some((func_name_ctx.clone(), in_func, None));
        } else if let Some((container, row, outer_func, outer_in)) = docstring_nodes.get(&node.id()) {
            raw_ctx = Some((outer_func.clone(), *outer_in, Some((container, *row))));
        }
        if let Some((fname, infn, docstring)) = raw_ctx {
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
            w.raw.push(RawComment {
                text,
                start_row: node.start_position().row,
                start_col: node.start_position().column,
                end_row,
                end_col,
                func_name: fname,
                in_function: infn,
                docstring,
            });
            continue;
        }
        if node.is_named() && node.kind() != "translation_unit" {
            w.row_first_node.entry(node.start_position().row).or_insert_with(|| node.kind().to_string());
        }
        if let Some(container) = spec.docstring_containers.iter().find(|c| **c == node.kind()) {
            let body = if node.kind() == "module" { Some(node) } else { node.child_by_field_name("body") };
            if let Some(body) = body {
                for i in 0..body.child_count() as u32 {
                    let child = body.child(i).unwrap();
                    if is_comment_node(child.kind()) {
                        continue;
                    }
                    // the grammar may or may not wrap the docstring statement
                    let target = if child.kind() == "string" {
                        Some(child)
                    } else if child.kind() == "expression_statement"
                        && child.named_child_count() == 1
                        && child.named_child(0).unwrap().kind() == "string"
                    {
                        child.named_child(0)
                    } else {
                        None
                    };
                    if let Some(t) = target {
                        docstring_nodes.insert(
                            t.id(),
                            (container, node.start_position().row, func_name_ctx.clone(), in_func),
                        );
                    }
                    break; // only the first statement can be a docstring
                }
            }
        }
        let (mut child_func, mut child_in) = (func_name_ctx, in_func);
        if spec.function_nodes.contains(&node.kind()) {
            let name = function_name(node, data);
            if let Some(body) = function_body(node) {
                w.functions.push(FunctionInfo {
                    path: path.to_string(),
                    name: name.clone(),
                    start_line: node.start_position().row + 1,
                    end_line: node.end_position().row + 1,
                    body_line_count: body.end_position().row - body.start_position().row + 1,
                });
            }
            (child_func, child_in) = (name, true);
        }
        for i in (0..node.child_count() as u32).rev() {
            if let Some(child) = node.child(i) {
                stack.push((child, child_func.clone(), child_in));
            }
        }
    }
    w.raw.sort_by_key(|c| (c.start_row, c.start_col));
    w
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

    let w = walk(tree.root_node(), data, path, spec);
    let raw = &w.raw;
    let blines = byte_lines(data);
    let lines: Vec<String> = blines
        .iter()
        .map(|bl| String::from_utf8_lossy(bl).trim_end_matches('\r').to_string())
        .collect();

    // rows occupied by comments, and per-row comment span masks (byte offsets)
    let mut masks: Vec<Vec<(usize, usize)>> = vec![Vec::new(); blines.len()];
    let mut comment_rows = vec![false; blines.len()];
    for rc in raw {
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

    let code_before = |rc: &RawComment| -> String {
        let bl = blines.get(rc.start_row).copied().unwrap_or(b"");
        String::from_utf8_lossy(&bl[..rc.start_col.min(bl.len())]).trim().to_string()
    };
    let code_after = |rc: &RawComment| -> String {
        let bl = blines.get(rc.end_row).copied().unwrap_or(b"");
        String::from_utf8_lossy(&bl[rc.end_col.min(bl.len())..]).trim().to_string()
    };

    // ---- group adjacent line comments into logical comments ----
    let mut groups: Vec<Vec<&RawComment>> = Vec::new();
    for rc in raw {
        let is_line = rc.docstring.is_none() && rc.text.starts_with(spec.line_marker);
        let merges = is_line
            && code_before(rc).is_empty()
            && groups.last().is_some_and(|g| {
                let prev = g[g.len() - 1];
                prev.docstring.is_none()
                    && prev.text.starts_with(spec.line_marker)
                    && code_before(prev).is_empty()
                    && rc.start_row == prev.end_row + 1
                    && rc.start_col == prev.start_col
                    && doc_class(&rc.text, spec) == doc_class(&prev.text, spec)
                    // directive and suppression-marker lines never merge with
                    // prose, so the prose part stays judged and the marker
                    // keeps its scope
                    && directive_line(&rc.text, spec) == directive_line(&prev.text, spec)
                    && marker_line(&rc.text, spec) == marker_line(&prev.text, spec)
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

        if let Some((container_type, container_row)) = first.docstring {
            let (attachment, attached) = if container_type == "module" {
                (Attachment::FileHeader, String::new())
            } else {
                // the docstring documents the def/class line above it
                let attached = lines.get(container_row).map(|l| l.trim().to_string()).unwrap_or_default();
                (Attachment::Preceding, attached)
            };
            comments.push(Comment {
                path: path.to_string(),
                lang: spec.name,
                kind: Kind::Doc,
                attachment,
                content: strip_docstring_quotes(&first.text),
                text: first.text.clone(),
                start_line: first.start_row + 1,
                end_line: last.end_row + 1,
                col: first.start_col,
                attached_code: attached,
                in_function: first.in_function,
                function_name: first.func_name.clone(),
                is_directive: false,
            });
            continue;
        }

        let raw_text: String = group.iter().map(|rc| rc.text.as_str()).collect::<Vec<_>>().join("\n");
        let trailing_code = code_before(first);
        let after_code = code_after(last);
        let next_row_code = code_rows.get(last.end_row + 1).copied().unwrap_or(false);
        let next_line = lines.get(last.end_row + 1).map(|l| l.trim().to_string()).unwrap_or_default();
        let before_first_code = first_code_row.is_none_or(|fc| first.start_row < fc);

        let (attachment, attached) = if !trailing_code.is_empty() {
            (Attachment::Trailing, trailing_code)
        } else if !after_code.is_empty() {
            (Attachment::Preceding, after_code)
        } else if raw_text.starts_with("//!") || raw_text.starts_with("/*!") {
            // inner/module doc: documents the file, not the next item
            (Attachment::FileHeader, String::new())
        } else if before_first_code && (!next_row_code || import_line_re().is_match(&next_line)) {
            (Attachment::FileHeader, String::new())
        } else if next_row_code {
            (Attachment::Preceding, next_line)
        } else {
            (Attachment::Floating, String::new())
        };

        let mut kind = classify_kind(&raw_text, spec);
        if kind != Kind::Doc
            && matches!(attachment, Attachment::Preceding | Attachment::FileHeader)
            && !first.in_function
            && !spec.doc_by_convention_nodes.is_empty()
            && w.row_first_node
                .get(&(last.end_row + 1))
                .is_some_and(|k| spec.doc_by_convention_nodes.contains(&k.as_str()))
        {
            // e.g. Go: a comment directly above a declaration or the package
            // clause is a doc comment, even without special markers
            kind = Kind::Doc;
        }

        let content = strip_markers(&raw_text, spec.line_marker);
        let content_lines: Vec<&str> = content.split('\n').filter(|l| !l.trim().is_empty()).collect();
        let content_head = content_lines.first().copied().unwrap_or("");
        // line-comment groups are class-uniform (directive lines never merge
        // with prose), so the head speaks for the group. A block comment is a
        // directive only when it contains nothing but the directive — a prose
        // essay hiding behind an eslint-disable first line stays judged.
        let directive = is_cgo_preamble(spec.name, &attached)
            || (is_directive_text(content_head, spec.name, Some(kind))
                && (kind == Kind::Line || content_lines.len() == 1));

        comments.push(Comment {
            path: path.to_string(),
            lang: spec.name,
            kind,
            attachment,
            content,
            text: raw_text,
            start_line: first.start_row + 1,
            end_line: last.end_row + 1,
            col: first.start_col,
            attached_code: attached,
            in_function: first.in_function,
            function_name: first.func_name.clone(),
            is_directive: directive,
        });
    }

    SourceFile {
        path: path.to_string(),
        lang: spec.name,
        lines,
        comments,
        functions: w.functions,
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

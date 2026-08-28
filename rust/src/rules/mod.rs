//! Rule framework and registry, ported from src/unwaffle/rules/__init__.py.

use std::sync::OnceLock;

use regex::Regex;

use crate::config::Config;
use crate::model::{Comment, Finding, Severity, SourceFile};

pub mod core;
pub mod ste;

pub struct Rule {
    pub id: &'static str,
    pub title: &'static str,
    pub severity: Severity,
    pub run: fn(&SourceFile, &Config) -> Vec<Finding>,
}

pub fn all_rules() -> &'static [Rule] {
    &[
        Rule { id: "UC001", title: "restates-code", severity: Severity::Warn, run: core::restates_code },
        Rule { id: "UC002", title: "narration", severity: Severity::Warn, run: core::narration },
        Rule { id: "UC003", title: "change-narration", severity: Severity::Error, run: core::change_narration },
        Rule { id: "UC004", title: "banner", severity: Severity::Warn, run: core::banner },
        Rule { id: "UC005", title: "commented-out-code", severity: Severity::Warn, run: core::commented_out_code },
        Rule { id: "UC006", title: "function-comment-density", severity: Severity::Warn, run: core::function_density },
        Rule { id: "UC007", title: "redundant-doc", severity: Severity::Warn, run: core::redundant_doc },
        Rule { id: "UC008", title: "doc-migration", severity: Severity::Info, run: core::doc_migration },
        Rule { id: "UC009", title: "trailing-comment-length", severity: Severity::Warn, run: core::trailing_length },
        Rule { id: "UC010", title: "boilerplate-label", severity: Severity::Warn, run: core::boilerplate_label },
        Rule { id: "UC011", title: "unowned-todo", severity: Severity::Info, run: core::unowned_todo },
        Rule { id: "UC012", title: "emoji-comment", severity: Severity::Warn, run: core::emoji_comment },
        Rule { id: "STE01", title: "long-sentence", severity: Severity::Info, run: ste::long_sentence },
        Rule { id: "STE02", title: "passive-voice", severity: Severity::Info, run: ste::passive_voice },
        Rule { id: "STE03", title: "unapproved-word", severity: Severity::Info, run: ste::unapproved_word },
        Rule { id: "STE04", title: "long-paragraph", severity: Severity::Info, run: ste::long_paragraph },
    ]
}

fn license_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(?i)copyright|license|licence|permission is hereby granted|spdx-license|apache|gnu general public|redistribution and use",
        )
        .unwrap()
    })
}

pub fn is_license_header(c: &Comment) -> bool {
    // a license block at the very top counts even when code follows directly
    // (which classifies it as 'preceding' rather than 'file_header')
    let at_top = matches!(c.attachment, crate::model::Attachment::FileHeader) || c.start_line == 1;
    at_top && license_re().is_match(&c.content)
}

/// Occurrences of the span marker, skipping the file-wide form. The python
/// regex's (?!-file) lookahead, hand-coded.
fn ignore_marker_at(content: &str) -> Option<(usize, Option<Vec<String>>)> {
    for (idx, _) in content.match_indices("unwaffle-ignore") {
        let rest = &content[idx + "unwaffle-ignore".len()..];
        if rest.starts_with("-file") {
            continue;
        }
        let rules = rest.strip_prefix('[').and_then(|r| {
            let end = r.find(']')?;
            let inner = &r[..end];
            if !inner.is_empty()
                && inner.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == ' ' || ch == ',')
            {
                Some(
                    inner
                        .split(',')
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect(),
                )
            } else {
                None
            }
        });
        return Some((idx, rules));
    }
    None
}

/// Rule ids granted a file-wide exception by unwaffle-ignore-file markers
/// anywhere in the file.
pub fn file_wide_rules(sf: &SourceFile) -> Vec<String> {
    let mut rules = Vec::new();
    for c in &sf.comments {
        for (idx, _) in c.content.match_indices("unwaffle-ignore-file[") {
            let rest = &c.content[idx + "unwaffle-ignore-file[".len()..];
            if let Some(end) = rest.find(']') {
                let inner = &rest[..end];
                if inner.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == ' ' || ch == ',') {
                    rules.extend(inner.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()));
                }
            }
        }
    }
    rules
}

/// Rule ids the file-level gate signals honor: any file-wide marker, plus
/// rule-listed span markers wherever they sit — a span cannot reach a
/// file-level signal, so an explicit rule list anywhere in the file is
/// their suppression contract.
pub fn file_suppressed_rules(sf: &SourceFile) -> Vec<String> {
    let mut rules = file_wide_rules(sf);
    for c in &sf.comments {
        if let Some((_, Some(listed))) = ignore_marker_at(&c.content) {
            rules.extend(listed);
        }
    }
    rules
}

struct Suppression {
    rules: Option<Vec<String>>,
    start: usize,
    end: usize,
}

fn suppressions(sf: &SourceFile) -> Vec<Suppression> {
    let mut sups = Vec::new();
    for (i, c) in sf.comments.iter().enumerate() {
        let Some((_, rules)) = ignore_marker_at(&c.content) else { continue };
        let (start, mut end) = (c.start_line, c.end_line);
        if c.content.trim().starts_with("unwaffle-ignore") {
            // a standalone marker covers the comment or code line below it
            end = match sf.comments.get(i + 1) {
                Some(nxt) if nxt.start_line == c.end_line + 1 => nxt.end_line,
                _ => c.end_line + 1,
            };
        }
        sups.push(Suppression { rules, start, end });
    }
    sups
}

fn suppressed(f: &Finding, sups: &[Suppression]) -> bool {
    for s in sups {
        match &s.rules {
            None => {
                if s.start <= f.line && f.end_line <= s.end {
                    return true;
                }
            }
            Some(rules) => {
                if rules.iter().any(|r| r == f.rule) && !(f.end_line < s.start || f.line > s.end) {
                    return true;
                }
            }
        }
    }
    false
}

fn is_marker(c: &Comment) -> bool {
    c.content.trim().starts_with("unwaffle-ignore")
}

/// Comment lines that are purely a suppression marker: never counted by the
/// gate's prose math.
pub fn marker_line_count(c: &Comment) -> usize {
    c.content.split('\n').filter(|l| l.trim().starts_with("unwaffle-ignore")).count()
}

/// Text as the wording rules should see it: the project's approved terms are
/// blanked out first. A term with an uppercase letter matches exactly;
/// all-lowercase matches any case. Boundary checks replace the python
/// pattern's (?<!\w)/(?!\w) lookarounds.
pub fn wording_text(text: &str, cfg: &Config) -> String {
    if cfg.approved_terms.is_empty() {
        return text.to_string();
    }
    let is_word = |ch: char| ch.is_alphanumeric() || ch == '_';
    let mut out = text.to_string();
    for term in &cfg.approved_terms {
        let exact = term.chars().any(|ch| ch.is_uppercase());
        let hay = if exact { out.clone() } else { out.to_lowercase() };
        let needle = if exact { term.clone() } else { term.to_lowercase() };
        let mut result = String::with_capacity(out.len());
        let mut pos = 0;
        while let Some(rel) = hay[pos..].find(&needle) {
            let at = pos + rel;
            let before_ok = !out[..at].chars().next_back().is_some_and(is_word);
            let after_ok = !out[at + needle.len()..].chars().next().is_some_and(is_word);
            result.push_str(&out[pos..at]);
            if !(before_ok && after_ok) {
                result.push_str(&out[at..at + needle.len()]);
            }
            pos = at + needle.len();
        }
        result.push_str(&out[pos..]);
        out = result;
    }
    out
}

/// Comments that rules may judge: tooling directives and standalone
/// suppression markers are exempt, plus anything matching the user's extra
/// directive-patterns config.
pub fn visible_comments(sf: &SourceFile, cfg: &Config) -> Vec<Comment> {
    let extra: Vec<Regex> = cfg.directive_patterns.iter().filter_map(|p| Regex::new(p).ok()).collect();
    sf.comments
        .iter()
        .filter(|c| !c.is_directive && !is_marker(c) && !extra.iter().any(|rx| rx.is_match(&c.content)))
        .cloned()
        .collect()
}

fn cap_hints(rule_id: &str, findings: Vec<Finding>, cfg: &Config) -> Vec<Finding> {
    let hints: Vec<&Finding> = findings.iter().filter(|f| f.severity == Severity::Info).collect();
    if hints.len() <= cfg.max_hints_per_rule {
        return findings;
    }
    let dropped = hints.len() - cfg.max_hints_per_rule;
    let last = hints[cfg.max_hints_per_rule - 1];
    let summary = Finding {
        rule: last.rule,
        severity: Severity::Info,
        path: last.path.clone(),
        line: last.line,
        end_line: last.line,
        message: format!("{dropped} more {rule_id} hint(s) in this file, not listed"),
        action: "The pattern repeats through this file; apply the same fix everywhere.".to_string(),
        excerpt: String::new(),
    };
    let mut out: Vec<Finding> = findings.iter().filter(|f| f.severity != Severity::Info).cloned().collect();
    out.extend(
        findings.iter().filter(|f| f.severity == Severity::Info).take(cfg.max_hints_per_rule).cloned(),
    );
    out.push(summary);
    out
}

pub fn run_rules(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let sups = suppressions(sf);
    let file_wide = file_wide_rules(sf);
    let mut visible = sf.clone();
    visible.comments = visible_comments(sf, cfg);

    let mut findings: Vec<Finding> = Vec::new();
    for rule in all_rules() {
        if !cfg.rule_enabled(rule.id) || file_wide.iter().any(|r| r == rule.id) {
            continue;
        }
        let mut rule_findings = Vec::new();
        for mut f in (rule.run)(&visible, cfg) {
            if suppressed(&f, &sups) {
                continue;
            }
            if let Some(over) = cfg.severity_override(rule.id) {
                f.severity = over;
            }
            rule_findings.push(f);
        }
        findings.extend(cap_hints(rule.id, rule_findings, cfg));
    }
    findings.sort_by(|a, b| (&a.path, a.line, a.rule).cmp(&(&b.path, b.line, b.rule)));
    findings
}

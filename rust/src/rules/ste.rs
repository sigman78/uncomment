//! ASD-STE100-inspired wording rules, ported from src/unwaffle/rules/ste.py.
//! All default to INFO — they guide rewording, not gating.

use std::sync::OnceLock;

use regex::Regex;

use crate::config::Config;
use crate::model::{Comment, Finding, Severity, SourceFile};
use crate::textutil::{first_line, sentences};

use super::core::looks_like_code;
use super::{is_license_header, wording_text};

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

static URL_RE: OnceLock<Regex> = OnceLock::new();
static PARA_RE: OnceLock<Regex> = OnceLock::new();
static PASSIVE_RE: OnceLock<Regex> = OnceLock::new();
static WORD_SPLIT_RE: OnceLock<Regex> = OnceLock::new();

/// Comment content with code-looking and URL lines removed. Blank lines
/// stay: they are paragraph boundaries.
fn prose(c: &Comment) -> String {
    let url = re(&URL_RE, r"https?://\S+");
    let kept: Vec<&str> = c.content.split('\n').filter(|ln| !looks_like_code(ln, false)).collect();
    url.replace_all(&kept.join("\n"), "").to_string()
}

fn skip(c: &Comment) -> bool {
    is_license_header(c) || c.word_count() < 3
}

fn ste_finding(rule: &'static str, c: &Comment, message: String, action: &str, excerpt: String) -> Finding {
    Finding {
        rule,
        severity: Severity::Info,
        path: c.path.clone(),
        line: c.start_line,
        end_line: c.end_line,
        message,
        action: action.to_string(),
        excerpt,
    }
}

pub fn long_sentence(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let para = re(&PARA_RE, r"\n\s*\n");
    let mut out = Vec::new();
    for c in &sf.comments {
        if skip(c) {
            continue;
        }
        let text = prose(c);
        let worst = para
            .split(&text)
            .flat_map(|p| sentences(p, true))
            .max_by_key(|s| s.split_whitespace().count())
            .unwrap_or_default();
        let n = worst.split_whitespace().count();
        if n > cfg.ste_max_sentence_words {
            out.push(ste_finding(
                "STE01",
                c,
                format!("sentence has {n} words (STE limit: {})", cfg.ste_max_sentence_words),
                "Reword into short sentences, one instruction or fact each. Do not just add periods to line ends; list items may stay as fragments.",
                first_line(&worst, 72),
            ));
        }
    }
    out
}

pub fn passive_voice(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let passive = re(&PASSIVE_RE,
        r"(?i)\b(is|are|was|were|be|been|being|gets?|got)\s+(\w+ed|built|chosen|done|driven|found|given|held|hidden|kept|known|left|lost|made|meant|put|read|run|said|seen|sent|set|shown|sold|spent|taken|thrown|told|understood|used|written)\b");
    let mut out = Vec::new();
    for c in &sf.comments {
        if skip(c) {
            continue;
        }
        let text = wording_text(&prose(c), cfg);
        if let Some(m) = passive.find(&text) {
            out.push(ste_finding(
                "STE02",
                c,
                format!("passive voice ('{}')", m.as_str()),
                "Rewrite in active voice: name the actor (the function, the caller, the OS) and use a simple verb.",
                first_line(&c.content, 72),
            ));
        }
    }
    out
}

// maps a phrase to its approved replacement; phrases match before single words
const PHRASES: &[(&str, &str)] = &[
    ("in order to", "to"),
    ("prior to", "before"),
    ("subsequent to", "after"),
    ("in the event that", "if"),
    ("with the exception of", "except"),
    ("at this point in time", "now"),
    ("in conjunction with", "with"),
    ("make use of", "use"),
    ("a number of", "some"),
    ("due to the fact that", "because"),
    ("note that", "(delete it)"),
    ("it should be noted that", "(delete it)"),
    ("needless to say", "(delete it)"),
];

const WORDS: &[(&str, &str)] = &[
    ("utilize", "use"), ("utilise", "use"), ("leverage", "use"), ("employ", "use"),
    ("facilitate", "help"), ("commence", "start"), ("initiate", "start"),
    ("terminate", "stop"), ("conclude", "end"), ("demonstrate", "show"),
    ("indicate", "show"), ("attempt", "try"), ("endeavor", "try"),
    ("additional", "more"), ("additionally", "also"), ("furthermore", "also"),
    ("moreover", "also"), ("consequently", "so"), ("subsequently", "then"),
    ("approximately", "about"), ("sufficient", "enough"), ("numerous", "many"),
    ("obtain", "get"), ("acquire", "get"), ("purchase", "buy"),
    ("construct", "build"), ("fabricate", "make"), ("modify", "change"),
    ("alter", "change"), ("transmit", "send"), ("whilst", "while"),
    ("amongst", "among"), ("notwithstanding", "despite"), ("aforementioned", "this"),
    ("thus", "so"), ("hence", "so"), ("therefore", "so"), ("nevertheless", "but"),
    ("assist", "help"), ("permit", "let"), ("adequate", "enough"),
    ("basically", "(delete it)"), ("essentially", "(delete it)"),
    ("obviously", "(delete it)"), ("clearly", "(delete it)"),
    ("simply", "(delete it)"), ("actually", "(delete it)"),
];

pub fn unapproved_word(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let word_split = re(&WORD_SPLIT_RE, r"(?i)[a-z]+");
    let mut out = Vec::new();
    for c in &sf.comments {
        if skip(c) {
            continue;
        }
        let text = wording_text(&prose(c), cfg).to_lowercase();
        let mut hits: Vec<(&str, &str)> = Vec::new();
        for (phrase, repl) in PHRASES {
            if text.contains(phrase) {
                hits.push((phrase, repl));
            }
        }
        for m in word_split.find_iter(&text) {
            if let Some((w, repl)) = WORDS.iter().find(|(w, _)| *w == m.as_str()) {
                hits.push((w, repl));
            }
        }
        if hits.is_empty() {
            continue;
        }
        let mut seen: Vec<&str> = Vec::new();
        let mut shown = Vec::new();
        for (a, b) in &hits {
            if !seen.contains(a) {
                seen.push(a);
                shown.push(format!("'{a}' → {b}"));
            }
        }
        out.push(ste_finding(
            "STE03",
            c,
            format!("non-simple wording: {}", shown.join(", ")),
            "Use the simple form. STE style: one common word per meaning.",
            first_line(&c.content, 72),
        ));
    }
    out
}

pub fn long_paragraph(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let para = re(&PARA_RE, r"\n\s*\n");
    let mut out = Vec::new();
    for c in &sf.comments {
        if skip(c) {
            continue;
        }
        let text = prose(c);
        for p in para.split(&text) {
            // hard count: only real [.!?] sentences of flowing prose, so
            // clause splits and punctuated fragments cannot inflate it
            let n = sentences(p, false).len();
            if n > cfg.ste_max_paragraph_sentences {
                out.push(ste_finding(
                    "STE04",
                    c,
                    format!("paragraph has {n} sentences (STE limit: {})", cfg.ste_max_paragraph_sentences),
                    "Split the paragraph, or move this prose to documentation.",
                    first_line(&c.content, 72),
                ));
                break;
            }
        }
    }
    out
}

//! Small text helpers, ported from src/unwaffle/textutil.py: identifier
//! splitting, light stemming, word overlap, sentence segmentation.

use std::collections::HashSet;
use std::sync::OnceLock;

use regex::Regex;

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

static IDENT_RE: OnceLock<Regex> = OnceLock::new();
static WORD_RE: OnceLock<Regex> = OnceLock::new();

const STOPWORDS: &[&str] = &[
    "the", "a", "an", "of", "it", "its", "this", "that", "these", "those", "we", "you", "i",
    "is", "are", "be", "been", "being", "was", "were", "will", "shall", "should", "would",
    "could", "must", "can", "may", "might", "now", "then", "just", "simply", "also", "very",
    "to", "and", "or", "with", "by", "on", "in", "at", "as", "from", "into", "our", "their",
    "his", "her",
];

/// Very light stemmer: enough to match 'loops'~'loop', 'incrementing'~'increment'.
pub fn stem(word: &str) -> String {
    let mut w = word.to_lowercase();
    for suffix in ["ing", "ies", "ied", "es", "ed", "s"] {
        if w.ends_with(suffix) && w.len() - suffix.len() >= 3 {
            w.truncate(w.len() - suffix.len());
            if suffix == "ies" || suffix == "ied" {
                w.push('y');
            }
            // undouble 'running'->'runn'->'run', but keep call/pass/buzz
            let bytes = w.as_bytes();
            if matches!(suffix, "ing" | "ed")
                && w.len() >= 4
                && bytes[w.len() - 1] == bytes[w.len() - 2]
                && !matches!(bytes[w.len() - 1], b'l' | b's' | b'z')
            {
                w.truncate(w.len() - 1);
            }
            break;
        }
    }
    // normalize the mute 'e' so 'frobnicates'->'frobnicat' matches 'frobnicate'
    if w.ends_with('e') && w.len() >= 4 {
        w.truncate(w.len() - 1);
    }
    w
}

/// user_name -> [user, name]; getUserName -> [get, user, name]. Hand-rolled
/// camel tokenizer: the python pattern's "[A-Z]+(?![a-z])" lookahead (an
/// all-caps run donates its last capital to the next word, HTTPServer ->
/// HTTP + Server) has no direct regex-crate equivalent.
pub fn split_identifier(ident: &str) -> Vec<String> {
    let mut parts = Vec::new();
    for chunk in ident.split('_') {
        let b: Vec<char> = chunk.chars().collect();
        let mut i = 0;
        while i < b.len() {
            let c = b[i];
            if c.is_ascii_uppercase() {
                if b.get(i + 1).is_some_and(|n| n.is_ascii_lowercase()) {
                    let mut j = i + 1;
                    while j < b.len() && b[j].is_ascii_lowercase() {
                        j += 1;
                    }
                    parts.push(b[i..j].iter().collect::<String>().to_lowercase());
                    i = j;
                } else {
                    let mut j = i;
                    while j < b.len() && b[j].is_ascii_uppercase() {
                        j += 1;
                    }
                    if j < b.len() && b[j].is_ascii_lowercase() && j - i > 1 {
                        j -= 1;
                    }
                    parts.push(b[i..j].iter().collect::<String>().to_lowercase());
                    i = j;
                }
            } else if c.is_ascii_lowercase() {
                let mut j = i;
                while j < b.len() && b[j].is_ascii_lowercase() {
                    j += 1;
                }
                parts.push(b[i..j].iter().collect::<String>());
                i = j;
            } else {
                i += 1; // digits and stray bytes contribute no word
            }
        }
    }
    parts
}

// operators verbalized: "// increment the counter" restates "counter++" even
// though the operator contributes no identifier. Multi-char operators are
// checked before their single-char prefixes.
const OPERATOR_WORDS: &[(&str, &[&str])] = &[
    ("++", &["increment"]),
    ("--", &["decrement"]),
    ("+=", &["add", "increase"]),
    ("-=", &["subtract", "decrease"]),
    ("*=", &["multiply", "scale"]),
    ("/=", &["divide"]),
    ("==", &["equal", "check", "compare"]),
    ("!=", &["not", "equal", "differ"]),
    ("&&", &["and"]),
    ("||", &["or"]),
    ("=", &["set", "assign", "store"]),
    ("+", &["add", "plus", "sum"]),
    ("-", &["minus", "subtract"]),
    ("*", &["multiply", "times"]),
    ("/", &["divide"]),
    ("%", &["modulo", "remainder"]),
    ("<", &["less", "below", "compare"]),
    (">", &["greater", "above", "compare"]),
    ("!", &["not", "negate"]),
    ("(", &["call", "invoke"]),
];

/// Stemmed word set from a line of code: whole and split identifiers, plus
/// verbalized operators.
pub fn code_words(code: &str) -> HashSet<String> {
    let ident = re(&IDENT_RE, r"[A-Za-z_][A-Za-z0-9_]*");
    let mut words = HashSet::new();
    for m in ident.find_iter(code) {
        words.insert(stem(&m.as_str().to_lowercase()));
        for part in split_identifier(m.as_str()) {
            words.insert(stem(&part));
        }
    }
    let mut rest = code.to_string();
    for (op, verbal) in OPERATOR_WORDS {
        if rest.contains(op) {
            rest = rest.replace(op, " ");
            for w in *verbal {
                words.insert(stem(w));
            }
        }
    }
    words
}

/// Stemmed, stopword-filtered words from comment prose.
pub fn comment_words(text: &str) -> Vec<String> {
    let word = re(&WORD_RE, r"[A-Za-z]+");
    word.find_iter(text)
        .map(|m| m.as_str().to_lowercase())
        .filter(|w| !STOPWORDS.contains(&w.as_str()) && w.len() > 1)
        .map(|w| stem(&w))
        .collect()
}

/// Fraction of comment words that also appear in the code.
pub fn overlap_ratio(comment_text: &str, code: &str) -> f64 {
    let cwords = comment_words(comment_text);
    if cwords.is_empty() {
        return 0.0;
    }
    let kwords = code_words(code);
    let hits = cwords.iter().filter(|w| kwords.contains(*w)).count();
    hits as f64 / cwords.len() as f64
}

static TAG_LINE_RE: OnceLock<Regex> = OnceLock::new();
static LIST_LINE_RE: OnceLock<Regex> = OnceLock::new();
static CLAUSE_SPLIT_RE: OnceLock<Regex> = OnceLock::new();
static WS_RE: OnceLock<Regex> = OnceLock::new();

/// Split after any of `stops` when followed by whitespace — the lookbehind
/// split ("(?<=[.!?;])\s+") this regex engine cannot express.
fn split_after(text: &str, stops: &[char]) -> Vec<String> {
    let mut out = Vec::new();
    let mut start = 0;
    let chars: Vec<(usize, char)> = text.char_indices().collect();
    for i in 0..chars.len() {
        let (pos, ch) = chars[i];
        if stops.contains(&ch) && chars.get(i + 1).is_some_and(|(_, n)| n.is_whitespace()) {
            out.push(text[start..pos + ch.len_utf8()].to_string());
            let mut j = i + 1;
            while j < chars.len() && chars[j].1.is_whitespace() {
                j += 1;
            }
            start = chars.get(j).map_or(text.len(), |(p, _)| *p);
        }
    }
    if start < text.len() {
        out.push(text[start..].to_string());
    }
    out
}

/// Naive sentence splitter; good enough for comment prose. Doc-tag lines
/// (@param, \return) and list items each start their own segment. soft=true
/// (STE01's view) also splits at semicolons and spaced dash/arrow clauses;
/// soft=false (STE04's view) counts only [.!?]-terminated sentences of
/// flowing prose and skips tag/list structure entirely.
pub fn sentences(text: &str, soft: bool) -> Vec<String> {
    let tag = re(&TAG_LINE_RE, r"^\s*[@\\]\w+");
    let list = re(&LIST_LINE_RE, r"^\s*(?:[-*•]|\d+[.)])\s+");
    let clause = re(&CLAUSE_SPLIT_RE, r"\s+(?:—|–|--|->|=>|-)\s+");
    let ws = re(&WS_RE, r"\s+");

    let mut blocks: Vec<(bool, Vec<&str>)> = vec![(false, Vec::new())];
    for line in text.split('\n') {
        if tag.is_match(line) || list.is_match(line) {
            blocks.push((true, vec![line]));
        } else {
            blocks.last_mut().unwrap().1.push(line);
        }
    }
    let mut out = Vec::new();
    for (structured, lines) in blocks {
        if !soft && structured {
            continue;
        }
        let flat = ws.replace_all(&lines.join("\n"), " ").trim().to_string();
        if flat.is_empty() {
            continue;
        }
        if soft {
            for part in split_after(&flat, &['.', '!', '?', ';']) {
                for p in clause.split(&part) {
                    let p = p.trim();
                    if !p.is_empty() {
                        out.push(p.to_string());
                    }
                }
            }
        } else {
            for s in split_after(&flat, &['.', '!', '?']) {
                let s = s.trim();
                if !s.is_empty() {
                    out.push(s.to_string());
                }
            }
        }
    }
    out
}

pub fn first_line(text: &str, limit: usize) -> String {
    let line = text.split('\n').next().unwrap_or("");
    if line.chars().count() <= limit {
        line.to_string()
    } else {
        let cut: String = line.chars().take(limit - 1).collect();
        format!("{cut}…")
    }
}

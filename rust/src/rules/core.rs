//! Core rules UC001–UC012, ported from src/unwaffle/rules/core.py. The
//! reference patterns use lookarounds this regex engine lacks; each such
//! spot is rewritten as a positive pattern plus a hand check, verified by
//! the corpus contract and rust/parity.py --findings.

use std::sync::OnceLock;

use regex::Regex;

use crate::config::Config;
use crate::languages::is_interface_file;
use crate::model::{Attachment, Comment, Finding, Kind, Severity, SourceFile};
use crate::textutil::{first_line, overlap_ratio};

use super::{is_license_header, wording_text};

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

fn finding(rule: &'static str, severity: Severity, c: &Comment, message: String, action: &str) -> Finding {
    Finding {
        rule,
        severity,
        path: c.path.clone(),
        line: c.start_line,
        end_line: c.end_line,
        message,
        action: action.to_string(),
        excerpt: first_line(&c.content, 72),
    }
}

fn pct(ratio: f64) -> String {
    format!("{:.0}%", ratio * 100.0)
}

static WHY_RE: OnceLock<Regex> = OnceLock::new();
static TODO_RE: OnceLock<Regex> = OnceLock::new();

fn why_re() -> &'static Regex {
    re(&WHY_RE,
       r"(?i)\b(because|why|workaround|otherwise|avoid|caveat|warning|careful|invariant|must not|do not|don't|note:|nb:|safety|so that)\b|https?://")
}

fn todo_re() -> &'static Regex {
    re(&TODO_RE, r"(?i)\b(todo|fixme|hack|xxx)\b")
}

pub fn restates_code(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let mut out = Vec::new();
    for c in &sf.comments {
        if c.kind == Kind::Doc || !matches!(c.attachment, Attachment::Preceding | Attachment::Trailing) {
            continue;
        }
        if c.line_count() > 4 || c.word_count() < 2 || c.attached_code.is_empty() {
            continue;
        }
        if why_re().is_match(&c.content) || todo_re().is_match(&c.content) {
            continue;
        }
        let ratio = overlap_ratio(&c.content, &c.attached_code);
        if ratio >= cfg.restate_overlap {
            out.push(finding(
                "UC001",
                Severity::Warn,
                c,
                format!("comment repeats the adjacent code ({} of its words appear in the code)", pct(ratio)),
                "Delete this comment. The code already says this.",
            ));
        }
    }
    out
}

// narration "let's" always precedes a lowercase verb; a capitalized word
// after it is a product name. The python originals use lookaheads here; a
// boolean prefix match lets the consuming form stand in exactly.
const WE_PROCESS_VERBS: &str = "check|validate|call|return|create|build|iterate|loop|parse|convert|initialize|define|declare|handle|process|fetch|load|store|compute|calculate|run|emit|skip|apply|wrap|normalize|start|begin|make|try|add|remove|update|set|get";

static NARRATION_START_RE: OnceLock<Regex> = OnceLock::new();
static STEP_NUMBER_RE: OnceLock<Regex> = OnceLock::new();
static NARRATION_CONT_RE: OnceLock<Regex> = OnceLock::new();

fn narration_start() -> &'static Regex {
    static ONCE: OnceLock<String> = OnceLock::new();
    let pat = ONCE.get_or_init(|| {
        format!(
            r"(?i)^(now,? we |now that we |first,|first we |then |next,? we |finally,? we |finally, |lastly[,: ]|we (?:{WE_PROCESS_VERBS})\b|let'?s (?-i:[a-z])|here,? we |i |start by |begin by |the following |below,? we |step \d)"
        )
    });
    NARRATION_START_RE.get_or_init(|| Regex::new(pat).unwrap())
}

pub fn narration(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let step = re(&STEP_NUMBER_RE, r"^\d+[.)]\s+\w");
    let cont = re(&NARRATION_CONT_RE, r"(?i)^(now,? we |first,? we |then we |next,? we |finally,? we |step \d)");
    let mut out = Vec::new();
    for c in &sf.comments {
        // doc comments conventionally start with the symbol name, which
        // collides with narration openers — skip them
        if c.kind == Kind::Doc || is_license_header(c) {
            continue;
        }
        let text = wording_text(&c.content, cfg);
        // a WHY comment that happens to open with "We cannot… because…" is
        // the kind of comment this tool asks for — leave it alone
        if why_re().is_match(&text) {
            continue;
        }
        let mut lines = text.split('\n');
        let head = lines.next().unwrap_or("");
        let hit = narration_start().is_match(head)
            || (c.in_function && step.is_match(head))
            || lines.any(|line| cont.is_match(line) || (c.in_function && step.is_match(line)));
        if hit {
            out.push(finding(
                "UC002",
                Severity::Warn,
                c,
                "comment narrates the process ('now/first/we/step N…') instead of stating intent".to_string(),
                "Delete it, or rewrite as a short statement of WHY the code does this. Do not tell a story.",
            ));
        }
    }
    out
}

// UC003's opener tier: verb\b(?!NEG) pairs from the python source, split
// into a positive match plus a negated follow pattern.
static CH_V1: OnceLock<Regex> = OnceLock::new();
static CH_V1N: OnceLock<Regex> = OnceLock::new();
static CH_FIXED: OnceLock<Regex> = OnceLock::new();
static CH_FIXEDN: OnceLock<Regex> = OnceLock::new();
static CH_TRANS: OnceLock<Regex> = OnceLock::new();
static CH_NOW: OnceLock<Regex> = OnceLock::new();
static CH_PREFIX: OnceLock<Regex> = OnceLock::new();
static CHANGE_INNER_RE: OnceLock<Regex> = OnceLock::new();

fn change_start(head: &str) -> bool {
    let v1 = re(&CH_V1,
        r"(?i)^(?:added|updated|changed|modified|removed|renamed|refactored|replaced|moved|migrated|improved|enhanced|optimized|rewrote|corrected|simplified|reworked|adjusted|introduced|dropped|cleaned(?:\s+up)?)\b");
    let v1n = re(&CH_V1N,
        r"(?i)^(?:added|updated|changed|modified|removed|renamed|refactored|replaced|moved|migrated|improved|enhanced|optimized|rewrote|corrected|simplified|reworked|adjusted|introduced|dropped|cleaned(?:\s+up)?)[\s-]+(?:from|by|in|on|at|out|off|up|when|while|after|before|during|once|if|unless|point|size|width|length|number|amount|rate|capacity|cost|header|timestamp|to\s+(?:the|a|an))\b");
    // "fixed" doubles as a participial adjective ("Fixed input x output
    // grid"), so its branch spares a wider set of premodified nouns
    let vf = re(&CH_FIXED, r"(?i)^fixed\b");
    let vfn = re(&CH_FIXEDN,
        r"(?i)^fixed[\s-]+(?:from|by|in|on|at|when|while|after|before|point|size|width|length|number|amount|rate|capacity|cost|header|timestamp|input|output|order|grid|layout|shape|stride|scale|step|precision|format|frequency|interval|buffer|window|depth|budget|list|array|table|set|to\s+(?:the|a|an))\b");
    let trans = re(&CH_TRANS, r"(?i)^(?:switched|reverted|ported)\b");
    let now = re(&CH_NOW, r"(?i)^(?:now|this now)\s+(?:uses|calls|returns|relies|handles|supports|avoids|reads|writes|skips)\b");
    let pfx = re(&CH_PREFIX, r"(?i)^(?:new|change|edit|fix):");
    (v1.is_match(head) && !v1n.is_match(head))
        || (vf.is_match(head) && !vfn.is_match(head))
        || trans.is_match(head)
        || now.is_match(head)
        || pfx.is_match(head)
}

fn change_inner() -> &'static Regex {
    re(&CHANGE_INNER_RE,
        r"(?i)\b(as requested|as discussed|as per (the )?(instructions?|request)|per (the )?(user|reviewer|review|feedback)|in response to (the )?(review|feedback|request)|this (change|edit|update|commit|patch)|the (old|previous|original) (implementation|version)|(?:replace[sd]?|supersede[sd]?|rewrites?|rewrote|rewritten) the (old|previous|original) (code|logic)|no longer (uses|calls|requires|relies)|instead of the (old|previous)|was (removed|changed|renamed|moved) in)\b")
}

pub fn change_narration(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let mut out = Vec::new();
    for c in &sf.comments {
        if is_license_header(c) {
            continue;
        }
        let text = wording_text(&c.content, cfg);
        let head = text.split('\n').next().unwrap_or("");
        if change_inner().is_match(&text) {
            out.push(finding(
                "UC003",
                Severity::Error,
                c,
                "comment describes the edit, not the code ('as requested', 'the previous version'…)".to_string(),
                "Delete this comment. Edit history belongs in the commit message, not in the source.",
            ));
        } else if c.kind != Kind::Doc && change_start(head) {
            // doc comments open with the symbol name by convention — the
            // opener tier skips them
            out.push(finding(
                "UC003",
                Severity::Warn,
                c,
                "comment starts like edit narration ('changed/simplified/now uses…')".to_string(),
                "If this describes the edit, delete it; history belongs in the commit message. If it describes current behavior, reword in present tense ('Uses X because…').",
            ));
        }
    }
    out
}

static DECO_CHAR_RE: OnceLock<Regex> = OnceLock::new();
static BOX_BORDER_RE: OnceLock<Regex> = OnceLock::new();
static UNICODE_BOX_RE: OnceLock<Regex> = OnceLock::new();
static WS_ONLY_RE: OnceLock<Regex> = OnceLock::new();

fn deco_char() -> &'static Regex {
    re(&DECO_CHAR_RE, r"[-=*~_#/▬─-╿]")
}

/// ASCII tables and box diagrams share characters with banners but carry
/// real information — keep them.
fn is_diagram(content: &str) -> bool {
    let border = re(&BOX_BORDER_RE, r"^[+|][-+=| ]{6,}[+|]$");
    let unibox = re(&UNICODE_BOX_RE, r"^[┌└├╔╚╠].*[┐┘┤╗╝╣]$|[│║].*[│║]");
    content.split('\n').any(|line| {
        let s = line.trim();
        border.is_match(s) || unibox.is_match(s) || s.matches('|').count() >= 2
    })
}

/// Mostly decoration around a short label. The density guard keeps
/// slash-heavy prose (URLs, path lists) from reading as decoration.
fn banner_line(line: &str) -> bool {
    let ws = re(&WS_ONLY_RE, r"\s+");
    let solid = ws.replace_all(line, "").to_string();
    if solid.is_empty() {
        return false;
    }
    let deco = deco_char().find_iter(&solid).count();
    let total = solid.chars().count();
    if deco < 8 || (deco as f64) / (total as f64) < 0.5 {
        return false;
    }
    let label_words = line
        .split_whitespace()
        .filter(|w| !w.chars().all(|ch| deco_char().is_match(&ch.to_string())))
        .count();
    label_words <= 3
}

pub fn banner(sf: &SourceFile, _cfg: &Config) -> Vec<Finding> {
    let mut out = Vec::new();
    for c in &sf.comments {
        if is_license_header(c) || is_diagram(&c.content) {
            continue;
        }
        if c.content.split('\n').any(banner_line) {
            out.push(finding(
                "UC004",
                Severity::Warn,
                c,
                "decorative banner/divider comment".to_string(),
                "Delete the banner. If the file needs sections, split it into smaller files or functions.",
            ));
        }
    }
    out
}

// ---- UC005 code-ish detection ----

static SC_TERM: OnceLock<Regex> = OnceLock::new();
static SC_BRACE: OnceLock<Regex> = OnceLock::new();
static SC_KW: OnceLock<Regex> = OnceLock::new();
static SC_PREPROC: OnceLock<Regex> = OnceLock::new();
static SC_CALL: OnceLock<Regex> = OnceLock::new();
static SC_ASSIGN_CALL: OnceLock<Regex> = OnceLock::new();
static SC_ASSIGN_CALL_NEG: OnceLock<Regex> = OnceLock::new();
static SC_ARROW: OnceLock<Regex> = OnceLock::new();
static SC_RETURN: OnceLock<Regex> = OnceLock::new();
static SC_FLOW: OnceLock<Regex> = OnceLock::new();
static SC_IMPORT: OnceLock<Regex> = OnceLock::new();
static SC_DECORATOR: OnceLock<Regex> = OnceLock::new();
static WEAK_ASSIGN: OnceLock<Regex> = OnceLock::new();
static BRACE_GLOSS_RE: OnceLock<Regex> = OnceLock::new();
static ENUM_GLOSS_RE: OnceLock<Regex> = OnceLock::new();
static PLAIN_WORD_RE: OnceLock<Regex> = OnceLock::new();
static PROSE_ASSIGN_RE: OnceLock<Regex> = OnceLock::new();

/// A '=' that is assignment, not part of ==, !=, <=, >= — the python
/// pattern's lookbehind/lookahead pair, scanned by hand.
fn has_plain_assign(s: &str) -> bool {
    let b: Vec<char> = s.chars().collect();
    for i in 0..b.len() {
        if b[i] == '='
            && !(i > 0 && matches!(b[i - 1], '!' | '<' | '>' | '='))
            && b.get(i + 1) != Some(&'=')
        {
            return true;
        }
    }
    false
}

fn strong_codeish(line: &str) -> bool {
    let term = re(&SC_TERM, r"[;{}]\s*$");
    let brace = re(&SC_BRACE, r"^\s*[{}]\s*$");
    // a keyword line is code only with real clause syntax: a brace, an
    // immediate paren, a plain assignment, or a python-style trailing colon
    let kw = re(&SC_KW,
        r"^\s*(if|elif|for|while|switch|return|import|export|let|const|var|val|fn|func|def|pub|static|struct|class|case|else|try|catch|except|finally|with|raise|yield|assert)\b");
    let preproc = re(&SC_PREPROC, r"^\s*#\s*(include|define|if|ifdef|ifndef|endif|pragma)\b");
    // calls, incl. chained; the paren must follow the callee DIRECTLY
    let call = re(&SC_CALL, r"^\s*[\w.\[\]:>*&-]+\(.*\)\s*;?\s*$");
    let assign_call = re(&SC_ASSIGN_CALL, r"^\s*[\w.\[\]]+\s*:?=\s*[\w.\[\]]+\(.*\)\s*;?\s*$");
    // the python original guards with (?!.*,\s*\w+=) so a key=value comma
    // list cannot read as an assignment-to-call
    let assign_call_neg = re(&SC_ASSIGN_CALL_NEG, r",\s*\w+=");
    let arrow = re(&SC_ARROW, r"\w->\w|\)\s*\{");
    let ret = re(&SC_RETURN, r#"^\s*return\s+[\w.\[\]()"']+\s*;?\s*$"#);
    let flow = re(&SC_FLOW, r"^\s*(break|continue|pass)\s*;?\s*$");
    let import = re(&SC_IMPORT, r"^\s*(import\s+[\w.]+(\s+as\s+\w+)?|from\s+[\w.]+\s+import\s+[\w.*,() ]+)\s*$");
    let deco = re(&SC_DECORATOR, r"^\s*@\w[\w.]*(\(.*\))?\s*$");

    if term.is_match(line) || brace.is_match(line) || preproc.is_match(line) || call.is_match(line) {
        return true;
    }
    if let Some(m) = kw.find(line) {
        let rest = &line[m.end()..];
        if rest.contains('{')
            || rest.contains('(')
            || has_plain_assign(rest)
            || Regex::new(r":\s*$").unwrap().is_match(rest)
        {
            return true;
        }
    }
    if assign_call.is_match(line) && !assign_call_neg.is_match(line) {
        return true;
    }
    arrow.is_match(line) || ret.is_match(line) || flow.is_match(line) || import.is_match(line) || deco.is_match(line)
}

fn prose_tail_assign(line: &str) -> bool {
    // 'LRCLK = BCK+1 in both).' — an assignment that trails off into prose
    let stripped = line.trim_end();
    if !stripped.ends_with('.') || stripped.ends_with("..") || !stripped.contains('=') {
        return false;
    }
    let plain = re(&PLAIN_WORD_RE, r"\b[a-z]{2,}\b");
    let after = stripped.split_once('=').map(|(_, r)| r).unwrap_or("");
    plain.find_iter(after).count() >= 2
}

pub fn looks_like_code(line: &str, strong_only: bool) -> bool {
    if line.trim().is_empty() {
        return false;
    }
    let prose_assign = re(&PROSE_ASSIGN_RE, r"^\s*\w+\s*=\s*[A-Za-z]+(\s+[A-Za-z]+){2,}\s*[.;]?\s*$");
    let brace_gloss = re(&BRACE_GLOSS_RE, r"^\{[^;{}=]*\}$");
    let enum_gloss = re(&ENUM_GLOSS_RE, r"^\s*[\w.\[\]]+\s*=\s*[A-Z][A-Z0-9_]*\(\d+\)\s*$");
    if prose_assign.is_match(line)
        || brace_gloss.is_match(line.trim())
        || enum_gloss.is_match(line)
        || prose_tail_assign(line)
    {
        return false;
    }
    if strong_codeish(line) {
        return true;
    }
    if !strong_only {
        // a bare assignment shape also appears in legends, so on its own it
        // only counts inside a multi-line block
        let weak = re(&WEAK_ASSIGN, r"^\s*[A-Za-z_][\w.\[\]]*\s*[-+*/|&^:]?=\s*[^=]");
        return weak.is_match(line);
    }
    false
}

pub fn commented_out_code(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let mut out = Vec::new();
    for c in &sf.comments {
        if c.kind == Kind::Doc {
            continue;
        }
        let lines: Vec<&str> = c.content.split('\n').filter(|l| !l.trim().is_empty()).collect();
        if lines.is_empty() {
            continue;
        }
        // sentence-wrapped prose: when the previous line ends mid-sentence,
        // this line's code-ish shape is an accident of wrapping
        let codeish = lines
            .iter()
            .enumerate()
            .filter(|(i, ln)| {
                looks_like_code(ln, false)
                    && !(*i > 0
                        && !lines[i - 1]
                            .trim_end()
                            .ends_with(['.', ';', ':', '!', '?', '{', '}', ')']))
            })
            .count();
        // a one-line formula that mirrors the adjacent code is a restatement
        // — UC001's finding, not dead code
        let single_restates = lines.len() == 1
            && !c.attached_code.is_empty()
            && overlap_ratio(&c.content, &c.attached_code) >= cfg.restate_overlap;
        let multi = lines.len() >= 2
            && codeish as f64 / lines.len() as f64 >= cfg.code_line_fraction
            && codeish >= 2;
        let single = lines.len() == 1
            && looks_like_code(lines[0], true)
            && !todo_re().is_match(lines[0])
            && !single_restates;
        if multi || single {
            out.push(finding(
                "UC005",
                Severity::Warn,
                c,
                format!("commented-out code ({codeish} of {} lines look like code)", lines.len()),
                "Delete it. Version control preserves removed code; dead code in comments rots.",
            ));
        }
    }
    out
}

pub fn function_density(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    if sf.functions.is_empty() {
        return Vec::new();
    }
    // attribute each interior comment to its innermost enclosing function once
    let mut comment_lines_of = vec![0usize; sf.functions.len()];
    for c in &sf.comments {
        if !c.in_function {
            continue;
        }
        let mut best: Option<usize> = None;
        let mut best_size = usize::MAX;
        for (idx, f) in sf.functions.iter().enumerate() {
            let size = f.end_line - f.start_line;
            if f.start_line < c.start_line && c.start_line <= f.end_line && size < best_size {
                best = Some(idx);
                best_size = size;
            }
        }
        if let Some(idx) = best {
            comment_lines_of[idx] += c.line_count();
        }
    }
    let mut out = Vec::new();
    for (idx, f) in sf.functions.iter().enumerate() {
        let comment_lines = comment_lines_of[idx];
        if comment_lines >= cfg.min_interior_comment_lines
            && f.body_line_count > 0
            && comment_lines as f64 / f.body_line_count as f64 > cfg.max_function_comment_ratio
        {
            out.push(Finding {
                rule: "UC006",
                severity: Severity::Warn,
                path: sf.path.clone(),
                line: f.start_line,
                end_line: f.end_line,
                message: format!(
                    "function '{}' has {comment_lines} comment lines in a {}-line body ({})",
                    f.name,
                    f.body_line_count,
                    pct(comment_lines as f64 / f.body_line_count as f64)
                ),
                action: "Strip the play-by-play comments from this function. Keep at most a short WHY note per non-obvious block; if the logic needs this much explanation, simplify or split it.".to_string(),
                excerpt: String::new(),
            });
        }
    }
    out
}

static DOC_TAG_RE: OnceLock<Regex> = OnceLock::new();

fn doc_tag() -> &'static Regex {
    re(&DOC_TAG_RE,
        r"(?i)[@\\](t?param|returns?|retval|throws?|arg|brief|details|note|warning|see|sa|since|ingroup|defgroup|addtogroup|copydoc|deprecated|exception|pre|post|file|invariant)\b|Args:|Returns:|Raises:|# Arguments|# Errors|# Panics|# Safety|# Examples|-\s+(Parameters?|Returns?|Throws|Note|Warning|Important|Precondition)s?:|</?(summary|param|returns|remarks|exception)\b")
}

pub fn redundant_doc(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let mut out = Vec::new();
    for c in &sf.comments {
        if c.kind != Kind::Doc || c.attachment != Attachment::Preceding || c.attached_code.is_empty() {
            continue;
        }
        if c.line_count() > 3 || doc_tag().is_match(&c.content) {
            continue;
        }
        // an enum case's doc necessarily mirrors its name, and ecosystem lint
        // REQUIRES the doc to exist
        if c.attached_code.trim_start().starts_with("case ") {
            continue;
        }
        let ratio = overlap_ratio(&c.content, &c.attached_code);
        if ratio >= cfg.redundant_doc_overlap && c.word_count() >= 2 {
            out.push(finding(
                "UC007",
                Severity::Warn,
                c,
                format!("doc comment restates the symbol name ({} word overlap)", pct(ratio)),
                "Delete it, or make it say something the signature cannot: units, invariants, error behavior, ownership.",
            ));
        }
    }
    out
}

static SECTION_RE: OnceLock<Regex> = OnceLock::new();

pub fn doc_migration(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let section = re(&SECTION_RE,
        r"(?im)^#+\s|\b(example|usage|architecture|overview|background|design|rationale|how it works|implementation notes?|history|tutorial)\b\s*:?");
    let mut out = Vec::new();
    for c in &sf.comments {
        if is_license_header(c) {
            continue;
        }
        if c.in_function && c.line_count() >= 6 {
            out.push(finding(
                "UC008",
                Severity::Info,
                c,
                format!("{}-line essay inside function '{}'", c.line_count(), c.function_name),
                "Move this to the function's doc comment or to project docs; keep at most one WHY line here.",
            ));
            continue;
        }
        if c.line_count() < cfg.doc_migration_lines {
            continue;
        }
        if c.attachment == Attachment::FileHeader && c.kind == Kind::Doc {
            // module/package docs are a legitimate home for long
            // documentation — that IS the docs
            continue;
        }
        if c.attachment == Attachment::FileHeader {
            out.push(finding(
                "UC008",
                Severity::Info,
                c,
                format!("{}-line file header essay", c.line_count()),
                "Move guide-level content to README/docs or the module doc; keep a one-paragraph summary here.",
            ));
        } else if c.kind == Kind::Doc {
            // interface files exist to carry API docs — never suggest moving
            // documentation out of them
            if is_interface_file(&sf.path) {
                continue;
            }
            // a structured doc is documentation in its right place unless it
            // grows into a book
            if doc_tag().is_match(&c.content) && c.line_count() < 2 * cfg.doc_migration_lines {
                continue;
            }
            if section.is_match(&c.content) || c.line_count() >= 2 * cfg.doc_migration_lines {
                out.push(finding(
                    "UC008",
                    Severity::Info,
                    c,
                    format!("{}-line doc comment with guide-level sections", c.line_count()),
                    "Keep the API summary and parameter docs here; move tutorial/architecture prose to project docs.",
                ));
            }
        } else {
            out.push(finding(
                "UC008",
                Severity::Info,
                c,
                format!("{}-line comment block", c.line_count()),
                "If this documents the API, make it a doc comment; if it is guide-level prose, move it to project docs.",
            ));
        }
    }
    out
}

static TRAILING_URL_RE: OnceLock<Regex> = OnceLock::new();

pub fn trailing_length(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let url = re(&TRAILING_URL_RE, r"https?://\S+");
    let mut out = Vec::new();
    for c in &sf.comments {
        if c.attachment != Attachment::Trailing {
            continue;
        }
        // measure collapsed text, without URLs, so column alignment padding
        // and citation links do not spend the brevity budget
        let cleaned = url.replace_all(&c.text, "");
        let collapsed = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
        let chars = collapsed.chars().count();
        let mut over = Vec::new();
        if chars > cfg.max_trailing_chars {
            over.push(format!("{chars} chars (limit {})", cfg.max_trailing_chars));
        }
        if c.word_count() > cfg.max_trailing_words {
            over.push(format!("{} words (limit {})", c.word_count(), cfg.max_trailing_words));
        }
        if !over.is_empty() {
            out.push(finding(
                "UC009",
                Severity::Warn,
                c,
                format!("trailing comment is too long: {}", over.join(", ")),
                "Delete it if it repeats the code; otherwise move it to its own line above, shortened.",
            ));
        }
    }
    out
}

static BOILERPLATE_RE: OnceLock<Regex> = OnceLock::new();

pub fn boilerplate_label(sf: &SourceFile, _cfg: &Config) -> Vec<Finding> {
    let boiler = re(&BOILERPLATE_RE,
        r"(?i)^(imports?|includes?|usings?|variables?|globals?|constants?|fields?|members?|types?|(private|public|protected|static)\s+(methods?|members?|fields?|functions?)|helpers?|helper functions?|utility functions?|utils?|main( function| entry point)?|constructors?|destructors?|getters?( and setters?)?|setters?|accessors?|initialization|init|cleanup|setup|teardown|declarations?|definitions?|implementation|entry point|event handlers?|callbacks?|properties|state|misc(ellaneous)?|other|end of .{0,40}|done)[.:]?$");
    let mut out = Vec::new();
    for c in &sf.comments {
        if c.kind == Kind::Doc || c.line_count() > 1 {
            continue;
        }
        if boiler.is_match(c.content.trim()) {
            out.push(finding(
                "UC010",
                Severity::Warn,
                c,
                "label comment states the obvious".to_string(),
                "Delete it. Readers can see what imports/helpers/loops are; structure should come from code, not labels.",
            ));
        }
    }
    out
}

static TODO_REF_RE: OnceLock<Regex> = OnceLock::new();

pub fn unowned_todo(sf: &SourceFile, _cfg: &Config) -> Vec<Finding> {
    let todo_ref = re(&TODO_REF_RE, r"\(\s*\w+\s*\)|#\d+|\b[A-Z][A-Z0-9]+-\d+\b|https?://");
    let mut out = Vec::new();
    for c in &sf.comments {
        if let Some(m) = todo_re().find(&c.content) {
            if !todo_ref.is_match(&c.content) {
                out.push(finding(
                    "UC011",
                    Severity::Info,
                    c,
                    format!("{} has no owner or ticket", m.as_str().to_uppercase()),
                    "Add an owner or issue reference (TODO(name), #123), file a ticket, or remove it.",
                ));
            }
        }
    }
    out
}

// emoji, pictographs, dingbats, decorative symbols — not general typography
static EMOJI_RE: OnceLock<Regex> = OnceLock::new();
static NON_ASCII_RE: OnceLock<Regex> = OnceLock::new();

pub fn emoji_comment(sf: &SourceFile, cfg: &Config) -> Vec<Finding> {
    let emoji = re(&EMOJI_RE,
        "[\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}\u{1F000}-\u{1FAFF}\u{1FB00}-\u{1FBFF}]");
    let non_ascii = re(&NON_ASCII_RE, r"[^\x00-\x7f]");
    let (rx, what) = if cfg.ascii_comments {
        (non_ascii, "non-ASCII characters")
    } else {
        (emoji, "emoji/decorative symbols")
    };
    let mut out = Vec::new();
    for c in &sf.comments {
        if is_license_header(c) {
            continue;
        }
        let found: Vec<char> = rx.find_iter(&c.content).filter_map(|m| m.as_str().chars().next()).collect();
        if found.is_empty() {
            continue;
        }
        let mut seen = Vec::new();
        for ch in &found {
            if !seen.contains(ch) && !ch.is_control() {
                seen.push(*ch);
            }
        }
        let unique: String = seen.into_iter().take(8).collect();
        let shown = if unique.is_empty() {
            let mut codes = Vec::new();
            for ch in &found {
                let code = format!("U+{:04X}", *ch as u32);
                if !codes.contains(&code) {
                    codes.push(code);
                }
            }
            codes.join(" ").chars().take(40).collect()
        } else {
            unique
        };
        out.push(finding(
            "UC012",
            Severity::Warn,
            c,
            format!("comment contains {what}: {shown}"),
            "Remove the decoration. Comments read best as plain text; symbols add no information.",
        ));
    }
    out
}

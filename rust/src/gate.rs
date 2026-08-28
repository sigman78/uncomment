//! Gate mode, ported from src/unwaffle/gate.py: judge only comments that
//! are NEW relative to a baseline. Matching runs in stages so ordinary
//! edits are not re-judged: per-file exact, cross-file exact, baseline
//! tree sweep (renames), then fuzzy. Diff-input mode (diffio) and verify
//! follow in the next slice.

use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

use crate::config::Config;
use crate::extract::{extract_path, extract_source};
use crate::filtering::{is_generated, selected};
use crate::languages::spec_for_path;
use crate::model::{Comment, Finding, Kind, Severity, SourceFile};
use crate::rules::{
    file_suppressed_rules, file_wide_rules, is_license_header, marker_line_count, run_rules,
    visible_comments,
};
use crate::similarity::SequenceMatcher;

#[derive(Debug, Default)]
pub struct GateResult {
    pub findings: Vec<Finding>,
    pub files_scanned: usize,
    pub files_skipped: usize,
    pub new_comments: usize,
    pub new_comment_lines: usize,
    pub added_code_lines: usize,
}

#[derive(Debug)]
pub struct GateError(pub String);

type Counter = HashMap<String, i64>;

fn norm(c: &Comment) -> String {
    c.content.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

fn similar(a: &str, b: &str, threshold: f64) -> bool {
    if a.is_empty() || b.is_empty() {
        return false;
    }
    let (la, lb) = (a.chars().count() as f64, b.chars().count() as f64);
    if la.min(lb) / la.max(lb) < 0.5 {
        return false;
    }
    let sm = SequenceMatcher::new(a, b);
    if sm.real_quick_ratio() < threshold || sm.quick_ratio() < threshold {
        return false;
    }
    sm.ratio() >= threshold
}

fn consume_exact(comments: Vec<Comment>, pool: &mut Counter) -> Vec<Comment> {
    let mut leftover = Vec::new();
    for c in comments {
        let key = norm(&c);
        let n = pool.entry(key).or_insert(0);
        if *n > 0 {
            *n -= 1;
        } else {
            leftover.push(c);
        }
    }
    leftover
}

fn consume_fuzzy(comments: Vec<Comment>, pool: &mut Counter, threshold: f64) -> Vec<Comment> {
    let mut leftover = Vec::new();
    for c in comments {
        let key = norm(&c);
        let hit = pool
            .iter()
            .find(|(old, n)| **n > 0 && similar(&key, old, threshold))
            .map(|(old, _)| old.clone());
        match hit {
            Some(old) => *pool.get_mut(&old).unwrap() -= 1,
            None => leftover.push(c),
        }
    }
    leftover
}

/// Comments that are neither documentation nor license text — the kind an
/// over-eager agent multiplies.
fn prose_comments<'c>(comments: &'c [Comment]) -> Vec<&'c Comment> {
    comments.iter().filter(|c| c.kind != Kind::Doc && !is_license_header(c)).collect()
}

fn prose_lines(comments: &[Comment]) -> usize {
    prose_comments(comments).iter().map(|c| c.line_count() - marker_line_count(c)).sum()
}

struct FileState {
    display: PathBuf,
    sf: SourceFile,
    unmatched: Vec<Comment>,
    added_code_lines: usize,
    had_counterpart: bool,
    old_prose_lines: usize,
    new_prose_lines: usize,
    old_file_wide: Vec<String>,
}

pub trait Baseline {
    /// (old source, identity) — identity marks the baseline file consumed
    /// even when the read succeeds or fails.
    fn source_for(&mut self, new_path: &Path, new_root: &Path) -> (Option<String>, Option<String>);
    fn tree_files(&mut self, anchor: &Path, consumed: &HashSet<String>, cfg: &Config) -> Vec<(String, String)>;
}

pub struct PathBaseline {
    base: PathBuf,
}

impl PathBaseline {
    pub fn new(base: &str) -> Self {
        PathBaseline { base: PathBuf::from(base) }
    }
}

fn resolve(p: &Path) -> PathBuf {
    p.canonicalize().unwrap_or_else(|_| p.to_path_buf())
}

impl Baseline for PathBaseline {
    fn source_for(&mut self, new_path: &Path, new_root: &Path) -> (Option<String>, Option<String>) {
        let candidate = if self.base.is_file() {
            self.base.clone()
        } else {
            let rel = resolve(new_path)
                .strip_prefix(resolve(new_root))
                .map(|r| r.to_path_buf())
                .unwrap_or_else(|_| PathBuf::from(new_path.file_name().unwrap_or_default()));
            self.base.join(rel)
        };
        let identity = resolve(&candidate).to_string_lossy().to_string();
        match std::fs::read_to_string(&candidate) {
            Ok(text) if candidate.is_file() => (Some(text), Some(identity)),
            _ => (None, Some(identity)),
        }
    }

    fn tree_files(&mut self, _anchor: &Path, consumed: &HashSet<String>, cfg: &Config) -> Vec<(String, String)> {
        let mut out = Vec::new();
        if !self.base.is_dir() {
            return out;
        }
        let mut stack = vec![self.base.clone()];
        let mut files = Vec::new();
        while let Some(dir) = stack.pop() {
            let Ok(entries) = std::fs::read_dir(&dir) else { continue };
            for e in entries.filter_map(Result::ok) {
                let p = e.path();
                if p.is_dir() {
                    stack.push(p);
                } else {
                    files.push(p);
                }
            }
        }
        files.sort();
        for p in files {
            if spec_for_path(&p.to_string_lossy()).is_none()
                || consumed.contains(&resolve(&p).to_string_lossy().to_string())
            {
                continue;
            }
            let rel = p
                .strip_prefix(&self.base)
                .map(|r| r.to_string_lossy().replace('\\', "/"))
                .unwrap_or_default();
            if !selected(&rel, cfg) {
                continue;
            }
            if let Ok(text) = std::fs::read_to_string(&p) {
                out.push((p.to_string_lossy().to_string(), text));
            }
        }
        out
    }
}

/// One persistent `git cat-file --batch` process per repository top. A dead
/// process is a hard error upstream, never a silent 'everything is new'.
struct CatFileBatch {
    proc: Child,
}

impl CatFileBatch {
    fn new(top: &Path) -> Result<Self, GateError> {
        let proc = Command::new("git")
            .args(["cat-file", "--batch"])
            .current_dir(top)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| GateError(format!("git executable not found: {e}")))?;
        Ok(CatFileBatch { proc })
    }

    fn read(&mut self, spec: &str) -> Result<Option<Vec<u8>>, GateError> {
        let dead = || GateError(format!("git cat-file exited unexpectedly while reading '{spec}'"));
        let stdin = self.proc.stdin.as_mut().ok_or_else(dead)?;
        writeln!(stdin, "{spec}").map_err(|_| dead())?;
        stdin.flush().map_err(|_| dead())?;
        let stdout = self.proc.stdout.as_mut().ok_or_else(dead)?;
        let mut reader = BufReader::new(stdout);
        let mut header = String::new();
        reader.read_line(&mut header).map_err(|_| dead())?;
        if header.is_empty() {
            return Err(dead());
        }
        let parts: Vec<&str> = header.split_whitespace().collect();
        if parts.len() != 3 || parts[2].parse::<usize>().is_err() {
            return Ok(None); // "<spec> missing" (or ambiguous/dangling)
        }
        let size: usize = parts[2].parse().unwrap();
        let mut data = vec![0u8; size + 1]; // payload + trailing LF
        reader.read_exact(&mut data).map_err(|_| dead())?;
        data.truncate(size);
        if parts[1] == "blob" {
            Ok(Some(data))
        } else {
            Ok(None)
        }
    }
}

impl Drop for CatFileBatch {
    fn drop(&mut self) {
        let _ = self.proc.kill();
        let _ = self.proc.wait();
    }
}

pub fn git_repo_top(anchor_dir: &Path) -> Option<PathBuf> {
    let out = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(anchor_dir)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let top = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if top.is_empty() {
        None
    } else {
        Some(PathBuf::from(top))
    }
}

pub struct GitBaseline {
    reference: String,
    batches: HashMap<PathBuf, CatFileBatch>,
}

impl GitBaseline {
    pub fn new(reference: &str) -> Self {
        let reference = if reference.is_empty() { "HEAD" } else { reference };
        GitBaseline { reference: reference.to_string(), batches: HashMap::new() }
    }

    fn batch(&mut self, top: &Path) -> Result<&mut CatFileBatch, GateError> {
        if !self.batches.contains_key(top) {
            self.batches.insert(top.to_path_buf(), CatFileBatch::new(top)?);
        }
        Ok(self.batches.get_mut(top).unwrap())
    }
}

fn rel_to(path: &Path, top: &Path) -> Option<String> {
    resolve(path)
        .strip_prefix(resolve(top))
        .ok()
        .map(|r| r.to_string_lossy().replace('\\', "/"))
}

impl Baseline for GitBaseline {
    fn source_for(&mut self, new_path: &Path, _new_root: &Path) -> (Option<String>, Option<String>) {
        let Some(parent) = new_path.parent() else { return (None, None) };
        let anchor = if parent.as_os_str().is_empty() { Path::new(".") } else { parent };
        let Some(top) = git_repo_top(anchor) else { return (None, None) };
        let Some(rel) = rel_to(new_path, &top) else { return (None, None) };
        let reference = self.reference.clone();
        match self.batch(&top).and_then(|b| b.read(&format!("{reference}:{rel}"))) {
            Ok(Some(data)) => {
                let text = String::from_utf8_lossy(&data).to_string();
                let text = text.strip_prefix('\u{feff}').unwrap_or(&text).to_string();
                (Some(text), Some(rel))
            }
            _ => (None, Some(rel)),
        }
    }

    fn tree_files(&mut self, anchor: &Path, consumed: &HashSet<String>, cfg: &Config) -> Vec<(String, String)> {
        let anchor_dir = if anchor.is_dir() { anchor.to_path_buf() } else { anchor.parent().unwrap_or(Path::new(".")).to_path_buf() };
        let Some(top) = git_repo_top(&anchor_dir) else { return Vec::new() };
        let Ok(listing) = Command::new("git")
            .args(["ls-tree", "-r", "--name-only", &self.reference])
            .current_dir(&top)
            .output()
        else {
            return Vec::new();
        };
        if !listing.status.success() {
            return Vec::new();
        }
        let names = String::from_utf8_lossy(&listing.stdout).to_string();
        let reference = self.reference.clone();
        let mut out = Vec::new();
        for rel in names.lines() {
            if consumed.contains(rel) || spec_for_path(rel).is_none() || !selected(rel, cfg) {
                continue;
            }
            if let Ok(Some(data)) = self.batch(&top).and_then(|b| b.read(&format!("{reference}:{rel}"))) {
                let text = String::from_utf8_lossy(&data).to_string();
                out.push((rel.to_string(), text.strip_prefix('\u{feff}').unwrap_or(&text).to_string()));
            }
        }
        out
    }
}

pub fn provider_for(baseline: &str) -> Box<dyn Baseline> {
    if let Some(reference) = baseline.strip_prefix("git:") {
        Box::new(GitBaseline::new(reference))
    } else {
        Box::new(PathBaseline::new(baseline))
    }
}

/// Comment norms from baseline files that were not per-file counterparts —
/// loaded only when a scanned file lacks a counterpart (rename/new file).
fn tree_norms(provider: &mut dyn Baseline, anchor: &Path, consumed: &HashSet<String>, cfg: &Config) -> Counter {
    let mut pool = Counter::new();
    for (label, text) in provider.tree_files(anchor, consumed, cfg) {
        let Some((spec, _)) = spec_for_path(&label) else { continue };
        let sf = extract_source(&label, &text, spec);
        for c in visible_comments(&sf, cfg) {
            *pool.entry(norm(&c)).or_insert(0) += 1;
        }
    }
    pool
}

fn finalize(st: &FileState, cfg: &Config) -> Vec<Finding> {
    let new_spans: Vec<(usize, usize)> = st.unmatched.iter().map(|c| (c.start_line, c.end_line)).collect();
    let touches_new =
        |f: &Finding| new_spans.iter().any(|(a, b)| !(*b < f.line || *a > f.end_line));

    let mut findings: Vec<Finding> =
        run_rules(&st.sf, cfg).into_iter().filter(touches_new).collect();
    // per-comment findings only; UC100's noise measure must not count the
    // aggregate UC101 signal below
    let rule_findings = findings.clone();

    let file_sups = file_suppressed_rules(&st.sf);
    let path_str = st.display.to_string_lossy().to_string();

    // UC101 comment amplification: fires on NET growth of the file's prose
    // volume, so an in-place rewrite is not amplification — only a file
    // whose prose actually multiplied is
    let net_growth = st.new_prose_lines as i64 - st.old_prose_lines as i64;
    let prose: Vec<&Comment> = prose_comments(&st.unmatched);
    if !file_sups.iter().any(|r| r == "UC101")
        && st.had_counterpart
        && st.old_prose_lines > 0
        && !prose.is_empty()
        && net_growth >= cfg.growth_min_lines as i64
        && net_growth as f64 >= cfg.growth_factor * st.old_prose_lines as f64
    {
        findings.push(Finding {
            rule: "UC101",
            severity: Severity::Warn,
            path: path_str.clone(),
            line: prose[0].start_line,
            end_line: prose[prose.len() - 1].end_line,
            message: format!(
                "comment amplification: prose comments grew from {} to {} lines",
                st.old_prose_lines, st.new_prose_lines
            ),
            action: "This edit multiplied the file's comments. Existing comments are not an invitation to add more: re-read every comment you added and keep only those stating a WHY the code cannot express. Delete elaborations, restatements, and section labels.".to_string(),
            excerpt: String::new(),
        });
    }

    // flood counts only noisy lines: new NON-DOC comments with at least one
    // warn/error finding
    let gating: Vec<&Finding> = rule_findings.iter().filter(|f| f.severity >= Severity::Warn).collect();
    let is_noisy = |c: &Comment| {
        c.kind != Kind::Doc && gating.iter().any(|f| !(c.end_line < f.line || c.start_line > f.end_line))
    };
    let noisy: Vec<&Comment> = st.unmatched.iter().filter(|c| is_noisy(c)).collect();
    let noisy_lines: usize = noisy.iter().map(|c| c.line_count()).sum();
    if !file_sups.iter().any(|r| r == "UC100")
        && noisy_lines >= cfg.flood_min_lines
        && noisy_lines as f64 > cfg.flood_ratio * st.added_code_lines.max(1) as f64
    {
        findings.push(Finding {
            rule: "UC100",
            severity: Severity::Error,
            path: path_str.clone(),
            line: noisy[0].start_line,
            end_line: noisy[noisy.len() - 1].end_line,
            message: format!(
                "comment flood: {noisy_lines} noisy new comment lines vs {} new code lines",
                st.added_code_lines
            ),
            action: "This edit added far more comment noise than code. Re-read every new comment and delete those that restate code, narrate the process, or describe the edit. Keep only WHY notes.".to_string(),
            excerpt: String::new(),
        });
    }

    // a NEW file-wide exception is itself worth a look: the escape hatch
    // stays open, but an edit granting one announces it to the reviewer
    if !file_sups.iter().any(|r| r == "UC102") {
        let mut granted: Vec<String> = file_wide_rules(&st.sf)
            .into_iter()
            .filter(|r| !st.old_file_wide.contains(r))
            .collect();
        granted.sort();
        granted.dedup();
        for rid in granted {
            let marker = st.sf.comments.iter().find(|c| {
                c.content.match_indices("unwaffle-ignore-file[").any(|(idx, _)| {
                    let rest = &c.content[idx + "unwaffle-ignore-file[".len()..];
                    rest.find(']').is_some_and(|end| rest[..end].contains(&rid))
                })
            });
            let Some(marker) = marker else { continue };
            findings.push(Finding {
                rule: "UC102",
                severity: Severity::Info,
                path: path_str.clone(),
                line: marker.start_line,
                end_line: marker.end_line,
                message: format!("edit grants this file a file-wide exception for {rid}"),
                action: "Confirm the marker's reason justifies a whole-file exception; prefer span markers when only specific comments need it.".to_string(),
                excerpt: marker.content.split('\n').next().unwrap_or("").to_string(),
            });
        }
    }

    findings.sort_by(|a, b| (a.line, a.rule).cmp(&(b.line, b.rule)));
    findings
}

fn gate(
    files: &[PathBuf],
    provider: &mut dyn Baseline,
    cfg: &Config,
    root_of: &dyn Fn(&Path) -> PathBuf,
) -> GateResult {
    let mut states: Vec<FileState> = Vec::new();
    let mut cross_pool = Counter::new();
    let mut consumed: HashSet<String> = HashSet::new();
    let mut result = GateResult::default();

    for f in files {
        let Some(sf) = extract_path(f) else { continue };
        let (old_source, identity) = provider.source_for(f, &root_of(f));
        if let Some(id) = identity {
            consumed.insert(id);
        }
        let mut old_norms = Counter::new();
        let mut old_code_lines = 0;
        let mut old_prose = 0;
        let mut old_file_wide = Vec::new();
        if let Some(old_source) = &old_source {
            let spec = spec_for_path(&f.to_string_lossy()).unwrap().0;
            let old_sf = extract_source(&f.to_string_lossy(), old_source, spec);
            let old_visible = visible_comments(&old_sf, cfg);
            for c in &old_visible {
                *old_norms.entry(norm(c)).or_insert(0) += 1;
            }
            old_code_lines = old_sf.code_line_count;
            old_prose = prose_lines(&old_visible);
            old_file_wide = file_wide_rules(&old_sf);
        }
        let visible_new = visible_comments(&sf, cfg);
        let new_prose = prose_lines(&visible_new);
        let unmatched = consume_exact(visible_new, &mut old_norms);
        for (k, v) in old_norms {
            // leftovers feed cross-file matching
            *cross_pool.entry(k).or_insert(0) += v;
        }
        states.push(FileState {
            display: f.clone(),
            added_code_lines: sf.code_line_count.saturating_sub(old_code_lines),
            sf,
            unmatched,
            had_counterpart: old_source.is_some(),
            old_prose_lines: old_prose,
            new_prose_lines: new_prose,
            old_file_wide,
        });
    }

    let leftovers = states.iter().any(|st| !st.unmatched.is_empty());
    if leftovers {
        // renames and file splits: pull in the rest of the baseline tree
        if states.iter().any(|st| !st.had_counterpart) {
            if let Some(anchor) = files.first() {
                for (k, v) in tree_norms(provider, anchor, &consumed, cfg) {
                    *cross_pool.entry(k).or_insert(0) += v;
                }
            }
        }
        for st in &mut states {
            st.unmatched = consume_exact(std::mem::take(&mut st.unmatched), &mut cross_pool);
        }
        for st in &mut states {
            st.unmatched =
                consume_fuzzy(std::mem::take(&mut st.unmatched), &mut cross_pool, cfg.baseline_similarity);
        }
    }

    for st in &states {
        result.files_scanned += 1;
        result.findings.extend(finalize(st, cfg));
        result.new_comments += st.unmatched.len();
        result.new_comment_lines += st.unmatched.iter().map(|c| c.line_count()).sum::<usize>();
        result.added_code_lines += st.added_code_lines;
    }
    result.findings.sort_by(|a, b| (&a.path, a.line, a.rule).cmp(&(&b.path, b.line, b.rule)));
    result
}

fn discover(path: &Path, cfg: &Config) -> Vec<PathBuf> {
    if path.is_file() {
        return vec![path.to_path_buf()];
    }
    let mut found = Vec::new();
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for e in entries.filter_map(Result::ok) {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if spec_for_path(&p.to_string_lossy()).is_some() {
                let rel = p
                    .strip_prefix(path)
                    .map(|r| r.to_string_lossy().replace('\\', "/"))
                    .unwrap_or_default();
                if selected(&rel, cfg) && !(cfg.skip_generated && is_generated(&p)) {
                    found.push(p);
                }
            }
        }
    }
    found.sort();
    found
}

pub fn gate_paths(paths: &[PathBuf], baseline: &str, cfg: &Config, root: Option<&Path>) -> GateResult {
    let mut roots: HashMap<PathBuf, PathBuf> = HashMap::new();
    let mut files: Vec<PathBuf> = Vec::new();
    for path in paths {
        let file_root = root
            .map(|r| r.to_path_buf())
            .unwrap_or_else(|| if path.is_dir() { path.clone() } else { path.parent().unwrap_or(Path::new(".")).to_path_buf() });
        for f in discover(path, cfg) {
            if !roots.contains_key(&f) {
                roots.insert(f.clone(), file_root.clone());
                files.push(f);
            }
        }
    }
    let mut provider = provider_for(baseline);
    let root_of = |f: &Path| roots.get(f).cloned().unwrap_or_else(|| PathBuf::from("."));
    gate(&files, provider.as_mut(), cfg, &root_of)
}

/// The pathless gate: git decides the file list — tracked files changed
/// relative to REF plus untracked (not ignored) ones — and the config's
/// include/exclude decides the scope.
pub fn gate_changes(reference: &str, cfg: &Config, root: Option<&Path>) -> Result<GateResult, GateError> {
    let cwd = root.map(|r| r.to_path_buf()).unwrap_or_else(|| std::env::current_dir().unwrap());
    let Some(top) = git_repo_top(&cwd) else {
        return Err(GateError("gate without paths needs to run inside a git repository".to_string()));
    };
    let reference = if reference.is_empty() { "HEAD" } else { reference };

    let mut rels: Vec<String> = Vec::new();
    for args in [
        vec!["diff", "--name-only", "-z", reference, "--"],
        vec!["ls-files", "--others", "--exclude-standard", "-z"],
    ] {
        let out = Command::new("git")
            .args(&args)
            .current_dir(&top)
            .output()
            .map_err(|e| GateError(format!("git executable not found: {e}")))?;
        if !out.status.success() {
            let detail = String::from_utf8_lossy(&out.stderr).trim().split('\n').next().unwrap_or("").to_string();
            return Err(GateError(format!("git could not list changes vs '{reference}': {detail}")));
        }
        rels.extend(
            String::from_utf8_lossy(&out.stdout)
                .split('\0')
                .filter(|r| !r.trim().is_empty())
                .map(|r| r.to_string()),
        );
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut files: Vec<PathBuf> = Vec::new();
    let mut skipped = 0;
    for rel in rels {
        if !seen.insert(rel.clone()) {
            continue;
        }
        let disk = top.join(&rel);
        if !disk.is_file() {
            continue; // deleted in the working tree
        }
        if spec_for_path(&rel).is_none() || !selected(&rel, cfg) {
            skipped += 1;
            continue;
        }
        if cfg.skip_generated && is_generated(&disk) {
            skipped += 1;
            continue;
        }
        files.push(disk);
    }

    let mut provider = GitBaseline::new(reference);
    let top_clone = top.clone();
    let root_of = move |_f: &Path| top_clone.clone();
    let mut result = gate(&files, &mut provider, cfg, &root_of);
    result.files_skipped = skipped;
    Ok(result)
}

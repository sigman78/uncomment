//! Gate-mode tests, mirroring tests/test_gate.py case for case.

use std::path::{Path, PathBuf};
use std::process::Command;

use unwaffle::config::Config;
use unwaffle::gate::{gate_changes, gate_paths};

const OLD: &str = "// Debounce keeps the request count low.\nexport function debounce(fn, delay = 250) {\n  let timer = null;\n  return () => fn();\n}\n";

// same file after an agent edit: one old comment kept, noisy ones added
const NEW: &str = "// Debounce keeps the request count low.\nexport function debounce(fn, delay = 250) {\n  // Changed the timer handling as requested\n  let timer = null;\n  // Then we return the wrapped callback\n  return () => fn();\n}\n";

struct Tmp(PathBuf);

impl Tmp {
    fn new(name: &str) -> Self {
        let dir = std::env::temp_dir().join(format!("unwaffle-gate-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        Tmp(dir)
    }

    fn write(&self, rel: &str, text: &str) -> PathBuf {
        let p = self.0.join(rel);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(&p, text).unwrap();
        p
    }
}

impl Drop for Tmp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn git(repo: &Path, args: &[&str]) {
    let out = Command::new("git")
        .args(args)
        .current_dir(repo)
        .env("GIT_AUTHOR_NAME", "t")
        .env("GIT_AUTHOR_EMAIL", "t@t")
        .env("GIT_COMMITTER_NAME", "t")
        .env("GIT_COMMITTER_EMAIL", "t@t")
        .output()
        .expect("git runs");
    assert!(out.status.success(), "git {args:?}: {}", String::from_utf8_lossy(&out.stderr));
}

#[test]
fn only_new_comments_are_flagged() {
    let tmp = Tmp::new("new-flagged");
    tmp.write("old/a.js", OLD);
    tmp.write("new/a.js", NEW);
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    let rules: Vec<&str> = result.findings.iter().map(|f| f.rule).collect();
    assert!(rules.contains(&"UC003"), "edit-narration line: {rules:?}");
    assert!(rules.contains(&"UC002"), "process-narration line: {rules:?}");
    // the pre-existing comment on line 1 must not produce findings
    assert!(result.findings.iter().all(|f| f.line != 1));
    assert_eq!(result.new_comments, 2);
}

#[test]
fn unchanged_file_is_silent() {
    let tmp = Tmp::new("unchanged");
    tmp.write("old/a.js", NEW); // baseline already contains the noise
    tmp.write("new/a.js", NEW);
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert!(result.findings.is_empty(), "{:?}", result.findings);
    assert_eq!(result.new_comments, 0);
}

#[test]
fn moved_comment_is_not_new() {
    let tmp = Tmp::new("moved");
    tmp.write("old/a.js", "// Keeps latency low on slow disks.\nconst a = 1;\n");
    tmp.write("new/a.js", "const a = 1;\n// Keeps latency low on slow disks.\nconst b = 2;\n");
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert_eq!(result.new_comments, 0);
}

#[test]
fn fuzzy_match_spares_typo_fixes() {
    let tmp = Tmp::new("fuzzy");
    tmp.write("old/a.js", "// Keeps latenzy low on slow disks always.\nconst a = 1;\n");
    tmp.write("new/a.js", "// Keeps latency low on slow disks always.\nconst a = 1;\n");
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert_eq!(result.new_comments, 0, "a one-letter typo fix is not a new comment");
}

#[test]
fn comment_flood_fires() {
    let tmp = Tmp::new("flood");
    let old = "export function f() {\n  return 1;\n}\n";
    let noise: String =
        (0..14).map(|i| format!("// then we run filler step number {i} of the plan\n")).collect();
    tmp.write("old/a.js", old);
    tmp.write("new/a.js", &format!("{noise}{old}"));
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert_eq!(result.new_comment_lines, 14);
    assert_eq!(result.added_code_lines, 0);
    assert!(result.findings.iter().any(|f| f.rule == "UC100"), "{:?}", result.findings);
}

#[test]
fn amplification_fires_on_prose_growth() {
    let tmp = Tmp::new("amplify");
    let old = "// One settled note.\nexport function f() {\n  return 1;\n}\n";
    let extra: String = (0..7)
        .map(|i| format!("// elaboration line number {i} restating the obvious intent\n"))
        .collect();
    tmp.write("old/a.js", old);
    tmp.write("new/a.js", &format!("// One settled note.\n{extra}export function f() {{\n  return 1;\n}}\n"));
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("old").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert!(result.findings.iter().any(|f| f.rule == "UC101"), "{:?}", result.findings);
}

#[test]
fn missing_baseline_treats_all_as_new() {
    let tmp = Tmp::new("missing");
    tmp.write("new/a.js", NEW);
    let result = gate_paths(
        &[tmp.0.join("new")],
        &tmp.0.join("absent").to_string_lossy(),
        &Config::default(),
        None,
    );
    assert_eq!(result.new_comments, 3);
    assert!(result.findings.iter().any(|f| f.rule == "UC003"));
}

#[test]
fn git_baseline_multi_file_rename() {
    let tmp = Tmp::new("git-rename");
    let repo = tmp.0.join("repo");
    std::fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "-q"]);
    std::fs::write(repo.join("a.js"), OLD).unwrap();
    std::fs::write(
        repo.join("b.js"),
        "// Retry twice: the registry drops the first request under load.\nexport const N = 2;\n",
    )
    .unwrap();
    git(&repo, &["add", "a.js", "b.js"]);
    git(&repo, &["commit", "-q", "-m", "base"]);

    std::fs::write(repo.join("a.js"), NEW).unwrap();
    std::fs::rename(repo.join("b.js"), repo.join("c.js")).unwrap(); // no HEAD counterpart

    let result = gate_paths(&[repo.clone()], "git:HEAD", &Config::default(), None);
    assert_eq!(result.files_scanned, 2);
    // the renamed file's comment matched through the tree sweep; only the
    // two noisy comments added to a.js are new
    assert_eq!(result.new_comments, 2);
    let rules: Vec<&str> = result.findings.iter().map(|f| f.rule).collect();
    assert!(rules.contains(&"UC002") && rules.contains(&"UC003"), "{rules:?}");
    assert!(result.findings.iter().all(|f| f.path.ends_with("a.js")));
}

#[test]
fn pathless_gate_uses_git_change_list() {
    let tmp = Tmp::new("pathless");
    let repo = tmp.0.join("repo");
    std::fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "-q"]);
    std::fs::write(repo.join("touched.js"), OLD).unwrap();
    std::fs::write(repo.join("untouched.js"), "// A settled note that never changes.\nconst u = 1;\n").unwrap();
    std::fs::write(repo.join("excluded.js"), OLD).unwrap();
    git(&repo, &["add", "-A"]);
    git(&repo, &["commit", "-q", "-m", "base"]);

    std::fs::write(repo.join("touched.js"), NEW).unwrap();
    std::fs::write(repo.join("excluded.js"), NEW).unwrap();
    std::fs::write(repo.join("fresh.js"), NEW).unwrap();
    std::fs::write(repo.join("notes.txt"), "changed\n").unwrap();

    let mut cfg = Config::default();
    cfg.exclude = vec!["excluded.js".to_string()];
    let result = gate_changes("HEAD", &cfg, Some(&repo)).expect("inside a repo");
    // only the changed+selected files were gated: untouched.js not scanned
    assert_eq!(result.files_scanned, 2);
    assert_eq!(result.files_skipped, 2); // excluded.js + notes.txt
    assert!(!result.findings.is_empty());
    assert!(result
        .findings
        .iter()
        .all(|f| f.path.contains("touched") || f.path.contains("fresh")));
}

#[test]
fn pathless_gate_outside_repo_is_loud() {
    let tmp = Tmp::new("norepo");
    let err = gate_changes("HEAD", &Config::default(), Some(&tmp.0)).unwrap_err();
    assert!(err.0.contains("repository"), "{}", err.0);
}

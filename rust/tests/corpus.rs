//! Corpus-contract harness. The same tests/corpus tree drives the Python
//! suite; a language is held to the full findings contract once its rules
//! are ported, and to extraction smoke checks before that.

use std::path::PathBuf;

use unwaffle::extract::extract_path;
use unwaffle::model::Kind;

fn corpus_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/corpus")
}

#[test]
fn corpus_layout_is_intact() {
    let langs = [
        "c", "cpp", "js", "ts", "tsx", "rust", "go", "python", "java", "csharp", "kotlin", "swift",
    ];
    for lang in langs {
        let dir = corpus_dir().join(lang);
        assert!(dir.is_dir(), "missing corpus dir {lang}");
        let sidecars: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|e| e.file_name().to_string_lossy().ends_with(".expected.json"))
            .collect();
        assert!(!sidecars.is_empty(), "{lang}: no expected.json sidecar");
        for sc in sidecars {
            let val: serde_json::Value =
                serde_json::from_str(&std::fs::read_to_string(sc.path()).unwrap()).unwrap();
            assert!(val["findings"].is_array(), "{lang}: sidecar without findings array");
        }
    }
}

#[test]
fn c_agent_noise_extracts() {
    let sf = extract_path(&corpus_dir().join("c/agent_noise.c")).expect("supported language");
    assert!(sf.comments.len() >= 5, "expected the noisy file to carry comments");
    assert!(sf.code_line_count > 0);
    for c in &sf.comments {
        assert!(c.start_line >= 1 && c.start_line <= c.end_line);
        assert!(c.end_line <= sf.lines.len());
        assert!(!c.content.is_empty() || !c.text.is_empty());
    }
    // masking must remove every comment byte from the code view
    for cl in &sf.code_lines {
        assert!(!cl.contains("//"), "comment marker survived masking: {cl}");
    }
}

#[test]
fn c_doc_comments_classify() {
    let sf = extract_path(&corpus_dir().join("c/agent_noise.c")).expect("supported language");
    let kinds: Vec<Kind> = sf.comments.iter().map(|c| c.kind).collect();
    assert!(kinds.contains(&Kind::Line) || kinds.contains(&Kind::Block));
}

#[test]
fn python_clean_extracts() {
    let sf = extract_path(&corpus_dir().join("python/clean.py")).expect("supported language");
    assert!(sf.code_line_count > 0);
    for cl in &sf.code_lines {
        assert!(!cl.trim_start().starts_with('#'), "comment survived masking: {cl}");
    }
}

#[test]
fn line_comment_runs_merge() {
    let src = "// first line\n// second line\nint x = 1;\n// standalone\n";
    let (spec, _) = unwaffle::languages::spec_for_path("t.c").unwrap();
    let sf = unwaffle::extract::extract_source("t.c", src, spec);
    assert_eq!(sf.comments.len(), 2, "adjacent line comments must merge");
    assert_eq!(sf.comments[0].start_line, 1);
    assert_eq!(sf.comments[0].end_line, 2);
    assert_eq!(sf.comments[0].content, "first line\nsecond line");
    assert_eq!(sf.code_line_count, 1);
}

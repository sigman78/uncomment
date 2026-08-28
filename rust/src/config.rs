//! Thresholds and rule toggles, ported from src/unwaffle/config.py.
//! File loading (unwaffle.toml discovery) is not ported yet; rules run on
//! defaults plus whatever the caller sets.

use crate::model::Severity;
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Config {
    pub restate_overlap: f64,
    pub code_line_fraction: f64,
    pub max_function_comment_ratio: f64,
    pub min_interior_comment_lines: usize,
    pub doc_migration_lines: usize,
    pub max_trailing_chars: usize,
    pub max_trailing_words: usize,
    pub redundant_doc_overlap: f64,
    pub ascii_comments: bool,
    pub ste_max_sentence_words: usize,
    pub ste_max_paragraph_sentences: usize,
    pub max_hints_per_rule: usize,
    pub baseline_similarity: f64,
    pub flood_ratio: f64,
    pub flood_min_lines: usize,
    pub growth_min_lines: usize,
    pub growth_factor: f64,
    pub include: Vec<String>,
    pub exclude: Vec<String>,
    pub skip_generated: bool,
    pub directive_patterns: Vec<String>,
    pub approved_terms: Vec<String>,
    pub disable: Vec<String>,
    pub severity: HashMap<String, Severity>,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            restate_overlap: 0.6,
            code_line_fraction: 0.5,
            max_function_comment_ratio: 0.4,
            min_interior_comment_lines: 4,
            doc_migration_lines: 12,
            max_trailing_chars: 80,
            max_trailing_words: 10,
            redundant_doc_overlap: 0.75,
            ascii_comments: false,
            ste_max_sentence_words: 20,
            ste_max_paragraph_sentences: 6,
            max_hints_per_rule: 8,
            baseline_similarity: 0.85,
            flood_ratio: 0.75,
            flood_min_lines: 12,
            growth_min_lines: 6,
            growth_factor: 1.0,
            include: Vec::new(),
            exclude: Vec::new(),
            skip_generated: true,
            directive_patterns: Vec::new(),
            approved_terms: Vec::new(),
            disable: Vec::new(),
            severity: HashMap::new(),
        }
    }
}

impl Config {
    pub fn rule_enabled(&self, rule_id: &str) -> bool {
        !self.disable.iter().any(|d| rule_id.starts_with(d.as_str()))
    }

    pub fn severity_override(&self, rule_id: &str) -> Option<Severity> {
        self.severity.get(rule_id).copied()
    }
}

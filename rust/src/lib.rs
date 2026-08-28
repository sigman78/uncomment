//! unwaffle, Rust port. The Python implementation in src/unwaffle is the
//! reference; tests/corpus with its .expected.json sidecars is the contract
//! both must satisfy. Extraction (all 12 languages, directives, function
//! context) is at measured parity via rust/parity.py. Rules, gate, and the
//! CLI follow.

pub mod config;
pub mod directives;
pub mod extract;
pub mod filtering;
pub mod gate;
pub mod languages;
pub mod model;
pub mod rules;
pub mod similarity;
pub mod textutil;

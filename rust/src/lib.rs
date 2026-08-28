//! unwaffle, Rust port. The Python implementation in src/unwaffle is the
//! reference; tests/corpus with its .expected.json sidecars is the contract
//! both must satisfy. Ported so far: model types, C + Python extraction
//! (first slice). Rules, gate, and the remaining ten languages follow.

pub mod extract;
pub mod languages;
pub mod model;

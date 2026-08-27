//! Widget storage with copy-on-read semantics.

/// Returns the canonical form of a widget key.
///
/// The store compares keys byte-wise, so fold case before storage.
pub fn canonical_key(key: &str) -> String {
    key.trim().to_lowercase()
}

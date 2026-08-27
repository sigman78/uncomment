//! Crate for widget frobnication.

/// Frobnicates the widget.
pub fn frobnicate_widget() {}

/// Parses a config file into a raw string.
///
/// # Overview
///
/// The parser reads the whole file into memory. It does not stream.
/// Config files are small, so memory use is not a concern here.
///
/// # Example
///
/// Call it with a path and use the returned string:
/// read the value, split on newlines, and trim each line.
///
/// # History
///
/// The first version used a streaming reader. It was too complex.
pub fn parse_config(path: &str) -> String {
    // Step 1: read the file contents into memory
    let data = std::fs::read_to_string(path).unwrap();
    // Step 2: return the data
    data
}

pub fn cleanup() {
    // let tmp = std::env::temp_dir();
    // std::fs::remove_dir_all(tmp).ok();
}

// NOTE: this replaces the previous version, the old implementation used a manual loop
pub const MAX_WIDGETS: usize = 16;

//! Parity-harness support: extract each argument file and emit JSON for
//! rust/parity.py to diff against the Python implementation.

use serde::Serialize;
use unwaffle::extract::extract_path;
use unwaffle::model::Comment;

#[derive(Serialize)]
struct FileDump {
    path: String,
    supported: bool,
    code_line_count: usize,
    comment_line_count: usize,
    comments: Vec<Comment>,
}

fn main() {
    let mut out = Vec::new();
    for arg in std::env::args().skip(1) {
        let p = std::path::PathBuf::from(&arg);
        match extract_path(&p) {
            Some(sf) => out.push(FileDump {
                path: arg,
                supported: true,
                code_line_count: sf.code_line_count,
                comment_line_count: sf.comment_line_count,
                comments: sf.comments,
            }),
            None => out.push(FileDump {
                path: arg,
                supported: false,
                code_line_count: 0,
                comment_line_count: 0,
                comments: Vec::new(),
            }),
        }
    }
    println!("{}", serde_json::to_string(&out).unwrap());
}

use unwaffle::extract::extract_path;
fn main() {
    let sf = extract_path(std::path::Path::new("../tests/corpus/c/agent_noise.c")).unwrap();
    println!("rust:   {} comments, {} code lines, {} comment lines",
             sf.comments.len(), sf.code_line_count, sf.comment_line_count);
}

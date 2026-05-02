use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[pyclass]
#[derive(Clone)]
struct Tag {
    #[pyo3(get, set)]
    rel_fname: String,
    #[pyo3(get, set)]
    fname: String,
    #[pyo3(get, set)]
    name: String,
    #[pyo3(get, set)]
    kind: String,
    #[pyo3(get, set)]
    line: usize,
}

#[pymethods]
impl Tag {
    #[new]
    fn new(rel_fname: String, fname: String, name: String, kind: String, line: usize) -> Self {
        Tag {
            rel_fname,
            fname,
            name,
            kind,
            line,
        }
    }
}

/// Get language from filename
fn get_language_from_filename(fname: &str) -> Option<&'static str> {
    let path = Path::new(fname);
    let extension = path.extension()?.to_str()?;
    
    match extension.to_lowercase().as_str() {
        "py" => Some("python"),
        "js" => Some("javascript"),
        "ts" => Some("typescript"),
        "rs" => Some("rust"),
        "go" => Some("go"),
        "java" => Some("java"),
        "cpp" | "cc" | "cxx" => Some("cpp"),
        "c" | "h" => Some("c"),
        _ => None,
    }
}

/// Get tree-sitter language
fn get_tree_sitter_language(lang: &str) -> Option<tree_sitter::Language> {
    match lang {
        "python" => Some(tree_sitter_python::language()),
        "javascript" => Some(tree_sitter_javascript::language()),
        "typescript" => Some(tree_sitter_typescript::language_typescript()),
        "rust" => Some(tree_sitter_rust::language()),
        "go" => Some(tree_sitter_go::language()),
        "java" => Some(tree_sitter_java::language()),
        "cpp" => Some(tree_sitter_cpp::language()),
        "c" => Some(tree_sitter_c::language()),
        _ => None,
    }
}

/// Parse file and extract tags using tree-sitter
#[pyfunction]
fn get_tags_rust(fname: &str, rel_fname: &str) -> PyResult<Vec<Tag>> {
    let lang = get_language_from_filename(fname).ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("Unsupported file type")
    })?;
    
    let language = get_tree_sitter_language(lang).ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("Language not supported")
    })?;
    
    let mut parser = tree_sitter::Parser::new();
    parser.set_language(language).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Parser error: {}", e))
    })?;
    
    let code = fs::read_to_string(fname).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Read error: {}", e))
    })?;
    
    let tree = parser.parse(&code, None).ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Parse error")
    })?;
    
    let mut tags = Vec::new();
    
    // Simple tag extraction - in a real implementation, this would use
    // tree-sitter queries similar to the Python version
    let root_node = tree.root_node();
    extract_tags_from_node(&root_node, rel_fname, fname, &mut tags);
    
    Ok(tags)
}

/// Extract tags from tree-sitter node (simplified implementation)
fn extract_tags_from_node(node: &tree_sitter::Node, rel_fname: &str, fname: &str, tags: &mut Vec<Tag>) {
    // This is a simplified version - in production, you would use
    // tree-sitter queries like the Python version does
    if node.is_named() {
        let kind = node.kind();
        
        // Check for function/class definitions
        if kind.contains("definition") || kind.contains("function") || kind.contains("class") {
            if let Some(name_node) = node.child_by_field_name("name") {
                let name = name_node.utf8_text(&[]).unwrap_or("").to_string();
                if !name.is_empty() {
                    tags.push(Tag::new(
                        rel_fname.to_string(),
                        fname.to_string(),
                        name,
                        "def".to_string(),
                        node.start_position().row,
                    ));
                }
            }
        }
    }
    
    // Recursively process children
    for i in 0..node.child_count() {
        if let Some(child) = node.child(i) {
            extract_tags_from_node(child, rel_fname, fname, tags);
        }
    }
}

/// PageRank implementation using petgraph
#[pyfunction]
fn pagerank_rust(
    nodes: Vec<String>,
    edges: Vec<(String, String, f64)>,
    personalization: Option<HashMap<String, f64>>,
    damping: f64,
    max_iterations: usize,
    tolerance: f64,
) -> PyResult<HashMap<String, f64>> {
    use petgraph::graph::DiGraph;
    use petgraph::algo::pagerank;
    
    let mut graph = DiGraph::<String, f64>::new();
    
    // Add nodes
    let mut node_indices = HashMap::new();
    for node in &nodes {
        let idx = graph.add_node(node.clone());
        node_indices.insert(node.clone(), idx);
    }
    
    // Add edges
    for (src, dst, weight) in edges {
        if let (Some(&src_idx), Some(&dst_idx)) = (node_indices.get(&src), node_indices.get(&dst)) {
            graph.add_edge(src_idx, dst_idx, *weight);
        }
    }
    
    // Calculate PageRank
    let scores = pagerank(&graph, damping, max_iterations, tolerance);
    
    // Convert back to HashMap
    let mut result = HashMap::new();
    for (idx, score) in graph.node_indices().zip(scores) {
        if let Some(node_name) = graph.node_weight(idx) {
            result.insert(node_name.clone(), *score);
        }
    }
    
    Ok(result)
}

/// Parallel file processing using rayon
#[pyfunction]
fn process_files_parallel(
    fnames: Vec<String>,
    progress_callback: Option<PyObject>,
) -> PyResult<Vec<(String, Vec<Tag>)>> {
    use rayon::prelude::*;
    
    let results: Vec<(String, Vec<Tag>)> = fnames
        .par_iter()
        .map(|fname| {
            let rel_fname = fname.clone(); // In real implementation, calculate relative path
            match get_tags_rust(fname, &rel_fname) {
                Ok(tags) => (fname.clone(), tags),
                Err(_) => (fname.clone(), Vec::new()),
            }
        })
        .collect();
    
    // Call progress callback if provided
    if let Some(callback) = progress_callback {
        Python::with_gil(|py| {
            for (i, (fname, _)) in results.iter().enumerate() {
                if let Err(e) = callback.call1(py, (i, fname)) {
                    eprintln!("Progress callback error: {:?}", e);
                }
            }
        });
    }
    
    Ok(results)
}

#[pymodule]
fn repomap_rust(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Tag>()?;
    m.add_function(wrap_pyfunction!(get_tags_rust, m)?)?;
    m.add_function(wrap_pyfunction!(pagerank_rust, m)?)?;
    m.add_function(wrap_pyfunction!(process_files_parallel, m)?)?;
    Ok(())
}

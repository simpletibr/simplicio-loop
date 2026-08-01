// PyO3 acceleration module for simplicio-mapper.
//
// Exposes hot-path helpers (content hashing and language-aware import parsing)
// as a native Python extension. The Python package falls back to pure-Python
// equivalents when this module is not installed, so all features remain
// available without Rust — building the crate is opt-in for users that want
// the speedup on large repositories.

use once_cell::sync::Lazy;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::Regex;
use sha2::{Digest, Sha256};

/// Compute the lowercase hex sha256 of a UTF-8 string (matches Python's
/// `hashlib.sha256(text.encode("utf-8")).hexdigest()` byte-for-byte).
#[pyfunction]
fn sha256_hex(text: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

static RE_JS_TS_IMPORT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"import\s+[^'"]*['"]([^'"]+)['"]"#).unwrap());
static RE_JS_TS_REQUIRE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"require\(['"]([^'"]+)['"]\)"#).unwrap());
static RE_PY_FROM: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\s*from\s+([A-Za-z0-9_.]+)\s+import\s+").unwrap());
static RE_PY_IMPORT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\s*import\s+([A-Za-z0-9_.]+)").unwrap());
static RE_CSHARP_USING: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\s*using\s+([A-Za-z0-9_.]+)\s*;").unwrap());
static RE_GO_IMPORT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"(?m)^\s*import\s+"([^"]+)""#).unwrap());

fn collect_matches<'a>(text: &'a str, patterns: &[&Lazy<Regex>]) -> Vec<&'a str> {
    let mut out: Vec<&str> = Vec::new();
    for re in patterns {
        for cap in re.captures_iter(text) {
            if let Some(m) = cap.get(1) {
                out.push(m.as_str());
            }
        }
    }
    out
}

/// Extract imported module names from `text` for the given `language`.
///
/// Returns up to 20 unique results in alphabetical order, mirroring the
/// pure-Python `_parse_imports` helper. Unknown languages return an empty list.
#[pyfunction]
fn parse_imports(text: &str, language: &str) -> PyResult<Vec<String>> {
    let raw: Vec<&str> = match language {
        "javascript" | "typescript" => {
            collect_matches(text, &[&RE_JS_TS_IMPORT, &RE_JS_TS_REQUIRE])
        }
        "python" => collect_matches(text, &[&RE_PY_FROM, &RE_PY_IMPORT]),
        "csharp" | "razor" => collect_matches(text, &[&RE_CSHARP_USING]),
        "go" => collect_matches(text, &[&RE_GO_IMPORT]),
        "" => return Err(PyValueError::new_err("language must be non-empty")),
        _ => Vec::new(),
    };

    let mut seen: std::collections::HashSet<&str> = std::collections::HashSet::new();
    let mut uniq: Vec<String> = Vec::new();
    for value in raw.iter().take(2000) {
        if seen.insert(value) {
            uniq.push((*value).to_string());
            if uniq.len() >= 20 {
                break;
            }
        }
    }
    uniq.sort();
    Ok(uniq)
}

/// Parse a batch of ``(path, language, utf8_text)`` records in one FFI call.
///
/// The path is carried through unchanged so callers can merge results
/// deterministically without a second lookup. Per-record errors are returned
/// as an empty import list only for unknown languages; malformed UTF-8 is
/// rejected by PyO3 before entering this function, preserving the Python
/// fallback as the safe path for such input.
#[pyfunction]
fn parse_batch(
    items: Vec<(String, String, String)>,
) -> PyResult<Vec<(String, String, Vec<String>)>> {
    items
        .into_iter()
        .map(|(path, language, text)| {
            Ok((path, sha256_hex(&text), parse_imports(&text, &language)?))
        })
        .collect()
}

#[pymodule]
fn simplicio_mapper_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", "0.1.0")?;
    m.add("__schema__", "simplicio.mapper-native/v1")?;
    m.add("__features__", vec!["sha256", "imports", "batch"])?;
    m.add(
        "__languages__",
        vec![
            "javascript",
            "typescript",
            "python",
            "csharp",
            "razor",
            "go",
        ],
    )?;
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(parse_imports, m)?)?;
    m.add_function(wrap_pyfunction!(parse_batch, m)?)?;
    Ok(())
}

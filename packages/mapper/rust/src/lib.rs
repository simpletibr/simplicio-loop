//! PyO3 adapter for the shared `simplicio_mapper_core` semantic kernels.
//!
//! Filesystem discovery, artifact lifecycle, fallback policy, and orchestration
//! remain in Python. This module only converts Python values to core calls.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use simplicio_mapper_core as core;

fn core_error(error: core::CoreError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

#[pyfunction]
fn sha256_hex(text: &str) -> String {
    core::sha256_hex(text)
}

#[pyfunction]
fn schema_registry_sha256(document: &str) -> PyResult<String> {
    core::schema_registry_sha256(document).map_err(core_error)
}

#[pyfunction]
fn validate_context_graph_contract(document: &str) -> PyResult<String> {
    core::validate_context_graph_contract(document).map_err(core_error)
}

#[pyfunction]
fn parse_imports(text: &str, language: &str) -> PyResult<Vec<String>> {
    core::parse_imports(text, language).map_err(core_error)
}

#[pyfunction]
fn parse_symbols_batch(
    items: Vec<(String, String, String)>,
) -> Vec<(String, String, Vec<String>, Vec<String>)> {
    core::parse_symbols_batch(items)
}

#[pyfunction]
fn parse_batch(
    items: Vec<(String, String, String)>,
) -> PyResult<Vec<(String, String, Vec<String>)>> {
    core::parse_batch(items).map_err(core_error)
}

#[pyfunction]
fn merge_edges(edges: Vec<(String, String, String)>) -> Vec<(String, String, String)> {
    core::merge_edges(edges)
}

#[pyfunction]
fn build_symbol_index(records: Vec<(String, String, u32)>) -> Vec<(String, String, u32)> {
    core::build_symbol_index(records)
}

#[pymodule]
fn simplicio_mapper_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", core::CORE_VERSION)?;
    m.add("__schema__", "simplicio.mapper-native/v1")?;
    m.add("__core_schema__", core::CORE_SCHEMA)?;
    m.add("__core_version__", core::CORE_VERSION)?;
    m.add("__features__", core::FEATURES.to_vec())?;
    m.add("__languages__", core::LANGUAGES.to_vec())?;
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(parse_imports, m)?)?;
    m.add_function(wrap_pyfunction!(parse_batch, m)?)?;
    m.add_function(wrap_pyfunction!(parse_symbols_batch, m)?)?;
    m.add_function(wrap_pyfunction!(merge_edges, m)?)?;
    m.add_function(wrap_pyfunction!(build_symbol_index, m)?)?;
    m.add_function(wrap_pyfunction!(schema_registry_sha256, m)?)?;
    m.add_function(wrap_pyfunction!(validate_context_graph_contract, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adapter_metadata_identifies_the_shared_core() {
        assert_eq!(core::CORE_SCHEMA, "simplicio.mapper-core/v1");
        assert!(core::FEATURES.contains(&"imports"));
    }
}

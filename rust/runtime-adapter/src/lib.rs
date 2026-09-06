//! Effect-free Runtime adapter for the shared Mapper core.
//!
//! Runtime owns filesystem lifecycle, persistence, auth, effects, fallback
//! orchestration, and provider/Loop/Sprint knowledge. This adapter only
//! validates a bounded source-generation request and invokes pure core
//! kernels, making the cross-repository migration seam executable here.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use simplicio_mapper_core as core;
use std::collections::BTreeSet;

pub const REQUEST_SCHEMA: &str = "simplicio.mapper-core-request/v1";
pub const RESULT_SCHEMA: &str = "simplicio.mapper-core-result/v1";
pub const CONTRACT_VERSION: &str = "v1";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct SourceRecord {
    pub path: String,
    pub content: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct MapperCoreRequest {
    pub schema: String,
    pub contract_version: String,
    pub capability: String,
    pub language: String,
    pub source_generation: Vec<SourceRecord>,
}

fn coverage(count: usize) -> Value {
    json!({
        "requested": count,
        "observed": count,
        "omitted": 0,
        "status": "complete",
    })
}

fn validate_request(request: &MapperCoreRequest) -> Result<(), String> {
    if request.schema != REQUEST_SCHEMA {
        return Err("request_schema_unsupported".to_string());
    }
    if request.contract_version != CONTRACT_VERSION {
        return Err("contract_version_unsupported".to_string());
    }
    if !core::LANGUAGES.contains(&request.language.as_str()) {
        return Err("language_unsupported".to_string());
    }
    if !matches!(request.capability.as_str(), "files" | "imports" | "batch") {
        return Err("capability_unsupported".to_string());
    }
    let mut paths = BTreeSet::new();
    for source in &request.source_generation {
        if source.path.is_empty() || !paths.insert(source.path.as_str()) {
            return Err("source_generation_invalid".to_string());
        }
    }
    Ok(())
}

pub fn execute(request: &MapperCoreRequest) -> Result<Value, String> {
    validate_request(request)?;
    let mut sources = request.source_generation.clone();
    sources.sort_by(|left, right| left.path.cmp(&right.path));
    let artifact = match request.capability.as_str() {
        "files" => sources
            .iter()
            .map(|source| {
                json!({
                    "path": source.path,
                    "file_hash": core::sha256_hex(&source.content),
                })
            })
            .collect::<Vec<_>>(),
        "imports" => sources
            .iter()
            .map(|source| {
                let imports = core::parse_imports(&source.content, &request.language)
                    .map_err(|error| error.to_string())?;
                Ok(json!({"path": source.path, "imports": imports}))
            })
            .collect::<Result<Vec<_>, String>>()?,
        "batch" => {
            let batch = sources
                .iter()
                .map(|source| {
                    (source.path.clone(), request.language.clone(), source.content.clone())
                })
                .collect::<Vec<_>>();
            core::parse_batch(batch)
                .map_err(|error| error.to_string())?
                .into_iter()
                .map(|(path, file_hash, imports)| json!({
                    "path": path,
                    "file_hash": file_hash,
                    "imports": imports,
                }))
                .collect::<Vec<_>>()
        }
        _ => unreachable!("request validation handles capabilities"),
    };

    Ok(json!({
        "schema": RESULT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "capability": request.capability,
        "language": request.language,
        "coverage": coverage(sources.len()),
        "artifact": artifact,
        "core_schema": core::CORE_SCHEMA,
        "core_version": core::CORE_VERSION,
        "adapter": "runtime",
    }))
}

pub fn execute_json(document: &str) -> Result<String, String> {
    let request: MapperCoreRequest =
        serde_json::from_str(document).map_err(|error| format!("invalid_request_json: {error}"))?;
    let result = execute(&request)?;
    serde_json::to_string(&result).map_err(|error| format!("result_serialization_failed: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(capability: &str) -> MapperCoreRequest {
        MapperCoreRequest {
            schema: REQUEST_SCHEMA.into(),
            contract_version: CONTRACT_VERSION.into(),
            capability: capability.into(),
            language: "python".into(),
            source_generation: vec![SourceRecord {
                path: "src/main.py".into(),
                content: "import os\n".into(),
            }],
        }
    }

    #[test]
    fn runtime_adapter_delegates_imports_to_shared_core() {
        let result = execute(&request("imports")).expect("adapter result");
        assert_eq!(result["schema"], RESULT_SCHEMA);
        assert_eq!(result["artifact"][0]["imports"], json!(["os"]));
    }

    #[test]
    fn invalid_requests_fail_closed() {
        let mut invalid = request("imports");
        invalid.capability = "architecture".into();
        assert_eq!(execute(&invalid), Err("capability_unsupported".into()));
    }
}

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use simplicio_fast_core::SnapshotReader;
use std::collections::{BTreeMap, HashMap};
use std::io::{self, BufRead, Read, Write};

const ABI: &str = "simplicio.fast-native/v1";
const CHANGESET_MAGIC: &[u8; 8] = b"SFBCHG01";
const MAX_CHANGESET_BYTES: usize = 64 * 1024 * 1024;
const MAX_RECORDS: usize = 100_000;

struct SessionState {
    snapshots: HashMap<String, SnapshotReader>,
}

impl SessionState {
    fn new() -> Self {
        Self {
            snapshots: HashMap::new(),
        }
    }

    fn snapshot(&mut self, path: &str) -> Result<&SnapshotReader, String> {
        if !self.snapshots.contains_key(path) {
            let reader = SnapshotReader::open(path).map_err(|error| error.to_string())?;
            self.snapshots.insert(path.to_owned(), reader);
        }
        self.snapshots
            .get(path)
            .ok_or_else(|| "snapshot cache insertion failed".into())
    }
}

fn execute(operation: &str, payload: &Value, state: &mut SessionState) -> Result<Value, String> {
    match operation {
        "decode_changeset" => decode_changeset(payload),
        "sha256" => {
            let bytes = hex::decode(payload["hex"].as_str().ok_or("hex")?).map_err(|_| "hex")?;
            Ok(json!(hex::encode(Sha256::digest(bytes))))
        }
        "catalog_lookup" => Ok(payload["catalog"]
            .get(payload["key"].as_str().ok_or("key")?)
            .cloned()
            .unwrap_or(Value::Null)),
        "page" => {
            let bytes = hex::decode(payload["hex"].as_str().ok_or("hex")?).map_err(|_| "hex")?;
            let offset = payload["offset"].as_u64().ok_or("offset")? as usize;
            let limit = payload["limit"].as_u64().ok_or("limit")? as usize;
            if limit == 0 || limit > 65536 {
                return Err("bounds".into());
            }
            let end = offset.saturating_add(limit).min(bytes.len());
            let page = if offset >= bytes.len() {
                &[]
            } else {
                &bytes[offset..end]
            };
            Ok(json!(hex::encode(page)))
        }
        "overlay_merge" => {
            let mut merged: BTreeMap<String, Value> =
                serde_json::from_value(payload["base"].clone()).map_err(|_| "base")?;
            let overlay: BTreeMap<String, Value> =
                serde_json::from_value(payload["overlay"].clone()).map_err(|_| "overlay")?;
            for (key, value) in overlay {
                if value.is_null() {
                    merged.remove(&key);
                } else {
                    merged.insert(key, value);
                }
            }
            Ok(json!(merged))
        }
        "query" => {
            let snapshot = payload["snapshot"].as_str().ok_or("snapshot")?;
            let term = payload["term"].as_str().ok_or("term")?;
            let path = payload["path"].as_str();
            let kind = payload["kind"].as_str();
            let limit = payload["limit"].as_u64().unwrap_or(50) as usize;
            let cursor = payload["cursor"].as_u64().map(|value| value as usize);
            let reader = state.snapshot(snapshot)?;
            let receipt = reader
                .query_filtered_after(term, path, kind, limit, cursor)
                .map_err(|error| error.to_string())?;
            Ok(json!({
                "matches": receipt.matches,
                "planner": {
                    "selected_index": receipt.selected_index,
                    "candidates_visited": receipt.candidates_visited,
                    "records_decoded": receipt.records_decoded,
                    "next_cursor": receipt.next_cursor,
                }
            }))
        }
        "context" => {
            let snapshot = payload["snapshot"].as_str().ok_or("snapshot")?;
            let root = payload["root"].as_str().ok_or("root")?;
            let term = payload["term"].as_str().ok_or("term")?;
            let limit = payload["limit"].as_u64().unwrap_or(10) as usize;
            let max_lines = payload["max_lines"].as_u64().unwrap_or(120) as u32;
            let max_bytes = payload["max_bytes"].as_u64().unwrap_or(32_000) as usize;
            let max_tokens = payload["max_tokens"].as_u64().unwrap_or(8_000) as usize;
            let reader = state.snapshot(snapshot)?;
            let receipt = reader
                .context_with_receipt(
                    std::path::Path::new(root),
                    term,
                    limit,
                    max_lines,
                    max_bytes,
                    max_tokens,
                )
                .map_err(|error| error.to_string())?;
            Ok(json!({
                "spans": receipt.spans,
                "planner": {
                    "source_files_read": receipt.source_files_read,
                    "source_cache_hits": receipt.source_cache_hits,
                    "source_bytes_read": receipt.source_bytes_read,
                }
            }))
        }
        "stats" => {
            let snapshot = payload["snapshot"].as_str().ok_or("snapshot")?;
            let reader = state.snapshot(snapshot)?;
            Ok(json!(reader.stats()))
        }
        "session_cache_stats" => Ok(json!({
            "snapshots": state.snapshots.len(),
        })),
        _ => Err("operation".into()),
    }
}

fn read_u32(bytes: &[u8], offset: &mut usize, field: &str) -> Result<u32, String> {
    let end = offset
        .checked_add(4)
        .ok_or_else(|| format!("{field}_overflow"))?;
    let value = bytes
        .get(*offset..end)
        .ok_or_else(|| format!("{field}_truncated"))?;
    *offset = end;
    Ok(u32::from_be_bytes([value[0], value[1], value[2], value[3]]))
}

fn decode_changeset(payload: &Value) -> Result<Value, String> {
    let encoded = payload["hex"].as_str().ok_or("hex")?;
    let bytes = hex::decode(encoded).map_err(|_| "hex")?;
    if bytes.len() > MAX_CHANGESET_BYTES {
        return Err("binary_size_limit".into());
    }
    if bytes.len() < 54 || &bytes[..8] != CHANGESET_MAGIC {
        return Err("binary_header_invalid".into());
    }
    if bytes[8] != 1 || bytes[9] != 0 {
        return Err("binary_header_invalid".into());
    }
    let mut offset = 10usize;
    let metadata_len = read_u32(&bytes, &mut offset, "metadata_length")? as usize;
    let record_count = read_u32(&bytes, &mut offset, "record_count")? as usize;
    let section_len = read_u32(&bytes, &mut offset, "section_length")? as usize;
    let digest = bytes
        .get(offset..offset + 32)
        .ok_or("binary_header_truncated")?;
    offset += 32;
    if record_count > MAX_RECORDS {
        return Err("record_count_limit".into());
    }
    let metadata_end = offset
        .checked_add(metadata_len)
        .ok_or("binary_length_overflow")?;
    let section_end = metadata_end
        .checked_add(section_len)
        .ok_or("binary_length_overflow")?;
    if section_end != bytes.len() {
        return Err("binary_length_mismatch".into());
    }
    let metadata = &bytes[offset..metadata_end];
    let section = &bytes[metadata_end..section_end];
    let mut hasher = Sha256::new();
    hasher.update(metadata);
    hasher.update(section);
    if hasher.finalize().as_slice() != digest {
        return Err("binary_checksum_mismatch".into());
    }
    let mut result: Value = serde_json::from_slice(metadata).map_err(|_| "metadata_invalid")?;
    let object = result.as_object_mut().ok_or("metadata_invalid")?;
    let mut records = Vec::with_capacity(record_count);
    let mut section_offset = 0usize;
    for _ in 0..record_count {
        let length = read_u32(section, &mut section_offset, "record_length")? as usize;
        let end = section_offset
            .checked_add(length)
            .and_then(|value| value.checked_add(32))
            .ok_or("record_length_overflow")?;
        if end > section.len() {
            return Err("record_truncated".into());
        }
        let record_end = section_offset + length;
        let record = &section[section_offset..record_end];
        let checksum = &section[record_end..end];
        let mut record_hasher = Sha256::new();
        record_hasher.update(record);
        if record_hasher.finalize().as_slice() != checksum {
            return Err("record_checksum_mismatch".into());
        }
        records.push(serde_json::from_slice(record).map_err(|_| "record_invalid")?);
        section_offset = end;
    }
    if section_offset != section.len() {
        return Err("section_length_mismatch".into());
    }
    object.insert("operations".into(), Value::Array(records));
    Ok(result)
}

fn response(request: &Value, state: &mut SessionState) -> Value {
    if request["abi"] != ABI {
        return json!({"abi": ABI, "ok": false, "reason": "abi"});
    }
    match execute(
        request["operation"].as_str().unwrap_or(""),
        &request["payload"],
        state,
    ) {
        Ok(result) => json!({"abi": ABI, "ok": true, "result": result}),
        Err(reason) => json!({"abi": ABI, "ok": false, "reason": reason}),
    }
}

fn run_session() -> io::Result<()> {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    writeln!(
        output,
        "{}",
        json!({
            "schema": "simplicio.fast.engine-session/v1",
            "abi": ABI,
            "ok": true,
            "capabilities": ["sha256", "decode_changeset", "catalog_lookup", "page", "overlay_merge", "query", "context", "stats", "session_cache_stats", "mmap_snapshot_cache"],
            "transport": "stdio-lines"
        })
    )?;
    output.flush()?;
    let mut state = SessionState::new();
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let request = match serde_json::from_str::<Value>(&line) {
            Ok(value) => value,
            Err(_) => json!({"abi": ABI, "ok": false, "reason": "frame_invalid"}),
        };
        writeln!(output, "{}", response(&request, &mut state))?;
        output.flush()?;
    }
    Ok(())
}

fn main() {
    if std::env::args().any(|arg| arg == "--session") {
        if run_session().is_err() {
            std::process::exit(2);
        }
        return;
    }
    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        std::process::exit(2);
    }
    let request: Value = match serde_json::from_str(&input) {
        Ok(value) => value,
        Err(_) => std::process::exit(2),
    };
    if request["abi"] != ABI {
        std::process::exit(3);
    }
    let mut state = SessionState::new();
    match response(&request, &mut state) {
        value if value["ok"] == true => println!("{}", value),
        value => {
            println!("{}", value);
            std::process::exit(4);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Vec<u8> {
        let metadata = br#"{"schema":"simplicio.fast.binary-changeset/v1"}"#;
        let record = br#"{"op":"create","path":"a.txt"}"#;
        let mut section = Vec::new();
        section.extend_from_slice(&(record.len() as u32).to_be_bytes());
        section.extend_from_slice(record);
        section.extend_from_slice(Sha256::digest(record).as_slice());
        let mut digest_input = Vec::new();
        digest_input.extend_from_slice(metadata);
        digest_input.extend_from_slice(&section);
        let digest = Sha256::digest(&digest_input);
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CHANGESET_MAGIC);
        bytes.extend_from_slice(&[1, 0]);
        bytes.extend_from_slice(&(metadata.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&1u32.to_be_bytes());
        bytes.extend_from_slice(&(section.len() as u32).to_be_bytes());
        bytes.extend_from_slice(digest.as_slice());
        bytes.extend_from_slice(metadata);
        bytes.extend_from_slice(&section);
        bytes
    }

    #[test]
    fn decodes_sealed_changeset_fixture() {
        let payload = json!({"hex": hex::encode(fixture())});
        let decoded = decode_changeset(&payload).expect("valid changeset");
        assert_eq!(decoded["schema"], "simplicio.fast.binary-changeset/v1");
        assert_eq!(decoded["operations"][0]["path"], "a.txt");
    }

    #[test]
    fn rejects_trailing_bytes() {
        let mut bytes = fixture();
        bytes.push(0);
        let error = decode_changeset(&json!({"hex": hex::encode(bytes)})).unwrap_err();
        assert_eq!(error, "binary_length_mismatch");
    }
}

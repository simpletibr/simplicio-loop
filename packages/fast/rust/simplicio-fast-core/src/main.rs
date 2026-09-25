use serde_json::Value;
use sha2::{Digest, Sha256};
use simplicio_fast_core::{
    decode_projection, encode_projection, manifest, SegmentReader, SegmentWriter, SnapshotReader,
};
use std::{
    collections::HashMap,
    env, fs,
    io::{self, BufRead, Write},
    process::ExitCode,
};

fn print_help() {
    println!("simplicio-fast-rs — Rust snapshot and segment engine");
    println!();
    println!("Usage:");
    println!("  simplicio-fast-rs --version [--json]");
    println!("  simplicio-fast-rs --projection <projection.json>");
    println!("  simplicio-fast-rs --stats <snapshot.sfast>");
    println!("  simplicio-fast-rs --query <snapshot.sfast> <term> [--path <file>] [--kind <kind>] [--limit <positive>] [--cursor <record-id>]");
    println!("  simplicio-fast-rs --relations <snapshot.sfast> [--handle <handle>] [--kind <kind>] [--limit <positive>]");
    println!("  simplicio-fast-rs --context <snapshot.sfast> <repo> <term> [--limit <positive>] [--max-lines <positive>] [--max-bytes <positive>] [--max-tokens <positive>]");
    println!("  simplicio-fast-rs --publish-segments <snapshot.sfast> <directory>");
    println!("  simplicio-fast-rs --segment <directory> <name>");
    println!("  simplicio-fast-rs --session");
    println!();
    println!("Use --help or -h to show this message.");
}

fn session_snapshot<'a>(
    snapshots: &'a mut HashMap<String, SnapshotReader>,
    path: &str,
    expected_generation: Option<&str>,
) -> Result<&'a SnapshotReader, String> {
    if !snapshots.contains_key(path) {
        let reader = SnapshotReader::open(path).map_err(|error| error.to_string())?;
        snapshots.insert(path.to_owned(), reader);
    }
    let snapshot = snapshots
        .get(path)
        .ok_or_else(|| "session_snapshot_missing".to_owned())?;
    if let Some(expected) = expected_generation {
        if expected != snapshot.stats().generation {
            return Err("generation_mismatch".to_owned());
        }
    }
    Ok(snapshot)
}

fn session_execute(
    request: &Value,
    snapshots: &mut HashMap<String, SnapshotReader>,
) -> Result<Value, String> {
    let operation = request
        .get("operation")
        .and_then(Value::as_str)
        .ok_or_else(|| "operation_missing".to_owned())?;
    let payload = request
        .get("payload")
        .ok_or_else(|| "payload_missing".to_owned())?;
    match operation {
        "stats" => {
            let snapshot = payload
                .get("snapshot")
                .and_then(Value::as_str)
                .ok_or_else(|| "snapshot_missing".to_owned())?;
            let expected_generation = payload.get("generation").and_then(Value::as_str);
            Ok(
                serde_json::json!({"stats": session_snapshot(snapshots, snapshot, expected_generation)?.stats()}),
            )
        }
        "query" => {
            let snapshot = payload
                .get("snapshot")
                .and_then(Value::as_str)
                .ok_or_else(|| "snapshot_missing".to_owned())?;
            let term = payload
                .get("term")
                .and_then(Value::as_str)
                .ok_or_else(|| "term_missing".to_owned())?;
            let path = payload.get("path").and_then(Value::as_str);
            let kind = payload.get("kind").and_then(Value::as_str);
            let limit = payload.get("limit").and_then(Value::as_u64).unwrap_or(50) as usize;
            let cursor = payload
                .get("cursor")
                .and_then(Value::as_u64)
                .map(|value| value as usize);
            let expected_generation = payload.get("generation").and_then(Value::as_str);
            let receipt = session_snapshot(snapshots, snapshot, expected_generation)?
                .query_filtered_after(term, path, kind, limit, cursor)
                .map_err(|error| error.to_string())?;
            Ok(serde_json::json!({
                "matches": receipt.matches,
                "planner": {
                    "selected_index": receipt.selected_index,
                    "candidates_visited": receipt.candidates_visited,
                    "records_decoded": receipt.records_decoded,
                    "next_cursor": receipt.next_cursor,
                }
            }))
        }
        "relations" => {
            let snapshot = payload
                .get("snapshot")
                .and_then(Value::as_str)
                .ok_or_else(|| "snapshot_missing".to_owned())?;
            let handle = payload.get("handle").and_then(Value::as_str);
            let kind = payload.get("kind").and_then(Value::as_str);
            let limit = payload.get("limit").and_then(Value::as_u64).unwrap_or(100) as usize;
            let expected_generation = payload.get("generation").and_then(Value::as_str);
            let relations = session_snapshot(snapshots, snapshot, expected_generation)?
                .query_relations(handle, kind, limit)
                .map_err(|error| error.to_string())?;
            let records_decoded = relations.len();
            Ok(serde_json::json!({
                "relations": relations,
                "planner": {"records_decoded": records_decoded}
            }))
        }
        "context" => {
            let snapshot = payload
                .get("snapshot")
                .and_then(Value::as_str)
                .ok_or_else(|| "snapshot_missing".to_owned())?;
            let root = payload
                .get("root")
                .and_then(Value::as_str)
                .ok_or_else(|| "root_missing".to_owned())?;
            let term = payload
                .get("term")
                .and_then(Value::as_str)
                .ok_or_else(|| "term_missing".to_owned())?;
            let number = |name: &str, default: usize| {
                payload
                    .get(name)
                    .and_then(Value::as_u64)
                    .unwrap_or(default as u64) as usize
            };
            let expected_generation = payload.get("generation").and_then(Value::as_str);
            let receipt = session_snapshot(snapshots, snapshot, expected_generation)?
                .context_with_receipt(
                    std::path::Path::new(root),
                    term,
                    number("limit", 10),
                    number("max_lines", 120) as u32,
                    number("max_bytes", 32_000),
                    number("max_tokens", 8_000),
                )
                .map_err(|error| error.to_string())?;
            Ok(serde_json::json!({
                "spans": receipt.spans,
                "planner": {
                    "source_files_read": receipt.source_files_read,
                    "source_cache_hits": receipt.source_cache_hits,
                    "source_bytes_read": receipt.source_bytes_read,
                }
            }))
        }
        "session_cache_stats" => Ok(serde_json::json!({"snapshots": snapshots.len()})),
        _ => Err("operation_unsupported".to_owned()),
    }
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn session_handshake() -> Value {
    let binary_digest = env::current_exe()
        .ok()
        .and_then(|path| std::fs::read(path).ok())
        .map(|bytes| format!("sha256:{}", hex_digest(Sha256::digest(&bytes).as_slice())))
        .unwrap_or_else(|| "unavailable:current-exe".to_owned());
    let metadata = manifest();
    let conformance = &metadata["conformance"];
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos().to_string())
        .unwrap_or_else(|_| "0".to_owned());
    serde_json::json!({
        "schema": "simplicio.fast.engine-session/v1",
        "abi": "simplicio.fast.engine-session/v1",
        "engine": "rust",
        "engine_version": env!("CARGO_PKG_VERSION"),
        "status": "ready",
        "schemas": ["simplicio.fast.engine-session/v1", "simplicio.fast.context/v1", "simplicio.fast.stats/v1", "simplicio.fast.relations/v1"],
        "capabilities": ["stats", "query", "relations", "context", "session_cache_stats"],
        "binary_digest": binary_digest,
        "source_commit": conformance["source_commit"],
        "conformance_digest": conformance["digest"],
        "platform": format!("{}-{}", env::consts::OS, env::consts::ARCH),
        "nonce": nonce,
        "transport": "stdio-lines"
    })
}

fn run_session() -> ExitCode {
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    let mut snapshots = HashMap::new();
    let handshake = session_handshake();
    if writeln!(stdout, "{}", handshake).is_err() || stdout.flush().is_err() {
        return ExitCode::from(1);
    }
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) if line.len() <= 1_048_576 => line,
            _ => {
                let _ = writeln!(stdout, "{{\"ok\":false,\"reason\":\"frame_invalid\"}}");
                continue;
            }
        };
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(request) => match session_execute(&request, &mut snapshots) {
                Ok(result) => serde_json::json!({"ok": true, "result": result}),
                Err(reason) => serde_json::json!({"ok": false, "reason": reason}),
            },
            Err(_) => serde_json::json!({"ok": false, "reason": "frame_invalid"}),
        };
        if writeln!(stdout, "{}", response).is_err() || stdout.flush().is_err() {
            return ExitCode::from(1);
        }
    }
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        print_help();
        return ExitCode::SUCCESS;
    }
    if args.iter().any(|arg| arg == "--version") {
        println!("{}", manifest());
        return ExitCode::SUCCESS;
    }
    if let Some(index) = args.iter().position(|arg| arg == "--projection") {
        let Some(path) = args.get(index + 1) else {
            eprintln!("missing projection path");
            return ExitCode::from(2);
        };
        let result = fs::read(path)
            .map_err(|error| error.to_string())
            .and_then(|raw| {
                let envelope = decode_projection(&raw).map_err(|error| error.to_string())?;
                let encoded = encode_projection(&envelope).map_err(|error| error.to_string())?;
                Ok(serde_json::json!({
                    "schema": "simplicio.fast.projection-conformance/v1",
                    "engine": "rust",
                    "projection_type": envelope.projection_type,
                    "stable_handle": envelope.stable_handle,
                    "generation": envelope.generation,
                    "input_bytes": raw.len(),
                    "encoded_bytes": encoded.len(),
                    "byte_for_byte": encoded == raw,
                }))
            });
        return match result {
            Ok(receipt) => {
                println!("{}", receipt);
                ExitCode::SUCCESS
            }
            Err(reason) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":reason})
                );
                ExitCode::from(2)
            }
        };
    }
    if args.iter().any(|arg| arg == "--session") {
        return run_session();
    }
    if let Some(index) = args.iter().position(|arg| arg == "--query") {
        let Some(path) = args.get(index + 1) else {
            eprintln!("missing snapshot path");
            return ExitCode::from(2);
        };
        let Some(term) = args.get(index + 2) else {
            eprintln!("missing query term");
            return ExitCode::from(2);
        };
        let limit = args
            .iter()
            .position(|arg| arg == "--limit")
            .and_then(|position| args.get(position + 1))
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(50);
        let path_filter = args
            .iter()
            .position(|arg| arg == "--path")
            .and_then(|position| args.get(position + 1))
            .map(String::as_str);
        let kind_filter = args
            .iter()
            .position(|arg| arg == "--kind")
            .and_then(|position| args.get(position + 1))
            .map(String::as_str);
        let cursor = args
            .iter()
            .position(|arg| arg == "--cursor")
            .and_then(|position| args.get(position + 1))
            .and_then(|value| value.parse::<usize>().ok());
        return match SnapshotReader::open(path).and_then(|snapshot| {
            snapshot.query_filtered_after(term, path_filter, kind_filter, limit, cursor)
        }) {
            Ok(receipt) => {
                println!(
                    "{}",
                    serde_json::json!({
                        "schema":"simplicio.fast.query/v1",
                        "engine":"rust",
                        "matches":receipt.matches,
                        "planner": {
                            "selected_index": receipt.selected_index,
                            "candidates_visited": receipt.candidates_visited,
                            "records_decoded": receipt.records_decoded,
                            "next_cursor": receipt.next_cursor,
                        }
                    })
                );
                ExitCode::SUCCESS
            }
            Err(error) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
                );
                ExitCode::from(2)
            }
        };
    }
    if let Some(index) = args.iter().position(|arg| arg == "--relations") {
        let Some(snapshot_path) = args.get(index + 1) else {
            eprintln!("missing snapshot path");
            return ExitCode::from(2);
        };
        let limit = args
            .iter()
            .position(|arg| arg == "--limit")
            .and_then(|position| args.get(position + 1))
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(100);
        let handle = args
            .iter()
            .position(|arg| arg == "--handle")
            .and_then(|position| args.get(position + 1))
            .map(String::as_str);
        let kind = args
            .iter()
            .position(|arg| arg == "--kind")
            .and_then(|position| args.get(position + 1))
            .map(String::as_str);
        return match SnapshotReader::open(snapshot_path)
            .and_then(|snapshot| snapshot.query_relations(handle, kind, limit))
        {
            Ok(relations) => {
                let records_decoded = relations.len();
                println!(
                    "{}",
                    serde_json::json!({
                        "schema":"simplicio.fast.relations/v1",
                        "engine":"rust",
                        "relations":relations,
                        "planner":{"records_decoded":records_decoded}
                    })
                );
                ExitCode::SUCCESS
            }
            Err(error) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
                );
                ExitCode::from(2)
            }
        };
    }
    if let Some(index) = args.iter().position(|arg| arg == "--context") {
        let Some(snapshot_path) = args.get(index + 1) else {
            eprintln!("missing snapshot path");
            return ExitCode::from(2);
        };
        let Some(root) = args.get(index + 2) else {
            eprintln!("missing repository root");
            return ExitCode::from(2);
        };
        let Some(term) = args.get(index + 3) else {
            eprintln!("missing context term");
            return ExitCode::from(2);
        };
        let value = |name: &str, default: usize| {
            args.iter()
                .position(|arg| arg == name)
                .and_then(|position| args.get(position + 1))
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(default)
        };
        return match SnapshotReader::open(snapshot_path).and_then(|snapshot| {
            snapshot.context_with_receipt(
                std::path::Path::new(root),
                term,
                value("--limit", 10),
                value("--max-lines", 120) as u32,
                value("--max-bytes", 32_000),
                value("--max-tokens", 8_000),
            )
        }) {
            Ok(receipt) => {
                println!(
                    "{}",
                    serde_json::json!({
                        "schema":"simplicio.fast.context/v1",
                        "engine":"rust",
                        "spans":receipt.spans,
                        "planner": {
                            "source_files_read": receipt.source_files_read,
                            "source_cache_hits": receipt.source_cache_hits,
                            "source_bytes_read": receipt.source_bytes_read,
                        }
                    })
                );
                ExitCode::SUCCESS
            }
            Err(error) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
                );
                ExitCode::from(2)
            }
        };
    }
    if let Some(index) = args.iter().position(|arg| arg == "--publish-segments") {
        let Some(snapshot_path) = args.get(index + 1) else {
            eprintln!("missing snapshot path");
            return ExitCode::from(2);
        };
        let Some(directory) = args.get(index + 2) else {
            eprintln!("missing segment directory");
            return ExitCode::from(2);
        };
        return match SnapshotReader::open(snapshot_path)
            .and_then(|snapshot| SegmentWriter::new(directory).publish(&snapshot))
        {
            Ok(receipt) => {
                println!(
                    "{}",
                    serde_json::to_string(&receipt).expect("serializable receipt")
                );
                ExitCode::SUCCESS
            }
            Err(error) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
                );
                ExitCode::from(2)
            }
        };
    }
    if let Some(index) = args.iter().position(|arg| arg == "--segment") {
        let Some(directory) = args.get(index + 1) else {
            eprintln!("missing segment directory");
            return ExitCode::from(2);
        };
        let Some(name) = args.get(index + 2) else {
            eprintln!("missing segment name");
            return ExitCode::from(2);
        };
        return match SegmentReader::open(directory).and_then(|reader| reader.map(name)) {
            Ok(segment) => {
                println!(
                    "{}",
                    serde_json::json!({
                        "schema":"simplicio.fast.segment-map/v1",
                        "engine":"rust",
                        "name":segment.name(),
                        "bytes":segment.as_bytes().len(),
                        "sha256":segment.sha256()
                    })
                );
                ExitCode::SUCCESS
            }
            Err(error) => {
                println!(
                    "{}",
                    serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
                );
                ExitCode::from(2)
            }
        };
    }
    let Some(index) = args.iter().position(|arg| arg == "--stats") else {
        eprintln!("missing command: expected --version, --stats <snapshot>, --publish-segments <snapshot> <directory> or --segment <directory> <name>");
        return ExitCode::from(2);
    };
    let Some(path) = args.get(index + 1) else {
        eprintln!("missing snapshot path");
        return ExitCode::from(2);
    };
    match SnapshotReader::open(path) {
        Ok(snapshot) => {
            println!(
                "{}",
                serde_json::json!({"schema":"simplicio.fast.stats/v1", "engine":"rust", "stats":snapshot.stats()})
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            println!(
                "{}",
                serde_json::json!({"schema":"simplicio.fast.error/v1", "engine":"rust", "status":"error", "reason":error.to_string()})
            );
            ExitCode::from(2)
        }
    }
}

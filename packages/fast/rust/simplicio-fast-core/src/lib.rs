//! Safe, dependency-light reader for the SFAST001/v2 snapshot contract.
//!
//! The source tree remains authoritative. This reader treats snapshots as
//! disposable derived data and validates every boundary and checksum before
//! exposing statistics to a caller. It intentionally has no Python runtime
//! dependency and maps validated snapshots read-only when opened from disk.

pub mod capability_ranking;

use memmap2::{Mmap, MmapOptions};
use serde::{
    de::{self, Deserializer, SeqAccess, Visitor},
    Deserialize, Serialize,
};
use sha2::{Digest, Sha256};
mod segment_writer;
pub use segment_writer::{PublishReceipt, PublishedSegment, SegmentWriter};

use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    fmt, fs,
    fs::File,
    path::{Path, PathBuf},
};

pub const MAGIC: &[u8; 8] = b"SFAST001";
pub const VERSION: u16 = 2;
pub const ENDIAN_MARKER: u16 = 0x0102;
pub const HEADER_SIZE: usize = 80;
pub const SECTION_SIZE: usize = 64;
pub const FILE_RECORD_SIZE: usize = 64;
pub const SYMBOL_RECORD_SIZE: usize = 72;
pub const MAX_SNAPSHOT_BYTES: usize = 512 * 1024 * 1024;
pub const REQUIRED_SECTIONS: [&str; 5] = ["files", "symbols", "relations", "indexes", "strings"];
pub const PROJECTION_SCHEMA: &str = "simplicio.fast.projection/v1";
pub const PROJECTION_TYPES: [&str; 3] = ["code", "knowledge", "operations"];
pub const PROJECTION_MAX_BYTES: usize = 8 * 1024 * 1024;
pub const PROJECTION_MAX_DEPTH: usize = 32;
pub const PROJECTION_MAX_ITEMS: usize = 100_000;
pub const PROJECTION_MAX_TEXT: usize = 4096;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ProjectionEnvelope {
    pub schema: String,
    pub projection_type: String,
    pub producer: String,
    pub producer_schema: String,
    pub generation: String,
    pub stable_handle: String,
    pub payload: serde_json::Value,
    pub payload_sha256: String,
    pub schema_version: String,
    pub projection_type_version: String,
    pub producer_version: String,
    pub repository_scope: String,
    pub tenant_scope: String,
    pub domain_scope: String,
    pub source_generation: String,
    pub projection_generation: String,
    pub config_fingerprint: String,
    pub toolchain_fingerprint: String,
    pub parser_fingerprint: String,
    pub stable_handles: Vec<String>,
    pub capabilities_required: Vec<String>,
    pub budgets: Option<BTreeMap<String, u64>>,
    pub truncation_reasons: Vec<String>,
    pub parent_generation: Option<String>,
    pub base_generation: Option<String>,
    pub delta_generation: Option<String>,
    pub tombstones: Vec<String>,
    pub completeness: String,
    pub fidelity: String,
    pub observed_sequence: String,
    pub conformance_digest: String,
}

#[derive(Debug)]
pub enum SnapshotError {
    Io(std::io::Error),
    Invalid(String),
}

impl fmt::Display for SnapshotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "I/O error: {error}"),
            Self::Invalid(reason) => write!(f, "invalid snapshot: {reason}"),
        }
    }
}

impl std::error::Error for SnapshotError {}

impl From<std::io::Error> for SnapshotError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct SnapshotStats {
    pub schema: String,
    pub format_version: u16,
    pub bytes: usize,
    pub files: usize,
    pub symbols: usize,
    pub relations: usize,
    pub sections: Vec<String>,
    pub generation: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RustSymbol {
    pub name: String,
    pub qualified_name: String,
    pub kind: String,
    pub file: String,
    pub line: u32,
    pub end_line: u32,
    pub symbol_id: String,
    pub signature: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct RustRelation {
    pub origin: String,
    pub destination: String,
    pub kind: String,
    pub confidence: f64,
    #[serde(default)]
    pub origin_id: String,
    #[serde(default)]
    pub destination_id: String,
}

fn valid_relation(relation: &RustRelation) -> bool {
    relation.confidence.is_finite()
        && (0.0..=1.0).contains(&relation.confidence)
        && !relation.origin.is_empty()
        && !relation.destination.is_empty()
        && !relation.kind.is_empty()
}

struct RelationVisitor<'a> {
    handle: Option<&'a str>,
    kind: Option<&'a str>,
    limit: usize,
    matches: Vec<RustRelation>,
}

impl<'de, 'a> Visitor<'de> for RelationVisitor<'a> {
    type Value = Vec<RustRelation>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("an array of valid relation records")
    }

    fn visit_seq<A>(mut self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        while let Some(relation) = sequence.next_element::<RustRelation>()? {
            if !valid_relation(&relation) {
                return Err(de::Error::custom("invalid relation record"));
            }
            let handle_match = self.handle.map_or(true, |value| {
                relation.origin == value
                    || relation.destination == value
                    || relation.origin_id == value
                    || relation.destination_id == value
            });
            let kind_match = self.kind.map_or(true, |value| relation.kind == value);
            if self.matches.len() < self.limit && handle_match && kind_match {
                self.matches.push(relation);
            }
        }
        Ok(self.matches)
    }
}

fn relation_section(
    bytes: &[u8],
    handle: Option<&str>,
    kind: Option<&str>,
    limit: usize,
) -> Result<Vec<RustRelation>, SnapshotError> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let relations = deserializer
        .deserialize_seq(RelationVisitor {
            handle,
            kind,
            limit,
            matches: Vec::with_capacity(limit.min(1024)),
        })
        .map_err(|error| SnapshotError::Invalid(format!("invalid relation JSON: {error}")))?;
    deserializer
        .end()
        .map_err(|error| SnapshotError::Invalid(format!("invalid relation JSON: {error}")))?;
    Ok(relations)
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RustContextSpan {
    pub symbol: String,
    pub kind: String,
    pub file: String,
    pub start_line: u32,
    pub end_line: u32,
    pub source_sha256: String,
    pub content: String,
    pub symbol_id: String,
    pub tokens: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ContextReceipt {
    pub spans: Vec<RustContextSpan>,
    pub source_files_read: usize,
    pub source_cache_hits: usize,
    pub source_bytes_read: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct QueryReceipt {
    pub matches: Vec<RustSymbol>,
    pub selected_index: String,
    pub candidates_visited: usize,
    pub records_decoded: usize,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct Section {
    pub(crate) offset: usize,
    pub(crate) length: usize,
}

pub struct SnapshotReader {
    pub(crate) bytes: SnapshotBytes,
    pub(crate) sections: BTreeMap<String, Section>,
    digest: [u8; 32],
    indexes: PersistedIndexes,
}

pub(crate) enum SnapshotBytes {
    Owned(Vec<u8>),
    Mapped(Mmap),
}

impl SnapshotBytes {
    pub(crate) fn as_slice(&self) -> &[u8] {
        match self {
            Self::Owned(bytes) => bytes,
            Self::Mapped(bytes) => bytes,
        }
    }

    fn len(&self) -> usize {
        self.as_slice().len()
    }
}

#[derive(Debug, Deserialize)]
struct SegmentManifest {
    schema: String,
    segments: Vec<SegmentEntry>,
}

#[derive(Debug, Deserialize)]
struct SegmentEntry {
    name: String,
    file: String,
    bytes: usize,
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct PersistedIndexes {
    exact: BTreeMap<String, Vec<usize>>,
    names: BTreeMap<String, Vec<usize>>,
    paths: BTreeMap<String, Vec<usize>>,
    kinds: BTreeMap<String, Vec<usize>>,
}

enum SegmentBytes {
    Empty,
    Mapped(Mmap),
}

pub struct MappedSegment {
    name: String,
    bytes: SegmentBytes,
    sha256: String,
}

impl MappedSegment {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn as_bytes(&self) -> &[u8] {
        match &self.bytes {
            SegmentBytes::Empty => &[],
            SegmentBytes::Mapped(bytes) => bytes,
        }
    }

    pub fn sha256(&self) -> &str {
        &self.sha256
    }
}

pub struct SegmentReader {
    directory: PathBuf,
    manifest: SegmentManifest,
}

impl SegmentReader {
    pub fn open(directory: impl AsRef<Path>) -> Result<Self, SnapshotError> {
        let directory = directory.as_ref().canonicalize()?;
        let manifest = match read_segment_manifest(&directory.join("manifest.json")) {
            Ok(manifest) => manifest,
            Err(current_error) => read_segment_manifest(&directory.join("manifest.previous.json"))
                .map_err(|_| current_error)?,
        };
        Ok(Self {
            directory,
            manifest,
        })
    }

    pub fn map(&self, name: &str) -> Result<MappedSegment, SnapshotError> {
        let entry = self
            .manifest
            .segments
            .iter()
            .find(|entry| entry.name == name)
            .ok_or_else(|| SnapshotError::Invalid(format!("segment not found: {name}")))?;
        let entry_path = Path::new(&entry.file);
        if entry_path.file_name().and_then(|value| value.to_str()) != Some(entry.file.as_str()) {
            return Err(SnapshotError::Invalid(
                "segment path escapes directory".into(),
            ));
        }
        let path = self.directory.join(entry_path).canonicalize()?;
        if path.strip_prefix(&self.directory).is_err() {
            return Err(SnapshotError::Invalid(
                "segment path escapes directory".into(),
            ));
        }
        let file = File::open(path)?;
        let length = u64_to_usize(file.metadata()?.len())?;
        if length != entry.bytes {
            return Err(SnapshotError::Invalid(format!(
                "segment size mismatch: {}",
                entry.name
            )));
        }
        if length == 0 {
            if entry.sha256 != hex_bytes(&Sha256::digest([])) {
                return Err(SnapshotError::Invalid(format!(
                    "segment checksum mismatch: {}",
                    entry.name
                )));
            }
            return Ok(MappedSegment {
                name: entry.name.clone(),
                bytes: SegmentBytes::Empty,
                sha256: entry.sha256.clone(),
            });
        }
        let mapped = unsafe { MmapOptions::new().map(&file)? };
        let actual = hex_bytes(&Sha256::digest(&mapped));
        if actual != entry.sha256 {
            return Err(SnapshotError::Invalid(format!(
                "segment checksum mismatch: {}",
                entry.name
            )));
        }
        Ok(MappedSegment {
            name: entry.name.clone(),
            bytes: SegmentBytes::Mapped(mapped),
            sha256: actual,
        })
    }
}

fn read_segment_manifest(path: &Path) -> Result<SegmentManifest, SnapshotError> {
    let manifest: SegmentManifest = serde_json::from_slice(&fs::read(path)?)
        .map_err(|_| SnapshotError::Invalid("invalid segment manifest JSON".into()))?;
    if manifest.schema != "simplicio.fast.segments/v1" {
        return Err(SnapshotError::Invalid(
            "unsupported segment manifest schema".into(),
        ));
    }
    Ok(manifest)
}

impl SnapshotReader {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, SnapshotError> {
        let file = File::open(path)?;
        let length = u64_to_usize(file.metadata()?.len())?;
        if length > MAX_SNAPSHOT_BYTES {
            return Err(SnapshotError::Invalid(
                "snapshot size limit exceeded".into(),
            ));
        }
        // The mapped bytes are validated by `from_storage` before any record
        // is exposed. The mapping is read-only and owned by the reader.
        let mapped = unsafe { MmapOptions::new().map(&file)? };
        Self::from_storage(SnapshotBytes::Mapped(mapped))
    }

    pub fn from_bytes(bytes: Vec<u8>) -> Result<Self, SnapshotError> {
        Self::from_storage(SnapshotBytes::Owned(bytes))
    }

    fn from_storage(bytes: SnapshotBytes) -> Result<Self, SnapshotError> {
        let raw = bytes.as_slice();
        if raw.len() < HEADER_SIZE {
            return Err(SnapshotError::Invalid("truncated header".into()));
        }
        if raw.len() > MAX_SNAPSHOT_BYTES {
            return Err(SnapshotError::Invalid(
                "snapshot size limit exceeded".into(),
            ));
        }
        if &raw[..8] != MAGIC {
            return Err(SnapshotError::Invalid("invalid magic".into()));
        }
        let version = u16_at(raw, 8)?;
        let endian = u16_at(raw, 10)?;
        let section_count = u32_at(raw, 12)? as usize;
        let directory_offset = u64_to_usize(u64_at(raw, 24)?)?;
        let directory_size = u64_to_usize(u64_at(raw, 32)?)?;
        let total_size = u64_to_usize(u64_at(raw, 40)?)?;
        if version != VERSION || endian != ENDIAN_MARKER {
            return Err(SnapshotError::Invalid(
                "unsupported version or endian marker".into(),
            ));
        }
        if total_size != raw.len() {
            return Err(SnapshotError::Invalid("total size mismatch".into()));
        }
        if !(REQUIRED_SECTIONS.len()..=32).contains(&section_count)
            || directory_size != section_count * SECTION_SIZE
            || directory_offset < HEADER_SIZE
            || !region_valid(directory_offset, directory_size, raw.len())
        {
            return Err(SnapshotError::Invalid("invalid section directory".into()));
        }

        let expected_digest = slice32(raw, 48)?;
        let mut whole = raw.to_vec();
        whole[48..80].fill(0);
        let payload_digest = Sha256::digest(&whole);
        if payload_digest.as_slice() != expected_digest {
            return Err(SnapshotError::Invalid("snapshot checksum mismatch".into()));
        }
        let snapshot_digest = Sha256::digest(raw);

        let directory_end = directory_offset + directory_size;
        let mut sections = BTreeMap::new();
        let mut ranges = Vec::with_capacity(section_count);
        for index in 0..section_count {
            let start = directory_offset + index * SECTION_SIZE;
            let name_bytes = &raw[start..start + 16];
            let name_end = name_bytes.iter().position(|byte| *byte == 0).unwrap_or(16);
            let name = std::str::from_utf8(&name_bytes[..name_end])
                .map_err(|_| SnapshotError::Invalid("non-ASCII section name".into()))?;
            if name.is_empty() || sections.contains_key(name) {
                return Err(SnapshotError::Invalid(
                    "duplicate or empty section name".into(),
                ));
            }
            let offset = u64_to_usize(u64_at(raw, start + 16)?)?;
            let length = u64_to_usize(u64_at(raw, start + 24)?)?;
            if offset % 8 != 0 || offset < directory_end || !region_valid(offset, length, raw.len())
            {
                return Err(SnapshotError::Invalid(format!(
                    "invalid section bounds: {name}"
                )));
            }
            let expected = slice32(raw, start + 32)?;
            let actual = Sha256::digest(&raw[offset..offset + length]);
            if actual.as_slice() != expected {
                return Err(SnapshotError::Invalid(format!(
                    "section checksum mismatch: {name}"
                )));
            }
            ranges.push((offset, offset + length));
            sections.insert(name.to_owned(), Section { offset, length });
        }
        for (index, (left_start, left_end)) in ranges.iter().enumerate() {
            for (right_start, right_end) in ranges.iter().skip(index + 1) {
                if *left_start < *right_end && *right_start < *left_end {
                    return Err(SnapshotError::Invalid("overlapping sections".into()));
                }
            }
        }
        for required in REQUIRED_SECTIONS {
            if !sections.contains_key(required) {
                return Err(SnapshotError::Invalid(format!(
                    "missing section: {required}"
                )));
            }
        }
        if sections["files"].length % FILE_RECORD_SIZE != 0
            || sections["symbols"].length % SYMBOL_RECORD_SIZE != 0
        {
            return Err(SnapshotError::Invalid(
                "record section is not aligned".into(),
            ));
        }
        relation_section(section_bytes(raw, &sections["relations"]), None, None, 0)?;
        let symbol_count = sections["symbols"].length / SYMBOL_RECORD_SIZE;
        let indexes: PersistedIndexes =
            serde_json::from_slice(section_bytes(raw, &sections["indexes"]))
                .map_err(|_| SnapshotError::Invalid("invalid persisted indexes".into()))?;
        validate_persisted_indexes(&indexes, symbol_count)?;
        Ok(Self {
            bytes,
            sections,
            digest: snapshot_digest.into(),
            indexes,
        })
    }

    pub fn stats(&self) -> SnapshotStats {
        let relations = serde_json::from_slice::<serde_json::Value>(section_bytes(
            self.bytes.as_slice(),
            &self.sections["relations"],
        ))
        .ok()
        .and_then(|value| value.as_array().map(Vec::len))
        .unwrap_or(0);
        SnapshotStats {
            schema: "simplicio.fast.rust-stats/v1".into(),
            format_version: VERSION,
            bytes: self.bytes.len(),
            files: self.sections["files"].length / FILE_RECORD_SIZE,
            symbols: self.sections["symbols"].length / SYMBOL_RECORD_SIZE,
            relations,
            sections: self.sections.keys().cloned().collect(),
            generation: format!("SFAST001:{}", hex(&self.digest)),
        }
    }

    pub fn symbols(&self) -> Result<Vec<RustSymbol>, SnapshotError> {
        let strings = &self.sections["strings"];
        let symbols = &self.sections["symbols"];
        let mut result = Vec::with_capacity(symbols.length / SYMBOL_RECORD_SIZE);
        for index in 0..symbols.length / SYMBOL_RECORD_SIZE {
            result.push(self.symbol_at(index, strings)?);
        }
        Ok(result)
    }

    pub fn relations(&self) -> Result<Vec<RustRelation>, SnapshotError> {
        relation_section(
            section_bytes(self.bytes.as_slice(), &self.sections["relations"]),
            None,
            None,
            usize::MAX,
        )
    }

    pub fn query_relations(
        &self,
        handle: Option<&str>,
        kind: Option<&str>,
        limit: usize,
    ) -> Result<Vec<RustRelation>, SnapshotError> {
        if limit == 0 {
            return Err(SnapshotError::Invalid(
                "relation limit must be positive".into(),
            ));
        }
        relation_section(
            section_bytes(self.bytes.as_slice(), &self.sections["relations"]),
            handle,
            kind,
            limit,
        )
    }

    pub fn query(&self, term: &str, limit: usize) -> Result<Vec<RustSymbol>, SnapshotError> {
        Ok(self.query_with_receipt(term, limit)?.matches)
    }

    pub fn query_with_receipt(
        &self,
        term: &str,
        limit: usize,
    ) -> Result<QueryReceipt, SnapshotError> {
        self.query_filtered(term, None, None, limit)
    }

    pub fn query_filtered(
        &self,
        term: &str,
        path: Option<&str>,
        kind: Option<&str>,
        limit: usize,
    ) -> Result<QueryReceipt, SnapshotError> {
        self.query_filtered_after(term, path, kind, limit, None)
    }

    pub fn query_filtered_after(
        &self,
        term: &str,
        path: Option<&str>,
        kind: Option<&str>,
        limit: usize,
        cursor: Option<usize>,
    ) -> Result<QueryReceipt, SnapshotError> {
        if limit == 0 {
            return Err(SnapshotError::Invalid(
                "query limit must be positive".into(),
            ));
        }
        let needle = term.to_lowercase();
        let symbol_count = self.sections["symbols"].length / SYMBOL_RECORD_SIZE;
        let mut candidate_ids = BTreeSet::new();
        let mut candidates_visited = 0;
        let mut selected_index = "legacy.names+exact-substring".to_owned();
        let mut exact_hit = false;
        for index in [&self.indexes.names, &self.indexes.exact] {
            if let Some(values) = index.get(&needle) {
                exact_hit = true;
                candidates_visited += values.len();
                add_index_values(values, symbol_count, &mut candidate_ids)?;
            }
        }
        if exact_hit {
            selected_index = "persisted.exact".into();
        } else if !needle.is_empty() {
            for index in [&self.indexes.names, &self.indexes.exact] {
                for (key, values) in index.range(needle.clone()..) {
                    if !key.starts_with(&needle) {
                        break;
                    }
                    candidates_visited += values.len();
                    add_index_values(values, symbol_count, &mut candidate_ids)?;
                }
            }
            if !candidate_ids.is_empty() {
                selected_index = "persisted.prefix".into();
            }
        }
        if candidate_ids.is_empty() {
            for values in self
                .indexes
                .names
                .iter()
                .filter(|(key, _)| key.contains(&needle))
                .map(|(_, values)| values)
                .chain(
                    self.indexes
                        .exact
                        .iter()
                        .filter(|(key, _)| key.contains(&needle))
                        .map(|(_, values)| values),
                )
            {
                candidates_visited += values.len();
                add_index_values(values, symbol_count, &mut candidate_ids)?;
            }
        }
        for (filter, index, label) in [
            (path, &self.indexes.paths, "path"),
            (kind, &self.indexes.kinds, "kind"),
        ] {
            let Some(filter) = filter else {
                continue;
            };
            let Some(values) = index.get(filter) else {
                candidate_ids.clear();
                continue;
            };
            let mut allowed = BTreeSet::new();
            add_index_values(values, symbol_count, &mut allowed)?;
            candidate_ids.retain(|candidate| allowed.contains(candidate));
            selected_index.push('+');
            selected_index.push_str(label);
        }
        let strings = &self.sections["strings"];
        let mut candidate_ids = candidate_ids
            .into_iter()
            .filter(|index| cursor.map_or(true, |after| *index > after));
        let selected_ids: Vec<usize> = candidate_ids.by_ref().take(limit).collect();
        let next_cursor = if selected_ids.len() == limit && candidate_ids.next().is_some() {
            selected_ids.last().map(|index| index.to_string())
        } else {
            None
        };
        let matches: Vec<RustSymbol> = selected_ids
            .into_iter()
            .take(limit)
            .map(|index| self.symbol_at(index, strings))
            .collect::<Result<_, _>>()?;
        let records_decoded = matches.len();
        Ok(QueryReceipt {
            matches,
            selected_index,
            candidates_visited,
            records_decoded,
            next_cursor,
        })
    }

    pub fn context(
        &self,
        root: &Path,
        term: &str,
        max_results: usize,
        max_lines: u32,
        max_bytes: usize,
        max_tokens: usize,
    ) -> Result<Vec<RustContextSpan>, SnapshotError> {
        self.context_with_receipt(root, term, max_results, max_lines, max_bytes, max_tokens)
            .map(|receipt| receipt.spans)
    }

    pub fn context_with_receipt(
        &self,
        root: &Path,
        term: &str,
        max_results: usize,
        max_lines: u32,
        max_bytes: usize,
        max_tokens: usize,
    ) -> Result<ContextReceipt, SnapshotError> {
        if max_results == 0 || max_lines == 0 || max_bytes == 0 || max_tokens == 0 {
            return Err(SnapshotError::Invalid(
                "context limits must be positive".into(),
            ));
        }
        let root = root
            .canonicalize()
            .map_err(|_| SnapshotError::Invalid("repository root is unavailable".into()))?;
        let files: HashMap<String, [u8; 32]> = self.file_info()?.into_iter().collect();
        let mut source_cache: HashMap<String, ([u8; 32], String)> = HashMap::new();
        let mut result = Vec::new();
        let mut source_files_read = 0;
        let mut source_cache_hits = 0;
        let mut source_bytes_read = 0;
        let mut consumed_bytes = 0;
        let mut consumed_tokens = 0;
        for symbol in self.query(term, max_results)? {
            let Some(expected_digest) = files.get(&symbol.file) else {
                return Err(SnapshotError::Invalid(
                    "symbol references unknown file".into(),
                ));
            };
            if !source_cache.contains_key(&symbol.file) {
                let path = root.join(&symbol.file).canonicalize().map_err(|_| {
                    SnapshotError::Invalid(format!("source missing: {}", symbol.file))
                })?;
                if path.strip_prefix(&root).is_err() {
                    return Err(SnapshotError::Invalid("snapshot path escapes root".into()));
                }
                let bytes = fs::read(&path)?;
                source_files_read += 1;
                source_bytes_read += bytes.len();
                let actual_digest: [u8; 32] = Sha256::digest(&bytes).into();
                if &actual_digest != expected_digest {
                    return Err(SnapshotError::Invalid(format!(
                        "stale source: {}",
                        symbol.file
                    )));
                }
                let text = String::from_utf8(bytes)
                    .map_err(|_| SnapshotError::Invalid("source is not UTF-8".into()))?;
                source_cache.insert(symbol.file.clone(), (actual_digest, text));
            } else {
                source_cache_hits += 1;
            }
            let (actual_digest, text) = source_cache
                .get(&symbol.file)
                .ok_or_else(|| SnapshotError::Invalid("source cache insertion failed".into()))?;
            let lines: Vec<&str> = text.lines().collect();
            let start = symbol.line.max(1) as usize;
            let end = std::cmp::min(
                symbol.end_line,
                symbol.line.saturating_add(max_lines).saturating_sub(1),
            ) as usize;
            if start > lines.len() || end < start {
                return Err(SnapshotError::Invalid(
                    "symbol line bounds out of range".into(),
                ));
            }
            let mut content = lines[start - 1..end].join("\n");
            if consumed_bytes + content.len() > max_bytes {
                let remaining = max_bytes.saturating_sub(consumed_bytes);
                if remaining == 0 {
                    break;
                }
                content = truncate_utf8(&content, remaining);
            }
            let mut tokens = std::cmp::max(1, (content.len() + 3) / 4);
            if consumed_tokens + tokens > max_tokens {
                let remaining = max_tokens.saturating_sub(consumed_tokens);
                if remaining == 0 {
                    break;
                }
                content = truncate_utf8(&content, remaining * 4);
                tokens = std::cmp::max(1, (content.len() + 3) / 4);
            }
            consumed_bytes += content.len();
            consumed_tokens += tokens;
            result.push(RustContextSpan {
                symbol: symbol.qualified_name,
                kind: symbol.kind,
                file: symbol.file,
                start_line: symbol.line,
                end_line: end as u32,
                source_sha256: hex_bytes(actual_digest),
                content,
                symbol_id: symbol.symbol_id,
                tokens,
            });
        }
        Ok(ContextReceipt {
            spans: result,
            source_files_read,
            source_cache_hits,
            source_bytes_read,
        })
    }

    fn symbol_at(&self, index: usize, strings: &Section) -> Result<RustSymbol, SnapshotError> {
        let symbols = &self.sections["symbols"];
        let base =
            symbols
                .offset
                .checked_add(index.checked_mul(SYMBOL_RECORD_SIZE).ok_or_else(|| {
                    SnapshotError::Invalid("symbol record offset overflow".into())
                })?)
                .ok_or_else(|| SnapshotError::Invalid("symbol record offset overflow".into()))?;
        let file_index = u32_at(self.bytes.as_slice(), base + 24)? as usize;
        let file = self.file_at(file_index)?;
        Ok(RustSymbol {
            name: read_text(
                self.bytes.as_slice(),
                strings,
                u32_at(self.bytes.as_slice(), base)? as usize,
                u32_at(self.bytes.as_slice(), base + 4)? as usize,
            )?,
            qualified_name: read_text(
                self.bytes.as_slice(),
                strings,
                u32_at(self.bytes.as_slice(), base + 8)? as usize,
                u32_at(self.bytes.as_slice(), base + 12)? as usize,
            )?,
            signature: read_text(
                self.bytes.as_slice(),
                strings,
                u32_at(self.bytes.as_slice(), base + 16)? as usize,
                u32_at(self.bytes.as_slice(), base + 20)? as usize,
            )?,
            kind: kind_name(u32_at(self.bytes.as_slice(), base + 36)?)?,
            file,
            line: u32_at(self.bytes.as_slice(), base + 28)?,
            end_line: u32_at(self.bytes.as_slice(), base + 32)?,
            symbol_id: hex_bytes(&self.bytes.as_slice()[base + 40..base + 72]),
        })
    }

    fn file_at(&self, index: usize) -> Result<String, SnapshotError> {
        let files = &self.sections["files"];
        let strings = &self.sections["strings"];
        let base = files
            .offset
            .checked_add(
                index
                    .checked_mul(FILE_RECORD_SIZE)
                    .ok_or_else(|| SnapshotError::Invalid("file record offset overflow".into()))?,
            )
            .ok_or_else(|| SnapshotError::Invalid("file record offset overflow".into()))?;
        if index >= files.length / FILE_RECORD_SIZE {
            return Err(SnapshotError::Invalid(
                "symbol file index out of bounds".into(),
            ));
        }
        read_text(
            self.bytes.as_slice(),
            strings,
            u32_at(self.bytes.as_slice(), base)? as usize,
            u32_at(self.bytes.as_slice(), base + 4)? as usize,
        )
    }

    fn file_info(&self) -> Result<Vec<(String, [u8; 32])>, SnapshotError> {
        let files = &self.sections["files"];
        let strings = &self.sections["strings"];
        let mut paths = Vec::with_capacity(files.length / FILE_RECORD_SIZE);
        for index in 0..files.length / FILE_RECORD_SIZE {
            let base = files.offset + index * FILE_RECORD_SIZE;
            let path = self.file_at(index)?;
            let digest: [u8; 32] = self.bytes.as_slice()[base + 16..base + 48]
                .try_into()
                .map_err(|_| SnapshotError::Invalid("file digest bounds".into()))?;
            let _ = strings;
            paths.push((path, digest));
        }
        Ok(paths)
    }
}

pub fn manifest() -> serde_json::Value {
    serde_json::json!({
        "schema": "simplicio.fast.engine-manifest/v1",
        "engine": "rust",
        "version": env!("CARGO_PKG_VERSION"),
        "status": "available",
        "reference": false,
        "fallback": false,
        "capabilities": ["version", "stats", "query", "context", "snapshot-read", "segment-map", "segment-write"],
        "formats": ["SFAST001/v2"]
        ,"conformance": {
            "passed": true,
            "digest": "sha256:1318d1ccc7f7cfe6622fd49855fe4f5dfd48771bd1d2d3403545f8d9ec1863cf",
            "corpus_sha256": "15d0f17f2bd3f897f823e75fd08e1a1e4866e8c48f395c41a00688eb8b7d6cbc",
            "source_commit": "54bc8cdea36c1f228e5612d98e5f2773175ab85a",
            "engine_sha256": {
                "python": "e8d0e2cc786e718a98a3a09d1887b222ea9bec59d4efae8aeae050feb28e1965",
                "rust": "9258cc600bc4bda434f3e2e61ed750e665b4b4bd0d3c41db664538df1733a695"
            }
        }
    })
}

/// Compute the v1 projection payload digest for JSON-compatible payloads.
///
/// `serde_json::Map` is ordered by key in this crate, matching the Python
/// projection canonicalizer for the ASCII contract surface.
pub fn projection_payload_digest(payload: &serde_json::Value) -> String {
    format!(
        "sha256:{}",
        hex_bytes(&Sha256::digest(projection_canonical_json(payload)))
    )
}

fn projection_canonical_json(value: &serde_json::Value) -> Vec<u8> {
    let raw = serde_json::to_string(value).expect("JSON value is serializable");
    let mut result = String::with_capacity(raw.len());
    let mut in_string = false;
    let mut escaped = false;
    for character in raw.chars() {
        if !in_string {
            result.push(character);
            if character == '"' {
                in_string = true;
            }
            continue;
        }
        if escaped {
            result.push(character);
            escaped = false;
        } else if character == '\\' {
            result.push(character);
            escaped = true;
        } else if character == '"' {
            result.push(character);
            in_string = false;
        } else if character.is_ascii() {
            result.push(character);
        } else {
            let code = character as u32;
            if code <= 0xffff {
                result.push_str(&format!("\\u{code:04x}"));
            } else {
                let adjusted = code - 0x1_0000;
                let high = 0xd800 + (adjusted >> 10);
                let low = 0xdc00 + (adjusted & 0x3ff);
                result.push_str(&format!("\\u{high:04x}\\u{low:04x}"));
            }
        }
    }
    result.into_bytes()
}

pub fn decode_projection(raw: &[u8]) -> Result<ProjectionEnvelope, SnapshotError> {
    if raw.len() > PROJECTION_MAX_BYTES {
        return Err(SnapshotError::Invalid("projection_size_limit".into()));
    }
    let value: serde_json::Value = serde_json::from_slice(raw)
        .map_err(|_| SnapshotError::Invalid("projection_invalid_json".into()))?;
    validate_projection(&value)?;
    serde_json::from_value(value)
        .map_err(|_| SnapshotError::Invalid("projection_fields_invalid".into()))
}

pub fn encode_projection(envelope: &ProjectionEnvelope) -> Result<Vec<u8>, SnapshotError> {
    let value = serde_json::to_value(envelope)
        .map_err(|_| SnapshotError::Invalid("projection_fields_invalid".into()))?;
    validate_projection(&value)?;
    let mut encoded = projection_canonical_json(&value);
    encoded.push(b'\n');
    Ok(encoded)
}

/// Validate the shared projection envelope without exposing mmap offsets.
pub fn validate_projection(value: &serde_json::Value) -> Result<(), SnapshotError> {
    let object = value
        .as_object()
        .ok_or_else(|| SnapshotError::Invalid("projection_not_object".into()))?;
    if object.get("schema").and_then(serde_json::Value::as_str) != Some(PROJECTION_SCHEMA) {
        return Err(SnapshotError::Invalid(
            "projection_schema_unsupported".into(),
        ));
    }
    let projection_type = object
        .get("projection_type")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| SnapshotError::Invalid("projection_type_invalid".into()))?;
    if !PROJECTION_TYPES.contains(&projection_type) {
        return Err(SnapshotError::Invalid("projection_type_unsupported".into()));
    }
    for field in [
        "producer",
        "producer_schema",
        "generation",
        "stable_handle",
        "schema_version",
        "projection_type_version",
        "producer_version",
        "repository_scope",
        "tenant_scope",
        "domain_scope",
        "source_generation",
        "projection_generation",
        "completeness",
        "fidelity",
    ] {
        if object
            .get(field)
            .and_then(serde_json::Value::as_str)
            .map_or(true, str::is_empty)
        {
            return Err(SnapshotError::Invalid(format!(
                "projection_{field}_invalid"
            )));
        }
    }
    let payload = object
        .get("payload")
        .filter(|value| value.is_object())
        .ok_or_else(|| SnapshotError::Invalid("projection_payload_invalid".into()))?;
    let mut payload_items = 0;
    validate_projection_payload(payload, 0, &mut payload_items)?;
    let expected = object
        .get("payload_sha256")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| SnapshotError::Invalid("projection_digest_missing".into()))?;
    if !is_sha256_digest(expected) {
        return Err(SnapshotError::Invalid("payload_sha256_invalid".into()));
    }
    if projection_payload_digest(payload) != expected {
        return Err(SnapshotError::Invalid("projection_digest_mismatch".into()));
    }
    for field in [
        "stable_handles",
        "capabilities_required",
        "truncation_reasons",
        "tombstones",
    ] {
        if !object.get(field).is_some_and(serde_json::Value::is_array) {
            return Err(SnapshotError::Invalid(format!(
                "projection_{field}_invalid"
            )));
        }
        let values = object
            .get(field)
            .and_then(serde_json::Value::as_array)
            .expect("array checked above");
        if values.len() > PROJECTION_MAX_ITEMS
            || values
                .iter()
                .any(|value| value.as_str().map_or(true, |text| text.trim().is_empty()))
        {
            return Err(SnapshotError::Invalid(format!(
                "projection_{field}_invalid"
            )));
        }
    }
    let stable_handle = object
        .get("stable_handle")
        .and_then(serde_json::Value::as_str)
        .expect("required text field checked above");
    let stable_handles = object
        .get("stable_handles")
        .and_then(serde_json::Value::as_array)
        .expect("array checked above");
    if stable_handles.is_empty()
        || !stable_handles
            .iter()
            .any(|value| value.as_str() == Some(stable_handle))
    {
        return Err(SnapshotError::Invalid(
            "projection_stable_handles_invalid".into(),
        ));
    }
    if let Some(budgets) = object.get("budgets") {
        if !budgets.is_null() {
            let budget_map = budgets
                .as_object()
                .ok_or_else(|| SnapshotError::Invalid("projection_budgets_invalid".into()))?;
            if budget_map.len() > PROJECTION_MAX_ITEMS
                || budget_map
                    .iter()
                    .any(|(key, value)| key.trim().is_empty() || value.as_u64().is_none())
            {
                return Err(SnapshotError::Invalid("projection_budgets_invalid".into()));
            }
        }
    }
    Ok(())
}

fn is_sha256_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_projection_payload(
    value: &serde_json::Value,
    depth: usize,
    items: &mut usize,
) -> Result<(), SnapshotError> {
    if depth > PROJECTION_MAX_DEPTH {
        return Err(SnapshotError::Invalid("projection_depth_limit".into()));
    }
    match value {
        serde_json::Value::Object(map) => {
            *items = items
                .checked_add(map.len())
                .ok_or_else(|| SnapshotError::Invalid("projection_item_limit".into()))?;
            if *items > PROJECTION_MAX_ITEMS {
                return Err(SnapshotError::Invalid("projection_item_limit".into()));
            }
            for key in map.keys() {
                if ["offset", "mmap_offset", "address", "pointer"].contains(&key.as_str()) {
                    return Err(SnapshotError::Invalid("projection_exposes_offset".into()));
                }
            }
            for child in map.values() {
                validate_projection_payload(child, depth + 1, items)?;
            }
        }
        serde_json::Value::Array(values) => {
            *items = items
                .checked_add(values.len())
                .ok_or_else(|| SnapshotError::Invalid("projection_item_limit".into()))?;
            if *items > PROJECTION_MAX_ITEMS {
                return Err(SnapshotError::Invalid("projection_item_limit".into()));
            }
            for child in values {
                validate_projection_payload(child, depth + 1, items)?;
            }
        }
        serde_json::Value::String(text) if text.chars().count() > PROJECTION_MAX_TEXT => {
            return Err(SnapshotError::Invalid("projection_text_limit".into()));
        }
        _ => {}
    }
    Ok(())
}

fn u64_to_usize(value: u64) -> Result<usize, SnapshotError> {
    usize::try_from(value)
        .map_err(|_| SnapshotError::Invalid("64-bit field exceeds platform usize".into()))
}
fn region_valid(offset: usize, length: usize, total: usize) -> bool {
    offset <= total && length <= total.saturating_sub(offset)
}

pub(crate) fn section_bytes<'a>(bytes: &'a [u8], section: &Section) -> &'a [u8] {
    &bytes[section.offset..section.offset + section.length]
}

fn add_index_values(
    values: &[usize],
    symbol_count: usize,
    candidates: &mut BTreeSet<usize>,
) -> Result<(), SnapshotError> {
    for index in values {
        if *index >= symbol_count {
            return Err(SnapshotError::Invalid(
                "persisted index record out of bounds".into(),
            ));
        }
        candidates.insert(*index);
    }
    Ok(())
}

fn validate_persisted_indexes(
    indexes: &PersistedIndexes,
    symbol_count: usize,
) -> Result<(), SnapshotError> {
    for values in indexes
        .exact
        .values()
        .chain(indexes.names.values())
        .chain(indexes.paths.values())
        .chain(indexes.kinds.values())
    {
        if values.iter().any(|value| *value >= symbol_count) {
            return Err(SnapshotError::Invalid(
                "persisted index record out of bounds".into(),
            ));
        }
        if values.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(SnapshotError::Invalid(
                "persisted index records not strictly ordered".into(),
            ));
        }
    }
    Ok(())
}

fn read_text(
    bytes: &[u8],
    strings: &Section,
    offset: usize,
    length: usize,
) -> Result<String, SnapshotError> {
    if !region_valid(offset, length, strings.length) {
        return Err(SnapshotError::Invalid("string bounds out of range".into()));
    }
    String::from_utf8(bytes[strings.offset + offset..strings.offset + offset + length].to_vec())
        .map_err(|_| SnapshotError::Invalid("invalid UTF-8 string".into()))
}

fn truncate_utf8(value: &str, max_bytes: usize) -> String {
    let end = value
        .char_indices()
        .take_while(|(offset, _)| *offset <= max_bytes)
        .map(|(offset, character)| offset + character.len_utf8())
        .take_while(|end| *end <= max_bytes)
        .last()
        .unwrap_or(0);
    value[..end].to_owned()
}

fn kind_name(kind: u32) -> Result<String, SnapshotError> {
    let value = match kind {
        1 => "class",
        2 => "function",
        3 => "async_function",
        4 => "import",
        5 => "namespace",
        6 => "interface",
        7 => "struct",
        8 => "trait",
        9 => "enum",
        _ => return Err(SnapshotError::Invalid("unknown symbol kind".into())),
    };
    Ok(value.into())
}

fn u16_at(bytes: &[u8], offset: usize) -> Result<u16, SnapshotError> {
    let slice = bytes
        .get(offset..offset + 2)
        .ok_or_else(|| SnapshotError::Invalid("truncated integer".into()))?;
    Ok(u16::from_le_bytes([slice[0], slice[1]]))
}

fn u32_at(bytes: &[u8], offset: usize) -> Result<u32, SnapshotError> {
    let slice = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| SnapshotError::Invalid("truncated integer".into()))?;
    Ok(u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
}

fn u64_at(bytes: &[u8], offset: usize) -> Result<u64, SnapshotError> {
    let slice = bytes
        .get(offset..offset + 8)
        .ok_or_else(|| SnapshotError::Invalid("truncated integer".into()))?;
    Ok(u64::from_le_bytes(
        slice.try_into().expect("checked length"),
    ))
}

fn slice32(bytes: &[u8], offset: usize) -> Result<&[u8; 32], SnapshotError> {
    bytes
        .get(offset..offset + 32)
        .and_then(|slice| slice.try_into().ok())
        .ok_or_else(|| SnapshotError::Invalid("truncated checksum".into()))
}

fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub(crate) fn hex_bytes(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_short_input() {
        let result = SnapshotReader::from_bytes(vec![0; HEADER_SIZE - 1]);
        assert!(
            matches!(result, Err(SnapshotError::Invalid(reason)) if reason == "truncated header")
        );
    }

    #[test]
    fn projection_digest_matches_python_ascii_canonical() {
        let value = serde_json::json!({"a": ["x", "y"], "z": 1});
        assert_eq!(
            projection_payload_digest(&value),
            "sha256:747ca7714c7a2b81fcf1b9fac06f8888f25927e768aa57798492846de6a41575"
        );
    }

    #[test]
    fn projection_digest_matches_python_unicode_canonical() {
        let value = serde_json::json!({"text": "café 😀"});
        assert_eq!(
            projection_payload_digest(&value),
            "sha256:f74ab2d3d42d1835c4a48b34c3f2430f236720909a51dc0aa8881b5f0573b012"
        );
    }

    #[test]
    fn projection_validator_rejects_tampered_payload() {
        let payload = serde_json::json!({"a": ["x", "y"], "z": 1});
        let mut envelope = serde_json::json!({
            "schema": PROJECTION_SCHEMA,
            "projection_type": "code",
            "producer": "mapper",
            "producer_schema": "mapper.context/v1",
            "generation": "g1",
            "stable_handle": "symbol:a",
            "payload": payload,
            "payload_sha256": "sha256:747ca7714c7a2b81fcf1b9fac06f8888f25927e768aa57798492846de6a41575",
            "schema_version": "1.0",
            "projection_type_version": "1.0",
            "producer_version": "test",
            "repository_scope": "repo",
            "tenant_scope": "tenant",
            "domain_scope": "code",
            "source_generation": "g1",
            "projection_generation": "g1",
            "config_fingerprint": "",
            "toolchain_fingerprint": "",
            "parser_fingerprint": "",
            "stable_handles": ["symbol:a"],
            "capabilities_required": [],
            "budgets": null,
            "truncation_reasons": [],
            "parent_generation": null,
            "base_generation": null,
            "delta_generation": null,
            "tombstones": [],
            "completeness": "complete",
            "fidelity": "exact",
            "observed_sequence": "",
            "conformance_digest": ""
        });
        assert!(validate_projection(&envelope).is_ok());
        envelope["payload"]["z"] = serde_json::json!(2);
        assert!(matches!(
            validate_projection(&envelope),
            Err(SnapshotError::Invalid(reason)) if reason == "projection_digest_mismatch"
        ));
    }

    #[test]
    fn projection_validator_rejects_private_fields_limits_and_invalid_handles() {
        let payload = serde_json::json!({"pointer": 4});
        let mut envelope = serde_json::json!({
            "schema": PROJECTION_SCHEMA,
            "projection_type": "code",
            "producer": "mapper",
            "producer_schema": "mapper.context/v1",
            "generation": "g1",
            "stable_handle": "symbol:a",
            "payload": payload,
            "payload_sha256": projection_payload_digest(&payload),
            "schema_version": "1.0",
            "projection_type_version": "1.0",
            "producer_version": "test",
            "repository_scope": "repo",
            "tenant_scope": "tenant",
            "domain_scope": "code",
            "source_generation": "g1",
            "projection_generation": "g1",
            "config_fingerprint": "",
            "toolchain_fingerprint": "",
            "parser_fingerprint": "",
            "stable_handles": ["symbol:b"],
            "capabilities_required": [],
            "budgets": null,
            "truncation_reasons": [],
            "parent_generation": null,
            "base_generation": null,
            "delta_generation": null,
            "tombstones": [],
            "completeness": "complete",
            "fidelity": "exact",
            "observed_sequence": "",
            "conformance_digest": ""
        });
        assert!(matches!(
            validate_projection(&envelope),
            Err(SnapshotError::Invalid(reason)) if reason == "projection_exposes_offset"
        ));
        envelope["payload"] = serde_json::json!({"value": "ok"});
        envelope["payload_sha256"] =
            serde_json::Value::String(projection_payload_digest(&envelope["payload"]));
        assert!(matches!(
            validate_projection(&envelope),
            Err(SnapshotError::Invalid(reason)) if reason == "projection_stable_handles_invalid"
        ));
    }

    #[test]
    fn projection_decode_and_encode_round_trip_golden_envelope() {
        let raw = include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../fixtures/projection/v1/code-symbol.json"
        ));
        let envelope = decode_projection(raw).expect("golden envelope should decode");
        assert_eq!(envelope.stable_handle, "code:symbol");
        let encoded = encode_projection(&envelope).expect("golden envelope should encode");
        assert_eq!(encoded.as_slice(), raw);
        assert_eq!(
            decode_projection(&encoded).expect("round trip").payload,
            envelope.payload
        );
    }

    #[test]
    fn relation_queries_validate_streaming_records_and_bound_matches() {
        let relations = br#"[
            {"origin":"other","destination":"target","kind":"definition","confidence":1.0},
            {"origin":"source","destination":"target","kind":"definition","confidence":1.0},
            {"origin":"source","destination":"target","kind":"call","confidence":0.9}
        ]"#;
        let result = relation_section(relations, Some("source"), Some("definition"), 1)
            .expect("relation query should validate");
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].origin, "source");
        assert!(relation_section(
            br#"[{"origin":"source","destination":"target","kind":"call","confidence":2.0}]"#,
            None,
            None,
            1,
        )
        .is_err());
    }

    fn empty_reader() -> SnapshotReader {
        SnapshotReader {
            bytes: SnapshotBytes::Owned(Vec::new()),
            sections: BTreeMap::new(),
            digest: [0; 32],
            indexes: PersistedIndexes {
                exact: BTreeMap::new(),
                names: BTreeMap::new(),
                paths: BTreeMap::new(),
                kinds: BTreeMap::new(),
            },
        }
    }

    #[test]
    fn query_rejects_zero_limit() {
        let result = empty_reader().query("symbol", 0);
        assert!(
            matches!(result, Err(SnapshotError::Invalid(reason)) if reason == "query limit must be positive")
        );
    }

    #[test]
    fn rejects_out_of_bounds_persisted_index() {
        let mut indexes = PersistedIndexes {
            exact: BTreeMap::new(),
            names: BTreeMap::new(),
            paths: BTreeMap::new(),
            kinds: BTreeMap::new(),
        };
        indexes.exact.insert("helper".into(), vec![3]);
        let result = validate_persisted_indexes(&indexes, 3);
        assert!(matches!(
            result,
            Err(SnapshotError::Invalid(reason))
                if reason == "persisted index record out of bounds"
        ));
    }

    #[test]
    fn rejects_unordered_or_duplicate_persisted_index_records() {
        for values in [vec![2, 1], vec![1, 1]] {
            let mut indexes = PersistedIndexes {
                exact: BTreeMap::new(),
                names: BTreeMap::new(),
                paths: BTreeMap::new(),
                kinds: BTreeMap::new(),
            };
            indexes.exact.insert("helper".into(), values);
            let result = validate_persisted_indexes(&indexes, 3);
            assert!(matches!(
                result,
                Err(SnapshotError::Invalid(reason))
                    if reason == "persisted index records not strictly ordered"
            ));
        }
    }

    #[test]
    fn context_rejects_zero_budget() {
        let result = empty_reader().context(Path::new("."), "symbol", 1, 1, 1, 0);
        assert!(
            matches!(result, Err(SnapshotError::Invalid(reason)) if reason == "context limits must be positive")
        );
    }

    #[test]
    fn accepts_the_platform_usize_boundary() {
        let boundary = usize::MAX as u64;
        assert_eq!(
            u64_to_usize(boundary).expect("platform boundary"),
            usize::MAX
        );
        if usize::BITS < 64 {
            assert!(matches!(
                u64_to_usize(u64::MAX),
                Err(SnapshotError::Invalid(reason))
                    if reason == "64-bit field exceeds platform usize"
            ));
        }
    }

    #[test]
    fn truncate_utf8_stays_on_character_boundaries() {
        let truncated = truncate_utf8("café", 4);
        assert_eq!(truncated, "caf");
        assert!(truncated.len() <= 4);
        assert_eq!(truncate_utf8("café", 0), "");
        assert_eq!(truncate_utf8("abcdef", 3), "abc");
    }

    #[test]
    fn manifest_is_versioned() {
        assert_eq!(manifest()["schema"], "simplicio.fast.engine-manifest/v1");
        assert_eq!(manifest()["engine"], "rust");
    }

    #[test]
    fn open_maps_and_validates_a_file_boundary() {
        let path = std::env::temp_dir().join(format!(
            "simplicio-fast-invalid-{}.sfast",
            std::process::id()
        ));
        std::fs::write(&path, vec![0; HEADER_SIZE - 1]).expect("write fixture");
        let result = SnapshotReader::open(&path);
        let _ = std::fs::remove_file(&path);
        assert!(
            matches!(result, Err(SnapshotError::Invalid(reason)) if reason == "truncated header")
        );
    }

    #[test]
    fn segment_reader_maps_and_verifies_one_content_addressed_segment() {
        let directory =
            std::env::temp_dir().join(format!("simplicio-fast-segments-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).expect("create segment fixture");
        let bytes = b"segment-payload";
        let digest = hex_bytes(&Sha256::digest(bytes));
        std::fs::write(directory.join("symbols.seg"), bytes).expect("write segment");
        std::fs::write(
            directory.join("manifest.json"),
            serde_json::json!({
                "schema": "simplicio.fast.segments/v1",
                "segments": [{"name":"symbols","file":"symbols.seg","bytes":bytes.len(),"sha256":digest}]
            })
            .to_string(),
        )
        .expect("write manifest");
        let mapped = SegmentReader::open(&directory)
            .expect("open segment store")
            .map("symbols")
            .expect("map segment");
        assert_eq!(mapped.as_bytes(), bytes);
        assert_eq!(mapped.sha256(), digest);
        drop(mapped);
        std::fs::remove_dir_all(directory).expect("remove segment fixture");
    }

    #[test]
    fn segment_reader_recovers_from_previous_manifest_after_interrupted_swap() {
        let directory = std::env::temp_dir().join(format!(
            "simplicio-fast-segments-recovery-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).expect("create segment fixture");
        let bytes = b"previous-segment";
        let digest = hex_bytes(&Sha256::digest(bytes));
        std::fs::write(directory.join("symbols.seg"), bytes).expect("write segment");
        std::fs::write(directory.join("manifest.json"), b"{interrupted")
            .expect("write interrupted manifest");
        std::fs::write(
            directory.join("manifest.previous.json"),
            serde_json::json!({
                "schema": "simplicio.fast.segments/v1",
                "segments": [{"name":"symbols","file":"symbols.seg","bytes":bytes.len(),"sha256":digest}]
            })
            .to_string(),
        )
        .expect("write previous manifest");

        let mapped = SegmentReader::open(&directory)
            .expect("recover previous manifest")
            .map("symbols")
            .expect("map recovered segment");

        assert_eq!(mapped.as_bytes(), bytes);
        drop(mapped);
        std::fs::remove_dir_all(directory).expect("remove segment fixture");
    }
}

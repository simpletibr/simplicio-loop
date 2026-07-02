# Module: simplicio_mapper

Groups 17 files across 4 detected layers.

## Structure

- Files: 17
- Layers: code, domain, entrypoint, model
- Entry points: `simplicio_mapper/cli.py`
- Tests: none detected

## Files

- `simplicio_mapper/__init__.py`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `simplicio_mapper/_native.py`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `simplicio_mapper/business.py`: Defines exported symbols: _build_glossary, _domain_doc_terms, _extract_invariants, _extract_limits, _extract_pattern_rules. Layers: code
- `simplicio_mapper/cache.py`: Defines exported symbols: FileProcessingCache, __enter__, __exit__, __init__, clear. Layers: code
- `simplicio_mapper/cli.py`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `simplicio_mapper/context_cache.py`: Defines exported symbols: ContextCache, __contains__, __init__, __len__, _load. Layers: code
- `simplicio_mapper/context_pack.py`: Defines exported symbols: _call_graph_edges, _file_symbols, _language_for, _load_json, _range_snippet. Layers: code
- `simplicio_mapper/diagrams.py`: Defines exported symbols: escape_label, render_call_sequence, render_flowchart, render_state_diagram, sanitize_id. Layers: code
- `simplicio_mapper/docsync.py`: Defines exported symbols: _changed_files_from_cache, _changed_files_from_git, _flows_touching, _modules_for_files, _render_global_docs. Layers: code
- `simplicio_mapper/drift.py`: Defines exported symbols: _check_orphan_code, _check_orphan_specs, _check_placeholders, _load_manifest, _read. Layers: code
- `simplicio_mapper/flows.py`: Defines exported symbols: _calls_by_source_file, _dedupe_effects, _derive_flow, _flow_id, _flow_kind. Layers: code
- `simplicio_mapper/history.py`: Defines exported symbols: _compute_delta, _digest_from_artifacts, _gc, _git_head, _hash_obj. Layers: code
- `simplicio_mapper/mapper.py`: Defines exported symbols: _agent_id_from_seed, _brown_hilbert_address, _build_agent_tree, _build_brown_hilbert_map, _build_file_inventory. Layers: code
- `simplicio_mapper/mechanical_edit.py`: Defines exported symbols: _absolute, _must_contain, _read_bytes_sample, _sha256_text, build_context. Layers: code
- `simplicio_mapper/models.py`: Defines domain, data or schema structures. Layers: domain, model
- `simplicio_mapper/query.py`: Defines exported symbols: _business_rules, _callees, _callers, _edge_view, _impact. Layers: code
- `simplicio_mapper/survey.py`: Defines exported symbols: _conventions, _detect_run_commands, _fan_in_by_module, _help_sources, _read_json_safe. Layers: code

## Public Symbols

- `CodeEntity`
- `ContextCache`
- `FileProcessingCache`
- `PrecedentItem`
- `ProjectFile`
- `__contains__`
- `__enter__`
- `__exit__`
- `__init__`
- `__len__`
- `_absolute`
- `_acquire_index_lock`
- `_agent_id_from_seed`
- `_artifact_evidence`
- `_artifact_paths`
- `_artifacts_exist`
- `_await_terminal`
- `_balanced_span`
- `_brown_hilbert_address`
- `_build_agent_tree`
- `_build_architecture_inventory`
- `_build_backend_face`
- `_build_brown_hilbert_map`
- `_build_call_graph`
- `_build_file_inventory`
- `_build_frontend_face`
- `_build_glossary`
- `_build_precedent_items`
- `_build_symbol_index`
- `_business_rules`
- `_button_label`
- `_cache_summary`
- `_cached_parse_file`
- `_call_expressions`
- `_call_graph_edges`
- `_callees`
- `_callers`
- `_calls_by_source_file`
- `_calls_in_text`
- `_candidate_import_targets`

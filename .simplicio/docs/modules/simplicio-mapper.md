# Module: simplicio_mapper

Groups 6 files across 4 detected layers.

## Structure

- Files: 6
- Layers: code, domain, entrypoint, model
- Entry points: `simplicio_mapper/cli.py`
- Tests: none detected

## Files

- `simplicio_mapper/__init__.py`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `simplicio_mapper/_native.py`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `simplicio_mapper/cache.py`: Defines exported symbols: FileProcessingCache, __enter__, __exit__, __init__, clear. Layers: code
- `simplicio_mapper/cli.py`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `simplicio_mapper/mapper.py`: Defines exported symbols: _build_architecture_inventory, _build_call_graph, _build_file_inventory, _build_precedent_items, _build_symbol_index. Layers: code
- `simplicio_mapper/models.py`: Defines domain, data or schema structures. Layers: domain, model

## Public Symbols

- `CodeEntity`
- `FileProcessingCache`
- `PrecedentItem`
- `ProjectFile`
- `__enter__`
- `__exit__`
- `__init__`
- `_artifact_paths`
- `_artifacts_exist`
- `_balanced_span`
- `_build_architecture_inventory`
- `_build_call_graph`
- `_build_file_inventory`
- `_build_precedent_items`
- `_build_symbol_index`
- `_cached_parse_file`
- `_call_expressions`
- `_candidate_import_targets`
- `_collect_architecture_signals`
- `_collect_entities`
- `_collect_text_files`
- `_detect_changed_files`
- `_emit_index_json`
- `_endpoint_files`
- `_endpoint_inventory_for`
- `_extract_angular_screen_entries`
- `_extract_csharp_server_routes`
- `_extract_python_routes`
- `_extract_route_screens_from_array`
- `_extract_snippet`
- `_extract_text_client_calls`
- `_extract_text_constants`
- `_file_ref`
- `_freshness_signature`
- `_git_signature`
- `_git_status_map`
- `_group_modules`
- `_hash_text`
- `_importance_for`
- `_index_result`

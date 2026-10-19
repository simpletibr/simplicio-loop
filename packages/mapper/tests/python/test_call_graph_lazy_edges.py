"""The lazy call-graph build emits the payload of the eager build, byte for byte (#1631).

``_legacy_build_call_graph`` is the eager implementation frozen as it stood before the lazy edges: it builds
a full edge for every distinct candidate and sorts them all, then keeps the first ``edge_limit``. The public
``_build_call_graph`` must return the same payload at every limit, including limits that cut a tie group
of edges that share the sort key (type, source, target, symbol, line).
"""

from __future__ import annotations

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_call_graph_scaling import TS, _file  # noqa: E402

from simplicio_mapper.mapper.graph import (  # noqa: E402
    _CALL_GRAPH_LANGUAGES,
    _PYTHON_KEYWORDS,
    ARTIFACT_VERSION,
    CALL_GRAPH_SCHEMA,
    _build_call_graph,
    _build_symbol_index,
    _call_expressions,
    _call_graph_edge_limit,
    _call_name_candidate_limit,
    _candidate_identities,
    _candidate_import_targets,
    _content_for,
    _is_skipped_call_name,
    _known_path_suffix_index,
    _name_candidate_order,
    _nearest_symbol,
    resolve_csharp_razor_semantics,
)
from simplicio_mapper.relations import relation_coverage, relation_id  # noqa: E402


def _legacy_build_call_graph(
    cwd,
    files,
    symbol_index,
    generated_at,
    contents=None,
    *,
    edge_limit=None,
    name_candidate_limit=None,
    semantic_adapter=None,
):
    known_paths = {file.path for file in files}
    known_path_index = _known_path_suffix_index(known_paths)
    symbols = list(symbol_index.get("symbols") or [])
    symbols_by_name = {}
    symbols_by_file = {}
    for symbol in symbols:
        symbols_by_name.setdefault(symbol["name"], []).append(symbol)
        symbols_by_file.setdefault(symbol["defined_in"], []).append(symbol)
    for definitions in symbols_by_file.values():
        definitions.sort(key=lambda item: (int(item["line"]), str(item.get("qualified_name") or item.get("name") or "")))
    symbol_lines_by_file = {
        path: [int(item["line"]) for item in definitions]
        for path, definitions in symbols_by_file.items()
    }

    call_sites = []
    definition_sites = {
        (str(item.get("defined_in") or ""), int(item.get("line") or 0), str(item.get("name") or ""))
        for item in symbols
    }
    for file in files:
        if file.language not in _CALL_GRAPH_LANGUAGES:
            continue
        text = _content_for(cwd, file.path, contents)
        for name, line in _call_expressions(text):
            if (file.path, line, name) in definition_sites:
                continue
            if _is_skipped_call_name(name):
                continue
            call_sites.append({"source_file": file.path, "name": name, "line": line})

    semantic_resolution, semantic_by_site = resolve_csharp_razor_semantics(
        cwd, files, symbols, contents, semantic_adapter=semantic_adapter,
    )

    symbols_by_name = {}
    symbols_by_file = {}
    for symbol in symbols:
        symbols_by_name.setdefault(symbol["name"], []).append(symbol)
        symbols_by_file.setdefault(symbol["defined_in"], []).append(symbol)
    for definitions in symbols_by_file.values():
        definitions.sort(key=lambda item: (int(item["line"]), str(item.get("qualified_name") or item.get("name") or "")))
    symbol_lines_by_file = {
        path: [int(item["line"]) for item in definitions]
        for path, definitions in symbols_by_file.items()
    }
    symbols_by_identity = {
        str(item.get("symbol_id") or item.get("qualified_name") or ""): item
        for item in symbols
        if item.get("symbol_id") or item.get("qualified_name")
    }
    file_by_path = {file.path: file for file in files}

    def semantic_target(resolution):
        identity = resolution.get("target_symbol") or resolution.get("symbol_id") or resolution.get("target_symbol_id")
        if isinstance(identity, str) and identity in symbols_by_identity:
            return symbols_by_identity[identity]
        target_file = resolution.get("target_file")
        target_line = resolution.get("target_line")
        target_name = resolution.get("target_name") or resolution.get("name")
        if isinstance(target_file, str) and isinstance(target_line, int) and not isinstance(target_line, bool) and isinstance(target_name, str):
            matches = [
                item for item in symbols_by_file.get(target_file.replace("\\", "/"), [])
                if int(item.get("line") or 0) == target_line and item.get("name") == target_name
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    edges = []
    unresolved = []
    seen = set()
    name_limit = _call_name_candidate_limit(name_candidate_limit)
    capped_by_name = {}
    name_capped_sites = 0
    name_edges_discarded = 0

    def add_edge(edge):
        if not edge.get("target_file") or edge.get("resolution_status") in {None, "unknown"}:
            return
        edge["relation_id"] = relation_id(edge)
        key = edge["relation_id"]
        if key in seen:
            return
        seen.add(key)
        edges.append(edge)

    for file in files:
        for imported in file.imports:
            targets = _candidate_import_targets(imported, file.path, known_paths, known_path_index)
            evidence_class = "import_resolved" if len(targets) == 1 else "lexical_ambiguous"
            candidates = sorted(targets)
            if not candidates:
                unresolved.append({
                    "source_file": file.path,
                    "queried_symbol": imported,
                    "kind": "import",
                })
                continue
            for target in candidates:
                if target == file.path:
                    continue
                add_edge({
                    "type": "imports",
                    "source_file": file.path,
                    "target_file": target,
                    "import": imported,
                    "evidence_class": evidence_class,
                    "resolution_status": "resolved" if len(candidates) == 1 else "ambiguous",
                    "target_candidates": candidates,
                    "provenance": {
                        "method": "import-resolution",
                        "import": imported,
                        "candidate_count": len(candidates),
                        "candidates": candidates,
                    },
                    "confidence": None,
                })

    for call_site in call_sites:
        file = file_by_path[call_site["source_file"]]
        name = call_site["name"]
        line = call_site["line"]
        if name in _PYTHON_KEYWORDS:
            continue
        resolution = semantic_by_site.get((file.path, line, name))
        target = semantic_target(resolution) if resolution is not None else None
        if target is not None:
            targets, observed = [target], 1
            target_candidates = _candidate_identities(targets)
        else:
            if name not in capped_by_name:
                found = [item for item in symbols_by_name.get(name, []) if item.get("defined_in")]
                if len(found) > name_limit:
                    found.sort(key=_name_candidate_order)
                kept = found[:name_limit]
                capped_by_name[name] = (kept, len(found), _candidate_identities(kept))
            targets, observed, target_candidates = capped_by_name[name]
        if observed > len(targets):
            name_capped_sites += 1
            name_edges_discarded += observed - len(targets)
        is_semantic = target is not None and resolution is not None
        is_csharp = file.language in {"csharp", "razor"}
        if not targets:
            unresolved.append({
                "source_file": file.path,
                "line": line,
                "queried_symbol": name,
            })
            continue
        caller = _nearest_symbol(
            symbols,
            file.path,
            line,
            symbols_by_file=symbols_by_file,
            symbol_lines_by_file=symbol_lines_by_file,
        )
        for candidate in targets:
            if candidate["defined_in"] == file.path and candidate["line"] == line:
                continue
            evidence_class = "semantic_resolved" if is_semantic else (
                "heuristic" if is_csharp else "lexical_unique" if observed == 1 else "lexical_ambiguous"
            )
            resolution_status = "resolved" if is_semantic else (
                "inferred" if is_csharp and observed == 1 else "resolved" if observed == 1 else "ambiguous"
            )
            provenance = {
                "method": "roslyn-semantic-service" if is_semantic else "semantic-service-fallback" if is_csharp else "symbol-name-lookup",
                "queried_symbol": name,
                "candidate_count": observed,
                "candidates": target_candidates,
                "caller_resolution": "lexical_nearest" if caller else "unknown",
            }
            if is_semantic:
                provenance.update({
                    "provider": semantic_resolution.get("providers", [None])[0],
                    "provider_version": semantic_resolution.get("provider_versions", [None])[0],
                    "semantic_symbol_id": candidate.get("symbol_id") or candidate.get("qualified_name"),
                    "overload_signature": candidate.get("signature"),
                })
            else:
                provenance["fallback_reason"] = semantic_resolution.get("reasons", []) if is_csharp else None
            add_edge({
                "type": "calls",
                "source_file": file.path,
                "source_symbol": caller["qualified_name"] if caller else None,
                "target_file": candidate["defined_in"],
                "target_symbol": candidate.get("symbol_id") or candidate["qualified_name"],
                "line": line,
                "target_candidates": target_candidates,
                "evidence_class": evidence_class,
                "resolution_status": resolution_status,
                "provenance": provenance,
                "confidence": None,
            })

    symbol_index["semantic_resolution"] = semantic_resolution

    limit = _call_graph_edge_limit(edge_limit)
    ordered_edges = sorted(edges, key=lambda item: (
        item.get("source_file") or "",
        item.get("target_file") or "",
        item.get("type") or "",
        item.get("target_symbol") or item.get("import") or "",
        item.get("line") or 0,
        item.get("relation_id") or "",
    ))
    emitted_edges = ordered_edges[:limit]
    unresolved.sort(key=lambda item: (
        str(item.get("source_file") or ""),
        int(item.get("line") or 0),
        str(item.get("queried_symbol") or ""),
    ))
    payload = {
        "schema": CALL_GRAPH_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_symbol_index": ".simplicio-loop/symbol-index.json",
        "edges": emitted_edges,
        "counts": {
            "edges": len(emitted_edges),
            "imports": len([item for item in emitted_edges if item["type"] == "imports"]),
            "calls": len([item for item in emitted_edges if item["type"] == "calls"]),
        },
        "coverage": relation_coverage(
            emitted_edges,
            observed_edges=len(ordered_edges),
            edge_limit=limit,
            name_candidate_limit=name_limit,
            name_capped_call_sites=name_capped_sites,
            name_edges_discarded=name_edges_discarded,
        ),
        "semantic_resolution": semantic_resolution,
    }
    if unresolved:
        payload["unresolved"] = unresolved
    return payload


Repo = tuple[list, dict[str, str], dict[tuple[str, str], str]]


def _tie_repo() -> Repo:
    """Two names reach one symbol id on one line: ``x`` (candidates T, U) and ``y`` (candidate T).

    Their edges share the sort key (source, target file, type, target symbol, line) but differ in the candidate
    list, so the edge limit can cut inside a tie group.
    """
    contents = {
        "a.py": "def x():\n    return 1\n\ndef y():\n    return 2\n",
        "b.py": "def x():\n    return 3\n",
        "main.py": (
            "def run():\n"
            "    x() + y()\n"
            "    x() + x()\n"
            "    x()\n"
            "\n"
            "def go():\n"
            "    return x() + y()\n"
        ),
    }
    files = [_file(path, "python") for path in contents]
    symbol_ids = {("a.py", "x"): "T", ("a.py", "y"): "T", ("b.py", "x"): "U"}
    return files, contents, symbol_ids


def _random_repo(seed: int, modules: int = 9, names: int = 5) -> Repo:
    rng = random.Random(seed)
    contents: dict[str, str] = {}
    symbol_ids: dict[tuple[str, str], str] = {}
    for m in range(modules):
        lines = []
        if m and rng.random() < 0.5:
            lines.append(f"from m{rng.randrange(modules)} import n{rng.randrange(names)}")
        for n in range(names):
            if rng.random() < 0.6:
                lines.append(f"def n{n}():\n    return {m}\n")
                symbol_ids[(f"m{m}.py", f"n{n}")] = f"id{rng.randrange(3)}"
        for caller in range(rng.randrange(1, 4)):
            lines.append(f"def c{caller}():")
            for _ in range(rng.randrange(1, 4)):
                pieces = [f"n{rng.randrange(names)}()" for _ in range(rng.randrange(1, 4))]
                lines.append("    " + " + ".join(pieces))
        contents[f"m{m}.py"] = "\n".join(lines) + "\n"
    files = [_file(path, "python") for path in contents]
    return files, contents, symbol_ids


def _payload(builder, repo: Repo, **kwargs) -> dict:
    files, contents, symbol_ids = repo
    index = _build_symbol_index(".", files, TS, contents)
    for symbol in index["symbols"]:
        identity = symbol_ids.get((symbol["defined_in"], symbol["name"]))
        if identity is not None:
            symbol["symbol_id"] = identity
    return builder(".", files, index, TS, contents, **kwargs)


class LazyEdgesMatchEagerBuildTests(unittest.TestCase):
    def assertSamePayload(self, lazy: dict, eager: dict, context: str) -> None:
        self.assertEqual(lazy, eager, context)
        self.assertEqual(json.dumps(lazy), json.dumps(eager), context)

    def test_every_edge_limit_gives_the_eager_payload(self) -> None:
        repos = {"tie repo": _tie_repo(), "random 1": _random_repo(1), "random 2": _random_repo(2)}
        for label, repo in repos.items():
            for name_limit in (2, 32):
                everything = _payload(_legacy_build_call_graph, repo, edge_limit=10**7, name_candidate_limit=name_limit)
                total = len(everything["edges"])
                self.assertGreaterEqual(total, 5, label)
                keys = [
                    (e["source_file"], e["target_file"], e["type"], e.get("target_symbol") or e.get("import") or "", e.get("line") or 0)
                    for e in everything["edges"]
                ]
                self.assertLess(len(set(keys)), len(keys), f"{label}: no tie on the sort key to cut")
                for limit in range(0, total + 3):
                    eager = _payload(_legacy_build_call_graph, repo, edge_limit=limit, name_candidate_limit=name_limit)
                    lazy = _payload(_build_call_graph, repo, edge_limit=limit, name_candidate_limit=name_limit)
                    self.assertSamePayload(lazy, eager, f"{label} name_limit={name_limit} edge_limit={limit}")

    def test_a_call_repeated_on_one_line_is_one_edge_per_candidate(self) -> None:
        repo = _tie_repo()
        lazy = _payload(_build_call_graph, repo, edge_limit=10**7)
        eager = _payload(_legacy_build_call_graph, repo, edge_limit=10**7)
        self.assertSamePayload(lazy, eager, "tie repo")
        line3 = [e for e in lazy["edges"] if e["source_file"] == "main.py" and e["type"] == "calls" and e["line"] == 3]
        self.assertEqual(sorted(e["target_file"] for e in line3), ["a.py", "b.py"])
        self.assertEqual(lazy["coverage"]["observed_edges"], len(lazy["edges"]))

    def test_limit_zero_emits_nothing_but_counts_every_distinct_edge(self) -> None:
        repo = _tie_repo()
        lazy = _payload(_build_call_graph, repo, edge_limit=0)
        eager = _payload(_legacy_build_call_graph, repo, edge_limit=0)
        self.assertSamePayload(lazy, eager, "limit 0")
        self.assertEqual(lazy["edges"], [])
        self.assertEqual(lazy["counts"], {"edges": 0, "imports": 0, "calls": 0})
        self.assertGreater(lazy["coverage"]["observed_edges"], 0)
        self.assertTrue(lazy["coverage"]["truncated"])


if __name__ == "__main__":
    unittest.main()

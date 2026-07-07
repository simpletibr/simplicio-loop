from __future__ import annotations

import json
import os
import sys

import orjson

from ..business import _business_diagram_svgs, build_business_rules, render_business_rules_markdown
from ..docsync import build_docs_sync
from ..drift import build_spec_drift, render_drift_markdown
from ..flows import _flow_diagram_svgs, build_flow_inventory, render_flow_inventory_markdown
from ..history import diff_snapshots, list_snapshots, maybe_snapshot
from ..mapper import _write_text_stable, build_artifacts, export_architecture_docs, write_architecture_docs
from ..query import run_query
from ..survey import build_survey, render_survey_markdown
from ._index_engine import _print_toon
from ._shared import DOC_HISTORY_SCHEMA


def _run_flows(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    abs_out = os.path.abspath(os.path.join(root, opts["out"]))
    artifacts = build_artifacts(root, output_dir=opts["out"])
    inventory = build_flow_inventory(root, artifacts)
    inventory_path = os.path.join(abs_out, "flow-inventory.json")
    tmp = f"{inventory_path}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(inventory, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
    os.replace(tmp, inventory_path)

    markdown = render_flow_inventory_markdown(inventory)
    doc_path = os.path.join(abs_out, "docs", "flows.md")
    os.makedirs(os.path.dirname(doc_path), exist_ok=True)
    tmp_doc = f"{doc_path}.tmp"
    with open(tmp_doc, "w", encoding="utf-8") as handle:
        handle.write(markdown.rstrip() + "\n")
    os.replace(tmp_doc, doc_path)

    for rel_path, svg in _flow_diagram_svgs(inventory).items():
        _write_text_stable(os.path.join(abs_out, "docs", rel_path), svg)

    if opts["json"]:
        print(json.dumps({**inventory, "doc": doc_path.replace(os.sep, "/")}, sort_keys=True))
    else:
        coverage = inventory["coverage"]
        print(
            f"flows={len(inventory['flows'])} "
            f"entrypoints_total={coverage['entrypoints_total']} "
            f"entrypoints_with_flow={coverage['entrypoints_with_flow']} "
            f"doc={doc_path}"
        )
    return 0


def _run_sync(opts: dict) -> int:
    payload = build_docs_sync(
        opts["root"],
        out_dir=opts["out"],
        range_spec=opts["range"] or None,
        staged=opts["staged"],
        check=opts["check"],
    )
    if not opts["check"]:
        maybe_snapshot(opts["root"], out_dir=opts["out"], trigger="sync", retention=opts["retention"])
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"changed={payload['diff']['files']} "
            f"affected_flows={len(payload['affected_flows'])} "
            f"regenerated={len(payload['regenerated_docs'])} "
            f"needs_review={len(payload['needs_review'])} "
            f"stale={payload['stale']}"
        )
    if opts["check"] and payload["stale"]:
        return 1
    return 0


def _run_history(opts: dict) -> int:
    snapshots = list_snapshots(opts["root"], out_dir=opts["out"])
    if opts["json"]:
        print(
            json.dumps({"schema": "simplicio.doc-history-index/v1", "snapshots": snapshots}, sort_keys=True)
        )
    else:
        if not snapshots:
            print("no snapshots yet — run map/sync to create the first one")
        for snapshot in snapshots:
            print(f"{snapshot['id']}  {snapshot['created_at']}  {snapshot['summary']}")
    return 0


def _run_diff(opts: dict) -> int:
    if not opts["from_id"] or not opts["to_id"]:
        print("diff requires --from <id> --to <id>", file=sys.stderr)
        return 2
    try:
        payload = diff_snapshots(opts["root"], opts["out"], opts["from_id"], opts["to_id"])
    except ValueError as error:
        if opts["json"]:
            print(json.dumps({"schema": DOC_HISTORY_SCHEMA, "error": str(error)}, sort_keys=True))
        else:
            print(f"diff failed: {error}", file=sys.stderr)
        return 1
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"from={payload['from']} to={payload['to']}")
        print(
            f"modules: +{len(payload['modules']['added'])} -{len(payload['modules']['removed'])} ~{len(payload['modules']['changed'])}"
        )
        print(
            f"dependencies: +{len(payload['dependencies']['added'])} -{len(payload['dependencies']['removed'])}"
        )
        print(
            f"flows: +{len(payload['flows']['added'])} -{len(payload['flows']['removed'])} ~{len(payload['flows']['changed'])}"
        )
        print(f"symbols: +{payload['symbols']['added']} -{payload['symbols']['removed']}")
    return 0


def _run_business(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    abs_out = os.path.abspath(os.path.join(root, opts["out"]))
    artifacts = build_artifacts(root, output_dir=opts["out"])
    payload = build_business_rules(root, artifacts)

    rules_path = os.path.join(abs_out, "business-rules.json")
    tmp = f"{rules_path}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
    os.replace(tmp, rules_path)

    doc_path = os.path.join(abs_out, "docs", "business-flows.md")
    os.makedirs(os.path.dirname(doc_path), exist_ok=True)
    tmp_doc = f"{doc_path}.tmp"
    with open(tmp_doc, "w", encoding="utf-8") as handle:
        handle.write(render_business_rules_markdown(payload).rstrip() + "\n")
    os.replace(tmp_doc, doc_path)

    for rel_path, svg in _business_diagram_svgs(payload).items():
        _write_text_stable(os.path.join(abs_out, "docs", rel_path), svg)

    if opts["json"]:
        print(json.dumps({**payload, "doc": doc_path.replace(os.sep, "/")}, sort_keys=True))
    else:
        print(
            f"rules={len(payload['rules'])} "
            f"state_machines={len(payload['state_machines'])} "
            f"glossary={len(payload['glossary'])} "
            f"doc={doc_path}"
        )
    return 0


def _run_survey(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    abs_out = os.path.abspath(os.path.join(root, opts["out"]))
    artifacts = build_artifacts(root, output_dir=opts["out"])
    flow_inventory = build_flow_inventory(root, artifacts)
    business_rules = build_business_rules(root, artifacts)
    survey = build_survey(root, artifacts, flow_inventory, business_rules)

    doc_path = os.path.join(abs_out, "docs", "onboarding.md")
    os.makedirs(os.path.dirname(doc_path), exist_ok=True)
    markdown = render_survey_markdown(survey)
    tmp_doc = f"{doc_path}.tmp"
    with open(tmp_doc, "w", encoding="utf-8") as handle:
        handle.write(markdown.rstrip() + "\n")
    os.replace(tmp_doc, doc_path)

    copied_to = None
    if opts["target"]:
        copied_to = os.path.abspath(os.path.join(root, opts["target"]))
        os.makedirs(os.path.dirname(copied_to) or ".", exist_ok=True)
        with open(copied_to, "w", encoding="utf-8") as handle:
            handle.write(markdown.rstrip() + "\n")

    if opts["json"]:
        print(
            json.dumps(
                {
                    **survey,
                    "doc": doc_path.replace(os.sep, "/"),
                    "target": copied_to.replace(os.sep, "/") if copied_to else None,
                },
                sort_keys=True,
            )
        )
    else:
        print(
            f"reading_order={len(survey['reading_order'])} "
            f"top_flows={len(survey['top_flows'])} "
            f"glossary={len(survey['glossary'])} "
            f"doc={doc_path}"
        )
    return 0


def _run_drift(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    abs_out = os.path.abspath(os.path.join(root, opts["out"]))
    payload = build_spec_drift(root, out_dir=opts["out"], threshold=opts["threshold"])

    if not opts["check"]:
        report_path = os.path.join(abs_out, "spec-drift.json")
        tmp = f"{report_path}.tmp"
        with open(tmp, "wb") as handle:
            handle.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
        os.replace(tmp, report_path)

        doc_path = os.path.join(abs_out, "docs", "spec-drift.md")
        os.makedirs(os.path.dirname(doc_path), exist_ok=True)
        tmp_doc = f"{doc_path}.tmp"
        with open(tmp_doc, "w", encoding="utf-8") as handle:
            handle.write(render_drift_markdown(payload).rstrip() + "\n")
        os.replace(tmp_doc, doc_path)

    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        score = payload["score"]
        print(
            f"findings={score['drift_findings']} threshold={score['threshold']} "
            f"{'PASS' if score['pass'] else 'FAIL'}"
        )
        for finding in payload["findings"]:
            target = f"{finding['target']}:{finding['line']}" if finding.get("line") else finding["target"]
            print(f"[{finding['severity']}] {finding['check']}: {target} — {finding['message']}")
    if opts["check"] and not payload["score"]["pass"]:
        return 1
    return 0


def _run_ask(opts: dict) -> int:
    if not opts["verb"]:
        print(
            "ask requires a verb: callers|callees|reaches|impact|flows|rules|tests-for|term|precedent",
            file=sys.stderr,
        )
        return 2
    try:
        payload = run_query(
            opts["root"],
            out_dir=opts["out"],
            verb=opts["verb"],
            arg=opts["query_arg"] or None,
            depth=opts["depth"],
            limit=opts["limit"],
            effect=opts["effect"] or None,
            category=opts["category"] or None,
        )
    except ValueError as error:
        print(f"ask failed: {error}", file=sys.stderr)
        return 2
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"verb={opts['verb']} total={payload['total']}")
        if payload.get("note"):
            print(f"note: {payload['note']}")
        for item in payload["results"]:
            print(item)
    return 0


def _run_docs(opts: dict) -> int:
    payload = write_architecture_docs(opts["root"], output_dir=opts["out"])
    maybe_snapshot(opts["root"], out_dir=opts["out"], trigger="docs", retention=opts["retention"])
    if opts["json"]:
        print(
            json.dumps(
                {
                    "schema": "simplicio.architecture-docs/v1",
                    "docs_root": payload["docs_root"].replace(os.sep, "/"),
                    "paths": [path.replace(os.sep, "/") for path in payload["paths"]],
                    "counts": payload["counts"],
                },
                sort_keys=True,
            )
        )
    else:
        print(f"docs={payload['counts']['files']} root={payload['docs_root']}")
    return 0


def _run_export_docs(opts: dict) -> int:
    payload = export_architecture_docs(opts["root"], opts["target"], output_dir=opts["out"])
    if opts["json"]:
        print(
            json.dumps(
                {
                    "schema": "simplicio.docs-export/v1",
                    "target": payload["target"].replace(os.sep, "/"),
                    "paths": [path.replace(os.sep, "/") for path in payload["paths"]],
                    "counts": payload["counts"],
                },
                sort_keys=True,
            )
        )
    else:
        print(f"exported={payload['counts']['files']} target={payload['target']}")
    return 0

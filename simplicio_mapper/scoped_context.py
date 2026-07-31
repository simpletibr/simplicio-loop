"""Foreground scoped context generation for Mapper/Loop integration."""
# The compact implementation keeps deterministic branches together; only style diagnostics are suppressed.
# ruff: noqa: E701, E702
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCOPED_HANDOFF_SCHEMA="simplicio.mapper-scoped-context/v1"
BACKGROUND_SCHEMA="simplicio.mapper-scoped-background/v1"
REASON_TARGET_OUTSIDE_SCOPE="TARGET_OUTSIDE_SCOPE"
REASON_ROOT_MISMATCH="ROOT_MISMATCH"
REASON_SCOPED_ARTIFACT_STALE="SCOPED_ARTIFACT_STALE"
REASON_CORRIDOR_INCOMPLETE="CORRIDOR_INCOMPLETE"
REASON_CACHE_INCOMPATIBLE="CACHE_INCOMPATIBLE"
REASON_BACKGROUND_PENDING="BACKGROUND_PENDING"
_ARTIFACTS=("project-map.json","symbol-index.json","call-graph.json","architecture-inventory.json")
_MANIFESTS={"pyproject.toml","package.json","Cargo.toml","go.mod","pom.xml","requirements.txt"}

class ScopedContextError(ValueError):
    def __init__(self, reason_code:str, detail:str="")->None:
        self.reason_code=reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)

@dataclass(frozen=True)
class ScopedRequest:
    repo_root:str
    scope_root:str
    target_hints:tuple[str,...]=()
    task_fingerprint:str=""
    context_budget:int=8000
    attempt_id:str=""
    configuration_fingerprint:str=""
    @classmethod
    def normalize(cls, repo_root:str, *, scope_root:str|None=None,
                  target_hints:Sequence[str]=(), task_fingerprint:str="",
                  context_budget:int=8000, attempt_id:str="",
                  configuration_fingerprint:str="")->ScopedRequest:
        repo=Path(repo_root).expanduser().resolve()
        scope=Path(scope_root or repo).expanduser().resolve()
        try: scope.relative_to(repo)
        except ValueError as e: raise ScopedContextError(REASON_ROOT_MISMATCH,str(scope)) from e
        if context_budget<1: raise ScopedContextError(REASON_CORRIDOR_INCOMPLETE,"context_budget")
        hints=[]
        for raw in target_hints:
            hint=str(raw).strip()
            if not hint: continue
            path=(Path(hint) if Path(hint).is_absolute() else scope/hint).resolve()
            try: hints.append(path.relative_to(scope).as_posix())
            except ValueError as e: raise ScopedContextError(REASON_TARGET_OUTSIDE_SCOPE,hint) from e
        return cls(repo.as_posix(),scope.as_posix(),tuple(sorted(set(hints))),
                   str(task_fingerprint).strip(),int(context_budget),str(attempt_id).strip(),
                   str(configuration_fingerprint).strip())

def _canon(v:Any)->bytes:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def _sha(v:Any)->str: return hashlib.sha256(_canon(v)).hexdigest()
def _norm(v:Any)->str: return str(v or "").replace("\\","/").lstrip("./")
def _in_scope(path:str,scope:str)->bool:
    path,scope=_norm(path),_norm(scope)
    if not scope: return True
    return path==scope or path.startswith(scope.rstrip("/")+"/")
def _read(path:Path)->dict[str,Any]:
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,json.JSONDecodeError) as e: raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE,str(path)) from e
    if not isinstance(value,dict): raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE,str(path))
    return value
def _git(root:Path,*args:str)->str:
    try: p=subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,timeout=10,stdin=subprocess.DEVNULL)
    except (OSError,subprocess.SubprocessError): return ""
    return p.stdout.strip() if p.returncode==0 else ""
def _atomic(path:Path,value:Mapping[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f".tmp-{os.getpid()}")
    tmp.write_bytes(_canon(value)+b"\n"); os.replace(tmp,path)

def _span(root:Path,path:str)->dict[str,Any]:
    try: raw=(root/path).read_bytes()
    except OSError as e: raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE,path) from e
    digest=hashlib.sha256(raw).hexdigest()
    return {"path":path,"source_sha256":digest,"bytes":len(raw),
            "spans":[{"start_line":1,"end_line":max(1,min(120,len(raw.splitlines()))),"source_sha256":digest}]}

def build_scoped_context(root:str, *, scope_root:str|None=None, target_hints:Sequence[str]=(),
                         task_fingerprint:str="", context_budget:int=8000, attempt_id:str="",
                         configuration_fingerprint:str="", out:str=".simplicio",
                         changed_paths:Sequence[str]=(), cache_root:str|None=None)->dict[str,Any]:
    """Build a ready foreground corridor; deep work is an explicit pending contract."""
    wall,cpu=time.perf_counter(),time.process_time()
    request=ScopedRequest.normalize(root,scope_root=scope_root,target_hints=target_hints,
        task_fingerprint=task_fingerprint,context_budget=context_budget,attempt_id=attempt_id,
        configuration_fingerprint=configuration_fingerprint)
    repo=Path(request.repo_root); artifact_dir=repo/out
    artifacts={}; artifact_bytes=0
    for name in _ARTIFACTS:
        path=artifact_dir/name
        if path.exists(): artifacts[name]=_read(path); artifact_bytes+=path.stat().st_size
    project=artifacts.get("project-map.json",{})
    files={_norm(x.get("path")):x for x in project.get("files",[]) if isinstance(x,Mapping) and x.get("path")}
    scope=Path(request.scope_root).relative_to(repo).as_posix() or "."
    selected=set(); why={}; reason=""
    symbols=artifacts.get("symbol-index.json",{}).get("symbols",[])
    for hint in request.target_hints:
        if hint in files or (repo / hint).is_file():
            files.setdefault(hint, {"path": hint})
            selected.add(hint); why.setdefault(hint,[]).append("explicit_target"); continue
        matches=sorted({_norm(x.get("defined_in")) for x in symbols if isinstance(x,Mapping) and x.get("defined_in") and
                        (_norm(x.get("defined_in")) in files) and
                        (str(x.get("name",""))==hint or str(x.get("qualified_name",""))==hint)})
        if not matches: reason=REASON_CORRIDOR_INCOMPLETE; selected=set(); why={}; break
        for path in matches: selected.add(path); why.setdefault(path,[]).append("target_symbol")
    initial=set(selected)
    for edge in artifacts.get("call-graph.json",{}).get("edges",[]):
        if not isinstance(edge,Mapping): continue
        source=_norm(edge.get("source_file") or edge.get("source"))
        target=_norm(edge.get("target_file") or edge.get("target"))
        if source in initial and target in files and _in_scope(target,scope):
            selected.add(target); why.setdefault(target,[]).append("direct_callee_or_import")
        if target in initial and source in files and _in_scope(source,scope):
            selected.add(source); why.setdefault(source,[]).append("direct_caller_or_import")
    stems={Path(p).stem.casefold() for p in initial}
    for path in files:
        if not _in_scope(path,scope): continue
        if Path(path).name in _MANIFESTS: selected.add(path); why.setdefault(path,[]).append("manifest")
        if any(x in path.casefold() for x in ("test","spec")) and any(x in path.casefold() for x in stems):
            selected.add(path); why.setdefault(path,[]).append("nearest_test")
    changed={_norm(x) for x in changed_paths}
    for path in changed & set(files):
        if _in_scope(path,scope): selected.add(path); why.setdefault(path,[]).append("changed_path")
    selected={p for p in selected if _in_scope(p,scope)}
    rows=[_span(repo,p) for p in sorted(selected)]
    selected_paths=[{"path":r["path"],"why":sorted(set(why.get(r["path"],["corridor"]))),"source_sha256":r["source_sha256"]} for r in rows]
    revision=_git(repo,"rev-parse","HEAD") or str(project.get("generated_at",""))
    tree=_git(repo,"rev-parse","HEAD^{tree}") or ""
    product=project.get("product",{}); repo_id=str(product.get("name") if isinstance(product,Mapping) and product.get("name") else repo.name)
    fingerprint=_sha({"repo_id":repo_id,"revision":revision,"tree":tree,"config":request.configuration_fingerprint,
                      "targets":request.target_hints,"selected":selected_paths})
    base=Path(cache_root or os.environ.get("SIMPLICIO_MAPPER_SCOPED_CACHE",str(Path.home()/".simplicio/mapper/scoped-context-cache"))).expanduser()
    cache=base/f"{fingerprint}.json"; hit=False
    if cache.exists():
        try: hit=_read(cache).get("generation",{}).get("input_fingerprint")==fingerprint
        except ScopedContextError: reason=REASON_CACHE_INCOMPATIBLE
    generation=_sha({"input_fingerprint":fingerprint,"selected_paths":selected_paths})
    payload={"schema":SCOPED_HANDOFF_SCHEMA,"ready":bool(selected) and not reason,
      "reason_code":reason or REASON_BACKGROUND_PENDING,
      "repository":{"root":repo.as_posix(),"scope_root":Path(request.scope_root).as_posix(),"repository_id":repo_id,"revision":revision,"tree":tree},
      "request":{"target_hints":list(request.target_hints),"task_fingerprint":request.task_fingerprint,
                 "context_budget":request.context_budget,"configuration_fingerprint":request.configuration_fingerprint},
      "generation":{"id":generation,"input_fingerprint":fingerprint,"immutable":True,"producer":"simplicio-mapper"},
      "attempt":{"id":request.attempt_id,"generation":generation,"pinned":bool(request.attempt_id)},
      "selected_paths":selected_paths,"spans":rows,
      "metrics":{"wall_ms":round((time.perf_counter()-wall)*1000,3),"cpu_ms":round((time.process_time()-cpu)*1000,3),
                 "files_parsed":0 if hit else len(artifacts),"files_reused":len(artifacts) if hit else 0,
                 "artifact_bytes":artifact_bytes,"cache":"hit" if hit else "miss","changed_paths":sorted(changed)},
      "background":{"schema":BACKGROUND_SCHEMA,"state":"pending","work_id":_sha({"repo_id":repo_id,"revision":revision,"scope":scope}),
                    "contract":"explicit-background-deep-scan","command":f"simplicio-mapper handoff {repo.as_posix()} --await"},
      "completeness":{"limitations":["foreground corridor excludes unrelated files"],
                      "deep_required_for":["repository-wide completeness"]}}
    _atomic(cache,payload); return payload


def run_scoped_context_cli(argv: Sequence[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="simplicio-mapper scoped-handoff")
    parser.add_argument("root")
    parser.add_argument("--scope-root")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--task-fingerprint", default="")
    parser.add_argument("--configuration-fingerprint", default="")
    parser.add_argument("--attempt-id", default="")
    parser.add_argument("--context-budget", type=int, default=8000)
    parser.add_argument("--out", default=".simplicio")
    parser.add_argument("--cache-root")
    args = parser.parse_args(list(argv))
    try:
        payload = build_scoped_context(
            args.root,
            scope_root=args.scope_root,
            target_hints=args.target,
            task_fingerprint=args.task_fingerprint,
            context_budget=args.context_budget,
            attempt_id=args.attempt_id,
            configuration_fingerprint=args.configuration_fingerprint,
            out=args.out,
            changed_paths=args.changed_path,
            cache_root=args.cache_root,
        )
    except ScopedContextError as error:
        payload = {
            "schema": SCOPED_HANDOFF_SCHEMA,
            "ready": False,
            "reason_code": error.reason_code,
            "detail": str(error),
        }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ready"] else 1

__all__=["BACKGROUND_SCHEMA","REASON_BACKGROUND_PENDING","REASON_CACHE_INCOMPATIBLE","REASON_CORRIDOR_INCOMPLETE",
         "REASON_ROOT_MISMATCH","REASON_SCOPED_ARTIFACT_STALE","REASON_TARGET_OUTSIDE_SCOPE",
         "SCOPED_HANDOFF_SCHEMA","ScopedContextError","ScopedRequest","build_scoped_context"]

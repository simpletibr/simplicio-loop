import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(REPO, "scripts", "flow_audit.py")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip(), encoding="utf-8")


def _run(args, cwd):
    return subprocess.run([sys.executable, FLOW] + args, capture_output=True, text=True, cwd=cwd)


def test_flow_audit_fails_on_frontend_call_without_endpoint(tmp_path):
    _write(tmp_path / "frontend" / "Checkout.tsx", """
export function Checkout() {
  return <button onClick={() => fetch("/api/checkout", { method: "POST" })}>Pay</button>
}
""")
    _write(tmp_path / "backend" / "routes.py", """
@app.get("/api/health")
def health():
    return {"ok": True}
""")

    r = _run(["audit", str(tmp_path), "--fail-on", "high"], cwd=REPO)
    assert r.returncode == 1, r.stdout
    assert "frontend_call_without_backend_endpoint" in r.stdout, r.stdout


def test_flow_audit_detects_backend_stub(tmp_path):
    _write(tmp_path / "frontend" / "Login.tsx", """
export function Login() {
  return <button onClick={() => fetch("/api/login", { method: "POST" })}>Login</button>
}
""")
    _write(tmp_path / "backend" / "routes.py", """
@app.post("/api/login")
def login():
    raise NotImplementedError("TODO")
""")

    r = _run(["audit", str(tmp_path), "--fail-on", "high"], cwd=REPO)
    assert r.returncode == 1, r.stdout
    assert "backend_endpoint_stub" in r.stdout, r.stdout


def test_flow_audit_flags_write_endpoint_without_persistence_call(tmp_path):
    # #79: an endpoint that never reaches its repository/ORM/SQL is a real integration defect —
    # scoped to non-GET (write) endpoints; medium (not high) since it's heuristic.
    _write(tmp_path / "backend" / "routes.py", """
@app.post("/api/orders")
def create_order():
    order = Order(item=request.json["item"])
    return {"ok": True}
""")
    r = _run(["audit", str(tmp_path), "--json"], cwd=REPO)
    assert r.returncode == 0, r.stdout  # medium-only findings don't fail the default (high) gate
    assert "backend_endpoint_without_persistence_call" in r.stdout, r.stdout

    r_medium = _run(["audit", str(tmp_path), "--fail-on", "medium"], cwd=REPO)
    assert r_medium.returncode == 1, r_medium.stdout
    assert "backend_endpoint_without_persistence_call" in r_medium.stdout, r_medium.stdout


def test_flow_audit_does_not_flag_write_endpoint_with_persistence_call(tmp_path):
    _write(tmp_path / "backend" / "routes.py", """
@app.post("/api/orders")
def create_order():
    order = Order(item=request.json["item"])
    db.session.add(order)
    db.session.commit()
    return {"ok": True}
""")
    r = _run(["audit", str(tmp_path), "--json"], cwd=REPO)
    assert "backend_endpoint_without_persistence_call" not in r.stdout, r.stdout


def test_flow_audit_passes_matched_non_stub_flow(tmp_path):
    _write(tmp_path / "frontend" / "Login.tsx", """
export function Login() {
  return <button onClick={() => fetch("/api/login", { method: "POST" })}>Login</button>
}
""")
    _write(tmp_path / "backend" / "routes.py", """
@app.post("/api/login")
def login():
    return {"ok": True}
""")

    r = _run(["audit", str(tmp_path), "--fail-on", "high"], cwd=REPO)
    assert r.returncode == 0, r.stdout
    assert "flow-audit: PASS" in r.stdout, r.stdout


def test_flow_audit_ignores_pytest_temp_directories(tmp_path):
    from importlib.util import module_from_spec, spec_from_file_location
    import sys

    spec = spec_from_file_location("flow_audit", FLOW)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _write(tmp_path / ".pytest-fixture" / "backend" / "routes.py", "@app.post('/bad')\ndef bad():\n    raise NotImplementedError\n")
    _write(tmp_path / "backend" / "routes.py", "@app.get('/ok')\ndef ok():\n    return {}\n")
    files = [path.relative_to(tmp_path).as_posix() for path in module.iter_files(tmp_path)]
    assert ".pytest-fixture/backend/routes.py" not in files
    assert "backend/routes.py" in files


# --- extract_endpoints: Django path()/re_path() e literais de string em .py ------------------------------------

_FLOW_MODULE = []


def _flow():
    """scripts/flow_audit.py as a module, loaded once."""
    if not _FLOW_MODULE:
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("flow_audit", FLOW)
        module = module_from_spec(spec)
        sys.modules[spec.name] = module  # its dataclasses resolve their module through sys.modules
        spec.loader.exec_module(module)
        _FLOW_MODULE.append(module)
    return _FLOW_MODULE[0]


def _routes(text, rel="backend/urls.py"):
    return [(r.method, r.path, r.line) for r in _flow().extract_endpoints(text, rel)]


def test_pathlib_Path_is_not_a_django_route():
    assert _routes('p = Path("x")\nq = pathlib.Path("y/z")\n') == []


def test_real_django_path_is_still_a_route():
    assert _routes('urlpatterns = [\n    path("api/x/", view),\n]\n') == [("ANY", "/api/x", 2)]


def test_django_path_with_other_quotes_and_re_path_is_a_route():
    got = _routes("urlpatterns = [path('a/', v), re_path('^b/$', v)]\n")
    assert [p for _, p, _ in got] == ["/a", "/^b/$"]


def test_path_attribute_calls_are_not_routes():
    assert _routes('a = os.path("c")\nb = self.path("d")\nc = mypath("e")\nd = obj.re_path("f")\n') == []


def test_path_inside_a_string_literal_is_not_a_route():
    assert _routes("msg = 'path(\"a/\")'\n") == []


def test_path_inside_a_docstring_is_not_a_route():
    text = 'def f():\n    """Use path("b/") to route.\n\n    re_path("c/") too.\n    """\n    return 1\n'
    assert _routes(text) == []


def test_path_inside_an_fstring_is_not_a_route():
    assert _routes("n = 1\nmsg = f'path(\"a/{n}\")'\n") == []


def test_route_after_a_docstring_keeps_its_line():
    text = '"""path("doc/")"""\n\nurlpatterns = [\n    path("real/", v),\n]\n'
    assert _routes(text) == [("ANY", "/real", 4)]


def test_decorators_in_python_files_are_still_routes():
    text = (
        '@app.route("/flask", methods=["POST"])\ndef a(): ...\n'
        '@router.get("/fast")\ndef b(): ...\n'
        '@app.post("/fast2")\ndef c(): ...\n'
    )
    assert sorted(_routes(text), key=lambda r: r[2]) == [("POST", "/flask", 1), ("GET", "/fast", 3), ("POST", "/fast2", 5)]


def test_decorators_inside_a_python_string_are_not_routes():
    text = 'DOC = """\n@app.get("/in-doc")\n@app.route("/in-doc2")\n"""\nspring = \'app.post("/x")\'\n'
    assert _routes(text) == []


def test_offsets_survive_non_ascii_text_and_crlf():
    text = 'nome = "ção ção"; x = \'path("a/")\'\r\nurlpatterns = [path("ok/", v)]\r\n'
    assert _routes(text) == [("ANY", "/ok", 2)]


def test_a_route_right_after_a_string_literal_is_not_inside_it():
    # the end of a literal is exclusive: `path(` starting at the very next character is code
    assert _routes('x = "s"path("edge/")\n') == [("ANY", "/edge", 1)]


def test_string_filter_applies_to_python_only():
    # a JS file is not tokenized as Python: `/"/` would open a Python string that swallows `app.get(`
    text = 'const re = /"/; app.get("/js-route", h); const t = "x";\n'
    assert _routes(text, rel="server/app.js") == [("GET", "/js-route", 1)]


def test_unparseable_python_keeps_what_was_tokenized_and_reports_the_rest(tmp_path):
    mod = _flow()
    text = '"""path("doc/")"""\nurlpatterns = [path("real/", v)]\nbad = "unterminated\n'
    refs, err = mod.scan_endpoints(text, "backend/urls.py")
    assert [r.path for r in refs] == ["/real"]  # the docstring before the error is still filtered
    assert err is not None and err[0] == 3, err
    # the audit surfaces it as a (medium) finding instead of swallowing it
    _write(tmp_path / "backend" / "urls.py", text)
    result = mod.audit(tmp_path)
    codes = [(i["code"], i["severity"], i["file"], i["line"]) for i in result["issues"]]
    assert ("python_string_scan_incomplete", "medium", "backend/urls.py", 3) in codes, codes
    assert result["ok"] is True  # medium: surfaced, not a hard fail


def test_clean_python_reports_no_scan_error():
    refs, err = _flow().scan_endpoints('urlpatterns = [path("a/", v)]\n', "backend/urls.py")
    assert err is None and [r.path for r in refs] == ["/a"]


def test_audit_does_not_count_pathlib_or_string_paths_as_endpoints(tmp_path):
    _write(tmp_path / "backend" / "files.py", """
from pathlib import Path
BASE = Path("data")
HELP = 'call path("api/y/") in urls'
""")
    _write(tmp_path / "backend" / "urls.py", """
urlpatterns = [path("api/real/", view)]
""")
    result = _flow().audit(tmp_path)
    assert [e["path"] for e in result["endpoints"]] == ["/api/real"], result["endpoints"]


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_flow_audit")

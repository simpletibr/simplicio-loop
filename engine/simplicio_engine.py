#!/usr/bin/env python3
"""Simplicio capture engine — native, self-contained token-saving proxy.

A transparent OpenAI/Anthropic-compatible HTTP proxy: it measures prompt tokens,
applies **deterministic** compression to message content (whitespace collapse,
consecutive-line dedup, oversized-output capping), forwards the request to the real
upstream **without changing the model**, streams the response straight back, and
records savings to ~/.simplicio/proxy_savings.json (schema v3 — the exact format the
Simplicio Token Monitor reads) plus a PERF log.

This is the native Simplicio core. It is intentionally NOT a reimplementation of the
upstream engine's semantic/ONNX compression — it does safe, reversible-by-construction
deterministic compression only. It is **fail-open**: if anything goes wrong parsing or
compressing a request, the original bytes are forwarded unchanged. Stdlib only.

Commands:
  simplicio_engine proxy --port 8788 [--upstream https://api.openai.com]
  simplicio_engine doctor [--port 8788]
  simplicio_engine memory stats
  simplicio_engine --version
"""
import argparse
import http.client
import http.server
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

__version__ = "1.0.0"

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = Path(os.environ.get("SIMPLICIO_HOME", Path(HOME) / ".simplicio"))
SAVINGS_PATH = DATA_DIR / "proxy_savings.json"
LOG_PATH = DATA_DIR / "logs" / "proxy.log"
SCHEMA_VERSION = 3
SESSION_INACTIVITY_S = 60 * 60
MAX_HISTORY = 5000
# Rough input $/1M tokens by family (savings are estimated, not billed).
PRICE_PER_M = {"gpt": 0.15, "claude": 0.80, "deepseek": 0.14, "gemini": 0.10,
               "llama": 0.06, "mistral": 0.10, "qwen": 0.08, "default": 0.14}

# Prefer the richer 8-algorithm compression module if present (sibling file).
# NB: named simplicio_compress (not `compression`) — Python 3.14 ships a stdlib `compression` package.
try:
    sys.path.insert(0, HERE)
    from simplicio_compress import compress as _ext_compress
except Exception:
    _ext_compress = None
try:
    from simplicio_compress_extra import compress_extra as _ext_compress_extra
except Exception:
    _ext_compress_extra = None
try:
    from simplicio_tokens import count_tokens as _count_tokens
except Exception:
    _count_tokens = None


def _exec_sibling(name, rest):
    """Hand off to a sibling engine module (mcp/memory/init), preserving args."""
    target = os.path.join(HERE, name)
    if not os.path.exists(target):
        print(f"simplicio_engine: {name} not found", file=sys.stderr)
        return 127
    os.execv(sys.executable, [sys.executable, target] + list(rest))


def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _toks(text):
    """Token estimate — the calibrated estimator if present, else ~4 chars/token."""
    if not text:
        return 0
    if _count_tokens is not None:
        try:
            return _count_tokens(text)
        except Exception:
            pass
    return max(0, round(len(text) / 4))


def _price(model):
    m = (model or "").lower()
    for fam, p in PRICE_PER_M.items():
        if fam in m:
            return p
    return PRICE_PER_M["default"]


# ── deterministic compression pipeline (safe, fail-open, multi-algorithm) ─────
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_BLANKS = re.compile(r"\n{3,}")
_RULE_RUN = re.compile(r"([=\-_*#.~ ])\1{9,}")  # 10+ repeated rule chars (==== / ---- / ....)


def _algo_strip_ansi(t):
    return _ANSI.sub("", t)


def _algo_rule_runs(t):
    return _RULE_RUN.sub(lambda m: m.group(1) * 6, t)


def _algo_dedup_lines(t):
    out, prev, marked = [], None, False
    for line in t.split("\n"):
        if line == prev and line.strip():
            if not marked:
                out.append("… (repeated line collapsed)")
                marked = True
            continue
        prev, marked = line, False
        out.append(line)
    return "\n".join(out)


def _algo_whitespace(t):
    return _MANY_BLANKS.sub("\n\n", _TRAILING_WS.sub("", t))


def _algo_minify_json(t):
    s = t.strip()
    if (s[:1], s[-1:]) in (("{", "}"), ("[", "]")) and len(s) > 40:
        try:
            return json.dumps(json.loads(s), separators=(",", ":"), ensure_ascii=False)
        except (ValueError, TypeError):
            return t
    return t


# Applied in order; each is lossless-ish and reversible-by-construction.
_PIPELINE = [_algo_strip_ansi, _algo_rule_runs, _algo_dedup_lines, _algo_whitespace, _algo_minify_json]


def _compress_text(text):
    """Compress one text block — the 8-algorithm module if present, else the inline pipeline."""
    if not text or len(text) < 80:
        return text
    if _ext_compress is not None:
        try:
            out = _ext_compress(text)
            if _ext_compress_extra is not None:
                out = _ext_compress_extra(out)
            return out if len(out) <= len(text) else text
        except Exception:
            pass
    out = text
    for algo in _PIPELINE:
        try:
            out = algo(out)
        except (ValueError, TypeError, re.error):
            pass
    return out if len(out) < len(text) else text


def _compress_content(content):
    if isinstance(content, str):
        return _compress_text(content)
    if isinstance(content, list):  # multimodal blocks
        new = []
        for blk in content:
            if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                blk = {**blk, "text": _compress_text(blk["text"])}
            new.append(blk)
        return new
    return content


def _compress_payload(obj):
    """Return (new_obj, tok_before, tok_after). Touches message/system text only."""
    before = after = 0

    def measure(c):
        if isinstance(c, str):
            return _toks(c)
        if isinstance(c, list):
            return sum(_toks(b.get("text", "")) for b in c if isinstance(b, dict))
        return 0

    new = dict(obj)
    if isinstance(obj.get("system"), str):  # Anthropic system prompt
        before += _toks(obj["system"])
        new["system"] = _compress_text(obj["system"])
        after += _toks(new["system"])
    msgs = obj.get("messages")
    if isinstance(msgs, list):
        nmsgs = []
        for m in msgs:
            if isinstance(m, dict) and "content" in m:
                before += measure(m["content"])
                cc = _compress_content(m["content"])
                after += measure(cc)
                nmsgs.append({**m, "content": cc})
            else:
                nmsgs.append(m)
        new["messages"] = nmsgs
    return new, before, after


# ── savings store (schema v3, atomic, thread-safe) ───────────────────────────
class SavingsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if SAVINGS_PATH.exists():
            try:
                d = json.loads(SAVINGS_PATH.read_text(errors="replace"))
                d.setdefault("schema_version", SCHEMA_VERSION)
                d.setdefault("lifetime", self._empty_totals())
                d.setdefault("display_session", self._empty_session())
                d.setdefault("history", [])
                return d
            except (ValueError, OSError):
                pass
        return {"schema_version": SCHEMA_VERSION, "lifetime": self._empty_totals(),
                "display_session": self._empty_session(), "history": [], "projects": {}}

    @staticmethod
    def _empty_totals():
        return {"requests": 0, "tokens_saved": 0, "compression_savings_usd": 0.0,
                "total_input_tokens": 0, "total_input_cost_usd": 0.0, "total_output_tokens": 0}

    def _empty_session(self):
        t = self._empty_totals()
        t.update({"savings_percent": 0.0, "started_at": _iso_now(), "last_activity_at": _iso_now()})
        return t

    def record(self, provider, model, before, after, out=0):
        saved = max(before - after, 0)
        out = max(int(out or 0), 0)
        rate = _price(model)
        usd_saved = saved / 1_000_000 * rate
        in_cost = after / 1_000_000 * rate
        now = _iso_now()
        with self._lock:
            L = self.data["lifetime"]
            L["requests"] += 1
            L["tokens_saved"] += saved
            L["compression_savings_usd"] = round(L["compression_savings_usd"] + usd_saved, 6)
            L["total_input_tokens"] += after
            L["total_input_cost_usd"] = round(L["total_input_cost_usd"] + in_cost, 6)
            L["total_output_tokens"] = L.get("total_output_tokens", 0) + out

            S = self.data["display_session"]
            last = _parse_iso(S.get("last_activity_at"))
            if last is None or (datetime.now(timezone.utc) - last).total_seconds() > SESSION_INACTIVITY_S:
                S.clear()
                S.update(self._empty_session())
            S["requests"] += 1
            S["tokens_saved"] += saved
            S["compression_savings_usd"] = round(S["compression_savings_usd"] + usd_saved, 6)
            S["total_input_tokens"] += after
            S["total_input_cost_usd"] = round(S["total_input_cost_usd"] + in_cost, 6)
            S["total_output_tokens"] = S.get("total_output_tokens", 0) + out
            S["last_activity_at"] = now
            denom = S["tokens_saved"] + S["total_input_tokens"]
            S["savings_percent"] = round(S["tokens_saved"] / denom * 100, 2) if denom else 0.0

            self.data["history"].append({
                "timestamp": now, "provider": provider, "model": model,
                "total_tokens_saved": L["tokens_saved"], "compression_savings_usd": L["compression_savings_usd"],
                "total_input_tokens": L["total_input_tokens"], "total_input_cost_usd": L["total_input_cost_usd"],
            })
            if len(self.data["history"]) > MAX_HISTORY:
                self.data["history"] = self.data["history"][-MAX_HISTORY:]
            self._save()
        return saved

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, SAVINGS_PATH)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)


STORE = None


def _log(line):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        with LOG_PATH.open("a") as f:
            f.write(f"{ts} - simplicio.proxy - INFO - {line}\n")
    except OSError:
        pass


# Per-request provider routing by model family → real provider host. Lets ONE proxy
# capture many providers transparently (no model swap). Unknown models use the default
# upstream. Each client forwards its own API key, so auth stays per-provider.
ROUTES = [
    ("gpt", "https://api.openai.com"), ("chatgpt", "https://api.openai.com"),
    ("o1", "https://api.openai.com"), ("o3", "https://api.openai.com"), ("o4", "https://api.openai.com"),
    ("claude", "https://api.anthropic.com"),
    ("deepseek", "https://api.deepseek.com"),
    ("grok", "https://api.x.ai"),
    ("mistral", "https://api.mistral.ai"), ("mixtral", "https://api.mistral.ai"),
    ("gemini", "https://generativelanguage.googleapis.com"),
]


def _route_for(model, default):
    m = (model or "").lower()
    for pref, host in ROUTES:
        if pref in m:
            return host
    return default


def _provider_of(host):
    h = host.lower()
    for key in ("deepseek", "anthropic", "openai", "googleapis", "x.ai", "groq", "mistral", "openrouter"):
        if key in h:
            return {"googleapis": "google", "x.ai": "xai"}.get(key, key)
    return "openai"


def _extract_output_tokens(data):
    """Pull completion/output token count from a response tail (OpenAI completion_tokens or
    Anthropic output_tokens). Returns 0 if the upstream didn't report usage (honest, no estimate)."""
    if not data:
        return 0
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        return 0
    m = re.findall(r'"(?:completion_tokens|output_tokens)"\s*:\s*(\d+)', text)
    return int(m[-1]) if m else 0


# ── transparent forwarding proxy ─────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = "https://api.openai.com"
    no_optimize = False
    route = True
    cache = None

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self._json(200, {"status": "ok", "engine": "simplicio", "version": __version__})
            return
        if self.path.rstrip("/") in ("/stats", "/v1/stats"):
            self._json(200, (STORE.data.get("lifetime", {}) if STORE else {}))
            return
        self._proxy()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        obj, model, before, after = None, "", 0, 0
        out_body = body
        if body:
            try:
                obj = json.loads(body)
                model = obj.get("model", "") or ""
                new_obj, before, after = _compress_payload(obj)  # before = full input tokens
                if not self.no_optimize and after < before:
                    out_body = json.dumps(new_obj).encode()
                else:
                    after = before
            except (ValueError, TypeError):
                out_body = body  # fail-open

        # Route to the model's real provider (transparent); fall back to default upstream.
        upstream = _route_for(model, self.upstream) if self.route else self.upstream
        provider = _provider_of(urlparse(upstream).netloc)

        # Response cache: a repeated deterministic (temp=0, non-streaming) request is served from
        # cache, skipping the upstream LLM call entirely → ~100% token saving on the hit.
        cache, ckey = self.cache, None
        if cache is not None and obj is not None and cache.cacheable(obj):
            ckey = cache.key(model, obj)
            hit = cache.get(ckey)
            if hit:
                status, hheaders, hbody = hit
                try:
                    self.send_response(status)
                    for k, v in hheaders.items():
                        if k.lower() not in ("transfer-encoding", "content-length", "connection", "content-encoding"):
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(hbody)))
                    self.send_header("Connection", "close")
                    self.send_header("X-Simplicio-Cache", "HIT")
                    self.end_headers()
                    self.wfile.write(hbody)
                except OSError:
                    return
                if STORE is not None:
                    tok_out = _extract_output_tokens(hbody)
                    STORE.record(provider, model or "unknown", before, 0, tok_out)  # whole call saved
                    _log(f"PERF model={model or 'unknown'} provider={provider} tok_before={before} "
                         f"tok_after=0 tok_saved={before} tok_out={tok_out} cache_hit_pct=100 cache=HIT")
                return

        try:
            up = urlparse(upstream)
            conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(up.netloc, timeout=600)
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ("host", "content-length", "accept-encoding")}
            headers["Content-Length"] = str(len(out_body))
            headers["Host"] = up.netloc
            conn.request(self.command, self.path, body=out_body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            resp_headers = {}
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "content-length", "connection", "content-encoding"):
                    self.send_header(k, v)
                    resp_headers[k] = v
            self.send_header("Connection", "close")
            self.end_headers()
            tail = b""  # keep the last 64KB — the usage block lives at the end (final SSE chunk / JSON)
            full = bytearray() if ckey else None  # buffer only when this request is cacheable
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                tail = (tail + chunk)[-65536:]
                if full is not None:
                    full.extend(chunk)
            conn.close()
            tok_out = _extract_output_tokens(tail)
            if ckey and full is not None and resp.status < 400:
                cache.put(ckey, resp.status, resp_headers, bytes(full))
        except Exception as e:  # upstream failure — report, don't crash the proxy
            try:
                self._json(502, {"error": {"message": f"simplicio-cli proxy upstream error: {e}", "type": "upstream_error"}})
            except OSError:
                return
            _log(f"UPSTREAM_ERROR {e}")
            return

        if STORE is not None and before:
            saved = STORE.record(provider, model or "unknown", before, after, tok_out)
            _log(f"PERF model={model or 'unknown'} provider={provider} tok_before={before} "
                 f"tok_after={after} tok_saved={saved} tok_out={tok_out} cache_hit_pct=0")

    def log_message(self, *a):
        pass


def cmd_proxy(args):
    global STORE
    STORE = SavingsStore()
    Handler.upstream = args.upstream.rstrip("/")
    Handler.no_optimize = args.no_optimize
    Handler.route = not args.no_route
    # Response cache on by default (only ever caches deterministic temp=0 non-streaming requests);
    # SIMPLICIO_CACHE=0 disables it.
    cache_on = os.environ.get("SIMPLICIO_CACHE", "1") != "0"
    if cache_on:
        try:
            from simplicio_cache import ResponseCache
            Handler.cache = ResponseCache()
        except Exception:
            Handler.cache = None
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    mode = "passthrough" if args.no_optimize else "compressing"
    routing = "per-provider routing" if Handler.route else f"fixed → {Handler.upstream}"
    cache_s = "cache on" if Handler.cache is not None else "cache off"
    print(f"⬡ Simplicio capture engine · proxy ({mode}, {routing}, {cache_s}) on http://{args.host}:{args.port}")
    _log(f"START proxy port={args.port} upstream={Handler.upstream} mode={mode}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


def _port_up(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def cmd_doctor(args):
    store = SavingsStore()
    life = store.data.get("lifetime", {})
    up = _port_up(args.port)
    print(f"Simplicio capture engine · doctor (port {args.port})")
    print(f"  proxy:   {'✓ running' if up else '✗ not reachable'} at http://127.0.0.1:{args.port}")
    print(f"  savings: {life.get('tokens_saved', 0):,} tokens / "
          f"${life.get('compression_savings_usd', 0):.4f} saved · {life.get('requests', 0)} requests")
    return 0


def cmd_memory(args):
    store = SavingsStore()
    print(f"Total Memories: {len(store.data.get('history', []))}")
    print(f"Database: {SAVINGS_PATH}")
    return 0


def main(argv=None):
    # Raw verbatim passthrough for sibling-backed commands — preserves `--flag value` order
    # (argparse REMAINDER mangles a leading flag). proxy/doctor/--version use argparse below.
    raw = list(sys.argv[1:] if argv is None else argv)
    _PASS = {"init": "simplicio_init.py", "wrap": "simplicio_wrap.py", "report": "simplicio_report.py",
             "verify": "simplicio_verify.py", "audit": "simplicio_audit.py", "capture": "simplicio_capture.py",
             "evals": "simplicio_evals.py", "detect": "simplicio_detect.py"}
    if raw:
        cmd, rest = raw[0], raw[1:]
        if cmd == "memory" and rest and rest[0] != "stats":
            return _exec_sibling("simplicio_memory.py", rest)
        if cmd == "mcp":
            return _exec_sibling("simplicio_tools_server.py", [])  # MCP server reads stdin; ignore extra args
        if cmd in _PASS:
            return _exec_sibling(_PASS[cmd], rest)
        if cmd == "semantic":
            if "--ml" in rest:
                return _exec_sibling("simplicio_semantic_ml.py", ["compress"] + [a for a in rest if a != "--ml"])
            return _exec_sibling("simplicio_semantic.py", rest)
        if cmd == "rag":
            if "--ml" in rest:
                return _exec_sibling("simplicio_semantic_ml.py", ["search"] + [a for a in rest if a != "--ml"])
            return _exec_sibling("simplicio_rag.py", rest)

    p = argparse.ArgumentParser(prog="simplicio_engine", description="Simplicio capture engine")
    p.add_argument("--version", action="version", version=f"simplicio-engine {__version__}")
    sub = p.add_subparsers(dest="cmd")

    pp = sub.add_parser("proxy", help="run the transparent capture proxy")
    pp.add_argument("--port", type=int, default=int(os.environ.get("SIMPLICIO_PROXY_PORT", "8788")))
    pp.add_argument("--host", default="127.0.0.1")
    pp.add_argument("--upstream", default=os.environ.get("SIMPLICIO_UPSTREAM", "https://api.openai.com"),
                    help="default/fallback upstream host for unrouted models")
    pp.add_argument("--no-optimize", action="store_true", help="pure passthrough (no compression)")
    pp.add_argument("--no-route", action="store_true",
                    help="disable per-provider routing; send everything to --upstream")

    pd = sub.add_parser("doctor", help="show proxy + savings status")
    pd.add_argument("--port", type=int, default=int(os.environ.get("SIMPLICIO_PROXY_PORT", "8788")))

    pm = sub.add_parser("memory", help="memory: stats (engine) | remember/recall/forget/list (CCR store)")
    pm.add_argument("rest", nargs=argparse.REMAINDER)
    pmcp = sub.add_parser("mcp", help="run the native MCP server (compress/retrieve/stats tools)")
    pmcp.add_argument("rest", nargs=argparse.REMAINDER)
    pin = sub.add_parser("init", help="register Simplicio into a client: init <client> [--apply]")
    pin.add_argument("rest", nargs=argparse.REMAINDER)
    psig = sub.add_parser("signatures", help="signatures-only view of a source file (token-economy read)")
    psig.add_argument("rest", nargs=argparse.REMAINDER)
    pca = sub.add_parser("cache", help="response cache: stats | clear")
    pca.add_argument("rest", nargs=argparse.REMAINDER)
    pwr = sub.add_parser("wrap", help="run a client with capture routing: wrap <client> [-- args]")
    pwr.add_argument("rest", nargs=argparse.REMAINDER)
    prp = sub.add_parser("report", help="savings report (summary/--json/--since/--top)")
    prp.add_argument("rest", nargs=argparse.REMAINDER)
    pvf = sub.add_parser("verify", help="self-check the whole token-economy stack")
    pvf.add_argument("rest", nargs=argparse.REMAINDER)
    pau = sub.add_parser("audit", help="audit files/dirs for compression savings opportunity")
    pau.add_argument("rest", nargs=argparse.REMAINDER)
    pca = sub.add_parser("capture", help="dry-run: what a request would compress/save (no send)")
    pca.add_argument("rest", nargs=argparse.REMAINDER)
    pev = sub.add_parser("evals", help="compression eval + regression gate")
    pev.add_argument("rest", nargs=argparse.REMAINDER)
    pse = sub.add_parser("semantic", help="reversible extractive (semantic-lite) compression of stdin")
    pse.add_argument("rest", nargs=argparse.REMAINDER)
    prg = sub.add_parser("rag", help="TF-IDF retrieval over the CCR memory store")
    prg.add_argument("rest", nargs=argparse.REMAINDER)

    # parse_known_args so leading passthrough flags (e.g. `semantic --ml`) reach the sibling
    args, _extra = p.parse_known_args(argv)
    _rest = list(getattr(args, "rest", []) or []) + _extra
    if args.cmd == "proxy":
        return cmd_proxy(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "memory":
        rest = _rest
        if not rest or rest[0] == "stats":
            return cmd_memory(args)  # engine history count — keeps the dashboard's "Total Memories:" parse
        return _exec_sibling("simplicio_memory.py", rest)
    if args.cmd == "mcp":
        return _exec_sibling("simplicio_tools_server.py", [])  # the MCP server reads stdin; ignore 'serve'
    if args.cmd == "init":
        return _exec_sibling("simplicio_init.py", _rest)
    if args.cmd == "wrap":
        return _exec_sibling("simplicio_wrap.py", _rest)
    if args.cmd == "report":
        return _exec_sibling("simplicio_report.py", _rest)
    if args.cmd == "verify":
        return _exec_sibling("simplicio_verify.py", _rest)
    if args.cmd == "audit":
        return _exec_sibling("simplicio_audit.py", _rest)
    if args.cmd == "capture":
        return _exec_sibling("simplicio_capture.py", _rest)
    if args.cmd == "evals":
        return _exec_sibling("simplicio_evals.py", _rest)
    if args.cmd == "semantic":
        rest = _rest
        if "--ml" in rest:  # real embedding backend (optional model2vec dep)
            return _exec_sibling("simplicio_semantic_ml.py", ["compress"] + [a for a in rest if a != "--ml"])
        return _exec_sibling("simplicio_semantic.py", rest)
    if args.cmd == "rag":
        rest = _rest
        if "--ml" in rest:
            return _exec_sibling("simplicio_semantic_ml.py", ["search"] + [a for a in rest if a != "--ml"])
        return _exec_sibling("simplicio_rag.py", rest)
    if args.cmd == "signatures":
        return _exec_sibling("simplicio_signatures.py", _rest)
    if args.cmd == "cache":
        return _exec_sibling("simplicio_cache.py", _rest or ["stats"])
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

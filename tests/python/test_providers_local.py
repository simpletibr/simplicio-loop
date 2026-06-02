"""Tests for the default in-process local inference path (llama-cpp-python).

The llama-cpp-python and huggingface-hub libs are optional extras that are not
installed in CI, so we test the routing/spec resolution directly and stub the
heavy model load (`_local_llama`) when exercising explicit GGUF fallback paths.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

from simplicio import providers
from simplicio._cache import reset_for_tests


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    for v in (
        "SIMPLICIO_MODEL",
        "SIMPLICIO_BASE_URL",
        "SIMPLICIO_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "SIMPLICIO_LOCAL_MODEL_PATH",
        "SIMPLICIO_LOCAL_MODEL_REPO",
        "SIMPLICIO_LOCAL_MODEL_FILE",
        "SIMPLICIO_LOCAL_MODEL_DIR",
        "SIMPLICIO_LOCAL_CTX",
        "SIMPLICIO_LOCAL_CTX_MAX",
        "SIMPLICIO_LOCAL_THREADS",
        "SIMPLICIO_LOCAL_THREADS_MAX",
        "SIMPLICIO_LOCAL_GPU_LAYERS",
        "SIMPLICIO_LOCAL_BATCH",
        "SIMPLICIO_LOCAL_BATCH_MAX",
        "SIMPLICIO_LOCAL_UBATCH",
        "SIMPLICIO_LOCAL_UBATCH_MAX",
        "SIMPLICIO_LOCAL_MAX_TOKENS",
        "SIMPLICIO_LOCAL_MAX_TOKENS_CAP",
        "SIMPLICIO_LOCAL_TEMP",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)
    providers._LOCAL_LLAMA_CACHE.clear()
    reset_for_tests()
    yield
    providers._LOCAL_LLAMA_CACHE.clear()
    reset_for_tests()


# --------------------------------------------------------------------------- #
# _is_local / default routing
# --------------------------------------------------------------------------- #


def test_is_local_explicit_prefix():
    assert providers._is_local("local-llama/default", None) is True
    assert providers._is_local("openbmb/minicpm5:latest", None) is True
    assert providers._is_local("local-llama/repo::a.gguf", "http://x") is True


def test_empty_config_uses_in_process_local_default():
    assert providers._is_default_local(None, None) is True
    assert providers._is_default_local("", "") is True
    assert providers._is_local(None, None) is False


def test_is_local_false_when_base_set():
    assert providers._is_local(None, "http://localhost:11434/v1") is False


def test_is_local_false_when_other_model_set():
    assert providers._is_local("claude-opus-4-7", None) is False
    assert providers._is_local("claude-cli/sonnet", None) is False


# --------------------------------------------------------------------------- #
# _local_spec
# --------------------------------------------------------------------------- #


def test_local_spec_default():
    repo, fname, path = providers._local_spec("")
    assert repo == providers.LOCAL_DEFAULT_REPO
    assert fname == providers.LOCAL_DEFAULT_FILE
    assert path is None


def test_local_spec_default_keyword():
    repo, fname, path = providers._local_spec("local-llama/default")
    assert repo == providers.LOCAL_DEFAULT_REPO
    assert fname == providers.LOCAL_DEFAULT_FILE


def test_local_spec_repo_and_file():
    repo, fname, path = providers._local_spec("local-llama/owner/repo::weights.gguf")
    assert repo == "owner/repo"
    assert fname == "weights.gguf"
    assert path is None


def test_local_spec_direct_path():
    repo, fname, path = providers._local_spec("local-llama//models/x.gguf")
    assert repo is None and fname is None
    assert path == "/models/x.gguf"


def test_local_spec_path_env_wins(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", "/data/custom.gguf")
    repo, fname, path = providers._local_spec("local-llama/owner/repo::w.gguf")
    assert path == "/data/custom.gguf"
    assert repo is None and fname is None


def test_local_spec_file_env_override(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_FILE", "Q4_K_M.gguf")
    repo, fname, _ = providers._local_spec("")
    assert fname == "Q4_K_M.gguf"


def test_local_spec_bare_repo_uses_default_file():
    repo, fname, path = providers._local_spec("local-llama/some/repo")
    assert repo == "some/repo"
    assert fname == providers.LOCAL_DEFAULT_FILE


# --------------------------------------------------------------------------- #
# _provider_id / info
# --------------------------------------------------------------------------- #


def test_provider_id_local():
    assert providers._provider_id("local-llama/default", None) == "local-llama"


def test_info_local_auto_default():
    s = providers.info()
    assert "openbmb/minicpm5:latest" in s
    assert "provider=local-llama" in s
    assert "key=not-needed" in s
    assert providers.LOCAL_DEFAULT_FILE in s


def test_info_local_explicit(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama/owner/repo::w.gguf")
    s = providers.info()
    assert "local-llama" in s
    assert "owner/repo/w.gguf" in s


# --------------------------------------------------------------------------- #
# _resolve_local_path
# --------------------------------------------------------------------------- #


def test_resolve_local_path_missing_file_raises():
    with pytest.raises(SystemExit) as exc:
        providers._resolve_local_path(None, None, "/nope/missing.gguf")
    assert "not found" in str(exc.value)


def test_resolve_local_path_existing_file(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(b"GGUF")
    assert providers._resolve_local_path(None, None, str(f)) == str(f)


def test_resolve_local_path_downloads_from_hf(monkeypatch):
    from pathlib import Path
    import tempfile

    downloaded_path = Path(tempfile.mkdtemp()) / "weights.gguf"
    downloaded_path.write_bytes(b"GGUF")
    downloaded = str(downloaded_path)
    fake = types.ModuleType("huggingface_hub")
    fake.hf_hub_download = MagicMock(return_value=downloaded)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    out = providers._resolve_local_path("owner/repo", "weights.gguf", None)
    assert out == downloaded
    fake.hf_hub_download.assert_called_once_with(
        repo_id="owner/repo", filename="weights.gguf"
    )


def test_resolve_local_path_prefers_executor_dir(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    primary = model_dir / providers.LOCAL_DEFAULT_FILE
    primary.write_bytes(b"GGUF")
    fake = types.ModuleType("huggingface_hub")
    fake.hf_hub_download = MagicMock()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_DIR", str(model_dir))

    out = providers._resolve_local_path(
        providers.LOCAL_DEFAULT_REPO, providers.LOCAL_DEFAULT_FILE, None
    )

    assert out == str(primary)
    fake.hf_hub_download.assert_not_called()


def test_resolve_local_path_skips_corrupt_executor_file(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    corrupt = model_dir / providers.LOCAL_DEFAULT_FILE
    corrupt.write_bytes(b"not-a-gguf")
    downloaded = tmp_path / "cache" / providers.LOCAL_DEFAULT_FILE
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"GGUF")
    fake = types.ModuleType("huggingface_hub")
    fake.hf_hub_download = MagicMock(return_value=str(downloaded))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_DIR", str(model_dir))

    out = providers._resolve_local_path(
        providers.LOCAL_DEFAULT_REPO, providers.LOCAL_DEFAULT_FILE, None
    )

    assert out == str(downloaded)
    fake.hf_hub_download.assert_called_once()


def test_resolve_local_path_default_does_not_try_legacy_qwen25(monkeypatch, tmp_path):
    fake = types.ModuleType("huggingface_hub")
    fake.hf_hub_download = MagicMock(side_effect=RuntimeError("qwen35 missing"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_DIR", str(tmp_path / "empty-models"))

    with pytest.raises(SystemExit) as exc:
        providers._resolve_local_path(
            providers.LOCAL_DEFAULT_REPO, providers.LOCAL_DEFAULT_FILE, None
        )

    assert providers.LOCAL_DEFAULT_FILE in str(exc.value)
    assert len(fake.hf_hub_download.call_args_list) == 1
    assert (
        fake.hf_hub_download.call_args_list[0].kwargs["repo_id"]
        == providers.LOCAL_DEFAULT_REPO
    )
    assert (
        fake.hf_hub_download.call_args_list[0].kwargs["filename"]
        == providers.LOCAL_DEFAULT_FILE
    )


def test_resolve_local_path_no_hf_lib_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with pytest.raises(SystemExit) as exc:
        providers._resolve_local_path("owner/repo", "w.gguf", None)
    assert "huggingface-hub" in str(exc.value)
    assert "simplicio-cli[local]" in str(exc.value)


# --------------------------------------------------------------------------- #
# _local_llama missing backend
# --------------------------------------------------------------------------- #


def test_local_llama_missing_backend_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    with pytest.raises(SystemExit) as exc:
        providers._local_llama("local-llama/default")
    assert "llama-cpp-python" in str(exc.value)
    assert "simplicio-cli[local]" in str(exc.value)


def test_local_llama_loads_and_caches(monkeypatch):
    f = MagicMock(name="LlamaInstance")
    Llama = MagicMock(return_value=f)
    fake = types.ModuleType("llama_cpp")
    fake.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", _touch(monkeypatch))

    a = providers._local_llama("local-llama/default")
    b = providers._local_llama("local-llama/default")
    assert a is f and b is f
    Llama.assert_called_once()  # second call reused the cached instance
    kwargs = Llama.call_args[1]
    assert kwargs["n_ctx"] == providers.LOCAL_DEFAULT_CTX
    assert kwargs["n_threads"] == providers.LOCAL_DEFAULT_THREADS
    assert kwargs["n_batch"] == providers.LOCAL_DEFAULT_BATCH
    assert kwargs["n_ubatch"] == providers.LOCAL_DEFAULT_UBATCH
    assert kwargs["n_gpu_layers"] == 0
    assert kwargs["use_mmap"] is True
    assert kwargs["use_mlock"] is False
    assert kwargs["verbose"] is False


def test_local_llama_clamps_ctx_threads_gpu_and_batch(monkeypatch):
    Llama = MagicMock(return_value=MagicMock())
    fake = types.ModuleType("llama_cpp")
    fake.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", _touch(monkeypatch))
    monkeypatch.setenv("SIMPLICIO_LOCAL_CTX", "16384")
    monkeypatch.setenv("SIMPLICIO_LOCAL_CTX_MAX", "20000")
    monkeypatch.setenv("SIMPLICIO_LOCAL_THREADS", "6")
    monkeypatch.setenv("SIMPLICIO_LOCAL_THREADS_MAX", "8")
    monkeypatch.setenv("SIMPLICIO_LOCAL_GPU_LAYERS", "20")
    monkeypatch.setenv("SIMPLICIO_LOCAL_BATCH", "999")
    monkeypatch.setenv("SIMPLICIO_LOCAL_UBATCH", "999")

    providers._local_llama("local-llama/default")
    kwargs = Llama.call_args[1]
    assert kwargs["n_ctx"] == providers.LOCAL_MAX_CTX
    assert kwargs["n_threads"] == providers.LOCAL_MAX_THREADS
    assert kwargs["n_gpu_layers"] == 0
    assert kwargs["n_batch"] == providers.LOCAL_MAX_BATCH
    assert kwargs["n_ubatch"] == providers.LOCAL_MAX_UBATCH


def test_local_llama_clamps_unsafe_ctx_and_threads(monkeypatch):
    Llama = MagicMock(return_value=MagicMock())
    fake = types.ModuleType("llama_cpp")
    fake.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", _touch(monkeypatch))
    monkeypatch.setenv("SIMPLICIO_LOCAL_CTX", "999999")
    monkeypatch.setenv("SIMPLICIO_LOCAL_THREADS", "999")

    providers._local_llama("local-llama/default")
    kwargs = Llama.call_args[1]
    assert kwargs["n_ctx"] == providers.LOCAL_MAX_CTX
    assert kwargs["n_threads"] == providers.LOCAL_MAX_THREADS


# --------------------------------------------------------------------------- #
# generate() local routing
# --------------------------------------------------------------------------- #


def test_generate_routes_to_local_llama_by_default(monkeypatch):
    calls = []

    def fake_openai(*_args, **_kwargs):
        raise AssertionError("Ollama/OpenAI-compatible endpoint must not be used")

    def fake_local(prompt, feedback, model, max_tokens):
        calls.append((prompt, model, max_tokens))
        return "GGUF OK"

    monkeypatch.setattr(providers, "_openai_compatible_generate", fake_openai)
    monkeypatch.setattr(providers, "_local_generate", fake_local)
    out = providers.generate("do x", max_tokens=128)
    assert out == "GGUF OK"
    assert calls[0][1] == providers.LOCAL_DEFAULT_MODEL
    assert calls[0][2] == 128


def test_generate_default_local_uses_minicpm_gguf(monkeypatch):
    calls = []

    def fake_local(prompt, feedback, model, max_tokens):
        calls.append((prompt, model, max_tokens))
        return "GGUF OK"

    monkeypatch.setattr(providers, "_local_generate", fake_local)
    out = providers.generate("do x", max_tokens=128)
    assert out == "GGUF OK"
    assert calls[0][1] == providers.LOCAL_DEFAULT_MODEL


def test_generate_local_explicit_prefix(monkeypatch):
    seen = {}

    def fake_local(prompt, feedback, model, max_tokens):
        seen["model"] = model
        return "OK"

    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama/owner/repo::w.gguf")
    monkeypatch.setattr(providers, "_local_generate", fake_local)
    providers.generate("x")
    assert seen["model"] == "local-llama/owner/repo::w.gguf"


def test_generate_local_uses_completion_cache(monkeypatch):
    n = {"calls": 0}

    def fake_local(prompt, feedback, model, max_tokens):
        n["calls"] += 1
        return "CACHED"

    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama/default")
    monkeypatch.setattr(providers, "_local_generate", fake_local)
    assert providers.generate("same prompt") == "CACHED"
    assert providers.generate("same prompt") == "CACHED"
    assert n["calls"] == 1  # second call served from cache


def test_generate_no_model_with_base_still_raises(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(SystemExit) as exc:
        providers.generate("x")
    assert "SIMPLICIO_MODEL" in str(exc.value)
    assert "openbmb/minicpm5:latest" in str(exc.value)


def test_local_generate_caps_tokens_and_temp(monkeypatch):
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "hi"}}]
    }
    monkeypatch.setattr(providers, "_local_llama", lambda model: llm)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MAX_TOKENS", "256")
    monkeypatch.setenv("SIMPLICIO_LOCAL_TEMP", "0.4")

    out = providers._local_generate("p", None, "local-llama/default", 4000)
    assert out == "hi"
    kwargs = llm.create_chat_completion.call_args[1]
    assert kwargs["max_tokens"] == 256  # cap overrides the 4000 arg
    assert kwargs["temperature"] == 0.4


def test_local_generate_clamps_unsafe_token_cap(monkeypatch):
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "hi"}}]
    }
    monkeypatch.setattr(providers, "_local_llama", lambda model: llm)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MAX_TOKENS", "999999")

    providers._local_generate("p", None, "local-llama/default", 4000)
    kwargs = llm.create_chat_completion.call_args[1]
    assert kwargs["max_tokens"] == providers.LOCAL_MAX_OUTPUT_TOKENS


def test_generate_cache_key_includes_weights(monkeypatch):
    # Two different GGUFs both routed as the default must not collide in cache.
    seen = []

    def fake_local(prompt, feedback, model, max_tokens):
        seen.append(os.environ.get("SIMPLICIO_LOCAL_MODEL_PATH"))
        return f"out:{os.environ.get('SIMPLICIO_LOCAL_MODEL_PATH')}"

    monkeypatch.setenv("SIMPLICIO_CACHE", "1")
    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama/default")
    monkeypatch.setattr(providers, "_local_generate", fake_local)

    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", "/models/a.gguf")
    out_a = providers.generate("same prompt")
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", "/models/b.gguf")
    out_b = providers.generate("same prompt")

    assert out_a == "out:/models/a.gguf"
    assert out_b == "out:/models/b.gguf"  # not served stale from model A
    assert seen == ["/models/a.gguf", "/models/b.gguf"]


def _touch(monkeypatch):
    """Create a throwaway .gguf file and return its path."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".gguf")
    import os as _os

    with _os.fdopen(fd, "wb") as handle:
        handle.write(b"GGUF")
    return path

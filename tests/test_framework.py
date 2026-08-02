"""Expanded framework tests (LUMU v0.4) — covers tools, memory, rag, providers, security, sandbox."""
import os, sys, hashlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _emb(text, dim=256):
    """Bag-of-tokens hashed embedding: shared tokens dominate similarity."""
    vec = [0.0] * dim
    for tok in text.split():
        idx = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % dim
        vec[idx] += 1.0
    return vec


def test_tool_registry_discovers_many_tools():
    from tools.registry import ToolRegistry
    r = ToolRegistry()
    r.discover()
    tools = r.list_tools()
    assert len(tools) > 50, "expected many tools, got %d" % len(tools)
    names = {t.name for t in tools}
    for expected in ("terminal", "write_file", "read_file"):
        assert expected in names, "missing expected tool %s" % expected


def test_memory_manager_roundtrip(tmp_path):
    from memory.manager import MemoryManager
    mm = MemoryManager(str(tmp_path / "mem.db"))
    mm.save("hello", "world")
    assert mm.recall("hello") == "world"


def test_vector_store_search_returns_inserted(tmp_path):
    from rag.vector_store import VectorStore
    vs = VectorStore(str(tmp_path / "rag.db"), dim=256, embedding_fn=_emb)
    vs.add("doc1", "LUMU 是本地优先的智能体框架", {"src": "a"})
    vs.add("doc2", "今天天气不错出去玩", {"src": "b"})
    res = vs.search("本地优先 智能体", top_k=2)
    ids = [r["id"] for r in res]
    assert "doc1" in ids and ids.index("doc1") < ids.index("doc2")


def test_providers_discovered_with_domestic():
    from providers import discover_providers, list_providers
    discover_providers()
    names = {p.name for p in list_providers()}
    assert len(names) > 0, "no providers discovered"
    for dom in ("deepseek", "glm", "qwen"):
        assert dom in names, "missing domestic provider %s" % dom


def test_security_protected_paths():
    from tools.registry import _is_protected_path
    assert _is_protected_path("/opt/agent-framework/config.py") is True
    assert _is_protected_path("/opt/agent-framework/tools/foo.py") is False
    assert _is_protected_path("/tmp/safe.txt") is False


def test_sandbox_reports_docker_state():
    from sandbox.executor import CodeSandbox
    sb = CodeSandbox(docker_socket="/nonexistent-docker.sock")
    assert isinstance(sb.docker_available, bool)


def test_openai_provider_supports_base_url_override(monkeypatch):
    from providers.base import ProviderProfile
    p = ProviderProfile(name="openai", display_name="x", base_url="https://api.openai.com/v1", api_key_env="OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://my-relay.example/v1")
    assert p.resolve_base_url() == "https://my-relay.example/v1"


def test_computer_control_tools_register():
    from tools.registry import ToolRegistry
    r = ToolRegistry()
    r.discover()
    names = {t.name for t in r.list_tools()}
    for k in ("screenshot", "mouse_click", "type_text", "key_press", "hotkey", "mouse_move", "scroll", "active_window"):
        assert k in names, "missing computer tool %s" % k

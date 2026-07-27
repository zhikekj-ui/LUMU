#!/usr/bin/env python3
"""Quick smoke test for all modules."""
import sys
sys.path.insert(0, ".")

print("=== Testing imports ===")

from providers import discover_providers, list_providers
discover_providers()
providers = list_providers()
print(f"Providers: {[p.name for p in providers]}")

from tools.registry import ToolRegistry
r = ToolRegistry()
r.discover()
tools = r.list_tools()
print(f"Tools: {[t.name for t in tools]}")

from agent.context import ContextEngine
ctx = ContextEngine()
print(f"ContextEngine OK (window={ctx.context_window})")

from agent.prompts import build_system_prompt
prompt = build_system_prompt()
print(f"System prompt: {len(prompt)} chars")

from memory.manager import MemoryManager
mm = MemoryManager("/tmp/test_memory.db")
mm.save("test_key", "test content")
assert mm.recall("test_key") == "test content"
print("MemoryManager OK")

print("\n=== ALL IMPORTS OK ===")

from __future__ import annotations

from core.logging_config import get_logger
_logger = get_logger("plugins.loader")
"""Plugin loader — discovers and manages plugins from the plugins/ directory.

Plugins are Python files in subdirectories of plugins/ that define a class
inheriting from BasePlugin. The loader scans for them, instantiates them,
and calls their lifecycle hooks.

Directory structure:
    plugins/
        model-providers/     # existing provider definitions
        example_plugin/
            __init__.py      # contains class ExamplePlugin(BasePlugin)
        another_plugin/
            __init__.py
"""
import importlib.util
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from tools.registry import ToolRegistry
    from fastapi import FastAPI


class PluginLoader:
    """Discover, load, and manage plugins."""

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    @property
    def plugins(self) -> dict[str, BasePlugin]:
        return dict(self._plugins)

    def discover(self, plugins_dir: Path | None = None):
        """Scan plugins/ for subdirectories containing __init__.py with a BasePlugin subclass."""
        if plugins_dir is None:
            plugins_dir = Path(__file__).parent

        for subdir in sorted(plugins_dir.iterdir()):
            if not subdir.is_dir():
                continue
            if subdir.name.startswith("_") or subdir.name.startswith("."):
                continue
            # Skip model-providers — handled separately by providers/registry.py
            if subdir.name == "model-providers":
                continue

            init_file = subdir / "__init__.py"
            if not init_file.exists():
                continue

            try:
                self._load_plugin_from_file(init_file, subdir.name)
            except Exception as e:
                _logger.info(f"[plugin] Failed to load {subdir.name}: {e}")

    def _load_plugin_from_file(self, filepath: Path, fallback_name: str):
        """Load a plugin module and find BasePlugin subclasses."""
        spec = importlib.util.spec_from_file_location(f"plugins.{fallback_name}", filepath)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find all BasePlugin subclasses in the module
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, BasePlugin)
                and attr is not BasePlugin
            ):
                instance = attr()
                self._register_plugin(instance)
                break  # One plugin class per file

    def _register_plugin(self, plugin: BasePlugin):
        """Register a plugin instance."""
        name = plugin.name or "unnamed"
        if name in self._plugins:
            _logger.info(f"[plugin] Duplicate plugin: {name}")
            return
        self._plugins[name] = plugin
        plugin.on_load()
        _logger.info(f"[plugin] Loaded: {name} v{plugin.version}")

    def register_tools(self, registry: "ToolRegistry"):
        """Call register_tools() on all loaded plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.register_tools(registry)
            except Exception as e:
                _logger.info(f"[plugin] {plugin.name} register_tools error: {e}")
        # Bump generation after all plugins have registered
        registry._generation += 1

    def register_routes(self, app: "FastAPI"):
        """Call register_routes() on all loaded plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.register_routes(app)
            except Exception as e:
                _logger.info(f"[plugin] {plugin.name} register_routes error: {e}")

    def run_message_hooks(self, message: dict) -> dict | None:
        """Run on_message hooks. Return None to continue, or a dict to short-circuit."""
        for plugin in self._plugins.values():
            try:
                result = plugin.on_message(message)
                if result is not None:
                    return result
            except Exception as e:
                _logger.info(f"[plugin] {plugin.name} on_message error: {e}")
        return None

    def run_response_hooks(self, response: dict) -> dict:
        """Run on_response hooks on the final response."""
        for plugin in self._plugins.values():
            try:
                response = plugin.on_response(response)
            except Exception as e:
                _logger.info(f"[plugin] {plugin.name} on_response error: {e}")
        return response

    def get_all_configs(self) -> list[dict]:
        """Get config from all loaded plugins."""
        return [p.get_config() for p in self._plugins.values()]

    def unload_all(self):
        """Unload all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_unload()
            except Exception as e:
                _logger.info(f"[plugin] {plugin.name} unload error: {e}")
        self._plugins.clear()

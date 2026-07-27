"""Base plugin class — all plugins inherit from this.

Plugins can:
- Register tools (via tool_registry)
- Add API routes (via app)
- Hook into agent lifecycle events
- Provide middleware for request/response processing
"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.registry import ToolRegistry
    from fastapi import FastAPI


class BasePlugin:
    """Base class for all plugins.

    Subclass this and implement the hooks you need.
    The plugin loader will call these methods automatically.
    """

    # Plugin metadata — override in subclass
    name: str = "unnamed"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    def on_load(self):
        """Called when the plugin is loaded. Use for initialization."""
        pass

    def on_unload(self):
        """Called when the plugin is unloaded. Use for cleanup."""
        pass

    def register_tools(self, registry: "ToolRegistry"):
        """Register tools with the tool registry.

        Example:
            registry.register(
                name="my_tool",
                description="Does something useful",
                parameters={"type": "object", "properties": {...}},
                handler=my_handler,
                toolset=self.name,
            )
        """
        pass

    def register_routes(self, app: "FastAPI"):
        """Add API routes to the FastAPI app.

        Example:
            @app.get(f"/api/plugins/{self.name}/status")
            async def status():
                return {"plugin": self.name, "status": "ok"}
        """
        pass

    def on_message(self, message: dict) -> dict | None:
        """Called before each agent turn. Return None to continue, or a dict to short-circuit.

        Args:
            message: {"role": "user", "content": "...", "session_id": "..."}

        Returns:
            None to continue normally, or {"content": "..."} to skip the agent.
        """
        return None

    def on_response(self, response: dict) -> dict:
        """Called after the agent produces a response. Can modify the response.

        Args:
            response: {"content": "...", "session_id": "...", "tool_calls": [...]}

        Returns:
            The (possibly modified) response dict.
        """
        return response

    def get_config(self) -> dict:
        """Return plugin configuration for the admin API."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
        }

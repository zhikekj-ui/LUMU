"""MCP bridge — connects to MCP servers and registers their tools in our registry.

Reads MCP server configurations from config or .env, starts the servers,
discovers their tools, and registers them in the ToolRegistry.

MCP servers are configured via MCP_SERVERS env var (JSON array):
    MCP_SERVERS=[{"name":"fs","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/tmp"]}]
"""
import asyncio
import json
import os
import sys

from mcp.client import MCPClient


class MCPBridge:
    """Manage MCP server connections and bridge their tools to our registry."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tool_map: dict[str, str] = {}  # tool_name → server_name

    @property
    def servers(self) -> dict[str, MCPClient]:
        return dict(self._clients)

    async def connect_all(self, registry=None):
        """Connect to all configured MCP servers and register their tools."""
        servers_config = os.getenv("MCP_SERVERS", "")
        if not servers_config:
            return

        try:
            configs = json.loads(servers_config)
        except json.JSONDecodeError:
            print(f"[mcp] Invalid MCP_SERVERS config: {servers_config[:100]}", file=sys.stderr)
            return

        for cfg in configs:
            name = cfg.get("name", cfg.get("command", "unknown"))
            command = cfg.get("command")
            args = cfg.get("args", [])
            env = cfg.get("env")

            if not command:
                print(f"[mcp] Skipping server {name}: no command", file=sys.stderr)
                continue

            try:
                client = MCPClient(command, args, env, name)
                await client.start()
                self._clients[name] = client
                print(f"[mcp] Connected to: {name}")

                # Discover and register tools
                if registry:
                    tools = await client.list_tools()
                    for tool in tools:
                        self._register_mcp_tool(registry, name, tool)
                    print(f"[mcp] {name}: registered {len(tools)} tools")

            except Exception as e:
                print(f"[mcp] Failed to connect {name}: {e}", file=sys.stderr)

    def _register_mcp_tool(self, registry, server_name: str, tool_def: dict):
        """Register an MCP server's tool in our ToolRegistry."""
        tool_name = tool_def.get("name", "")
        if not tool_name:
            return

        # Prefix with server name to avoid collisions
        full_name = f"mcp_{server_name}_{tool_name}"
        self._tool_map[full_name] = server_name

        # Convert MCP input schema to OpenAI schema format
        input_schema = tool_def.get("inputSchema", {})
        if not input_schema.get("type"):
            input_schema["type"] = "object"

        description = tool_def.get("description", f"MCP tool from {server_name}")

        client = self._clients[server_name]

        async def handler(**kwargs):
            try:
                return await client.call_tool(tool_name, kwargs)
            except Exception as e:
                return f"MCP error: {e}"

        registry.register(
            name=full_name,
            description=f"[MCP:{server_name}] {description}",
            parameters=input_schema,
            handler=handler,
            is_async=True,
            toolset="mcp",
            emoji="🔌",
        )

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for name, client in self._clients.items():
            try:
                await client.stop()
                print(f"[mcp] Disconnected: {name}")
            except Exception as e:
                print(f"[mcp] Error disconnecting {name}: {e}", file=sys.stderr)
        self._clients.clear()
        self._tool_map.clear()

    def get_server_info(self) -> list[dict]:
        """Get info about connected MCP servers."""
        return [
            {
                "name": name,
                "command": client.command,
                "args": client.args,
                "tools": [tn for tn, sn in self._tool_map.items() if sn == name],
            }
            for name, client in self._clients.items()
        ]

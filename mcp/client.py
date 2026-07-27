"""MCP Client — connects to MCP servers via stdio transport.

MCP (Model Context Protocol) is a standard for connecting AI models to external
tools and data sources. This client spawns MCP server processes and communicates
via JSON-RPC 2.0 over stdin/stdout.

Usage:
    client = MCPClient("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
    await client.start()
    tools = await client.list_tools()
    result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
    await client.stop()
"""
import asyncio
import json
import sys
from typing import Any


class MCPClient:
    """MCP client using stdio transport (JSON-RPC 2.0)."""

    def __init__(self, command: str, args: list[str] = None, env: dict = None, name: str = ""):
        self.command = command
        self.args = args or []
        self.env = env
        self.name = name or command
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def start(self):
        """Start the MCP server process and initialize the connection."""
        self._process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize MCP handshake
        result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "lumu-agent", "version": "0.3.0"},
        })
        # Send initialized notification
        await self._notify("notifications/initialized", {})
        return result

    async def stop(self):
        """Stop the MCP server process."""
        if self._reader_task:
            self._reader_task.cancel()
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    async def list_tools(self) -> list[dict]:
        """List available tools from the MCP server."""
        result = await self._request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        result = await self._request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # MCP returns content as list of {type: "text", text: "..."}
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
        return str(result)

    async def _request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        self._request_id += 1
        req_id = self._request_id
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"MCP request timed out: {method}")

    async def _notify(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def _read_loop(self):
        """Read responses from the MCP server."""
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Handle response
                if "id" in msg and msg["id"] in self._pending:
                    future = self._pending.pop(msg["id"])
                    if "error" in msg:
                        err = msg["error"]
                        future.set_exception(
                            RuntimeError(f"MCP error {err.get('code', '?')}: {err.get('message', '?')}")
                        )
                    else:
                        future.set_result(msg.get("result", {}))
                # Handle notification (no id)
                elif "method" in msg and "id" not in msg:
                    pass  # Ignore notifications for now
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[mcp] {self.name} reader error: {e}", file=sys.stderr)

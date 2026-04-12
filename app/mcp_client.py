from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.tools import StructuredTool
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field, create_model


@dataclass(slots=True)
class MCPToolDefinition:
    """Discovered MCP tool metadata plus local risk annotations."""

    server_name: str
    langchain_name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool
    risk_level: str


@dataclass(slots=True)
class MCPClientSettings:
    """Environment-driven configuration for the MCP stdio bridge."""

    enabled: bool
    command: str
    args: list[str]
    cwd: str | None
    timeout_seconds: float
    startup_timeout_seconds: float
    approval_required_tools: set[str]
    allowed_root: str | None

    @classmethod
    def from_env(cls) -> MCPClientSettings:
        """Load MCP bridge settings from the process environment."""
        command_line = os.getenv("MCP_SERVER_COMMAND", "").strip()
        mock_enabled = os.getenv("MCP_MOCK_ENABLED", "false").lower() in {"1", "true", "yes"}
        test_mode = os.getenv("MCP_TEST_MODE", "false").lower() in {"1", "true", "yes"}
        if not command_line and (mock_enabled or test_mode):
            command_line = "python -m app.mcp_demo_server"

        enabled = bool(command_line)
        if enabled:
            parts = shlex.split(command_line, posix=False)
            command = cls._normalize_python_command(parts[0])
            args = parts[1:]
        else:
            command = ""
            args = []

        approval_required = {
            item.strip()
            for item in os.getenv(
                "MCP_APPROVAL_REQUIRED_TOOLS",
                "dangerous_delete_file,send_email",
            ).split(",")
            if item.strip()
        }

        return cls(
            enabled=enabled,
            command=command,
            args=args,
            cwd=os.getenv("MCP_SERVER_CWD"),
            timeout_seconds=float(os.getenv("MCP_SERVER_TIMEOUT_SECONDS", "20")),
            startup_timeout_seconds=float(os.getenv("MCP_SERVER_STARTUP_TIMEOUT_SECONDS", "10")),
            approval_required_tools=approval_required,
            allowed_root=os.getenv("MCP_ALLOWED_ROOT"),
        )

    @staticmethod
    def _normalize_python_command(command: str) -> str:
        """Prefer the current interpreter when env config uses a generic Python launcher."""
        lowered = command.lower()
        if lowered in {"python", "python.exe", "py", "py.exe"}:
            return sys.executable
        return command


class MCPClientBridge:
    """Thin stdio MCP client that discovers tools and proxies tool calls."""

    def __init__(self, settings: MCPClientSettings) -> None:
        self._settings = settings
        self._tool_definitions: dict[str, MCPToolDefinition] = {}

    async def open(self) -> None:
        """Discover tools from the configured MCP server."""
        if not self._settings.enabled:
            return
        self._tool_definitions = await asyncio.wait_for(
            self._discover_tools(),
            timeout=self._settings.startup_timeout_seconds,
        )

    async def close(self) -> None:
        """Close hook for symmetry with app lifespan management."""
        await asyncio.sleep(0)

    async def has_tools(self) -> bool:
        """Return whether any MCP tools are available."""
        return bool(self._tool_definitions)

    async def list_tool_names(self) -> list[str]:
        """Return LangChain-visible tool names."""
        return sorted(self._tool_definitions.keys())

    def requires_approval(self, langchain_name: str) -> bool:
        """Return whether the local risk policy requires approval for a tool."""
        tool = self._tool_definitions.get(langchain_name)
        return bool(tool and tool.requires_approval)

    def get_definition(self, langchain_name: str) -> MCPToolDefinition | None:
        """Return tool metadata for one proxied MCP tool."""
        return self._tool_definitions.get(langchain_name)

    def get_langchain_tools(self) -> list[Any]:
        """Create LangChain tool proxies for all discovered MCP tools."""
        return [self._build_langchain_tool(item) for item in self._tool_definitions.values()]

    def call_tool_sync(self, langchain_name: str, arguments: dict[str, Any]) -> str:
        """Invoke one MCP tool and serialize the result as a stable JSON envelope."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call_tool_async(langchain_name, arguments))
        return self._run_coroutine_in_thread(self._call_tool_async(langchain_name, arguments))

    async def _discover_tools(self) -> dict[str, MCPToolDefinition]:
        """Open a one-shot MCP session and fetch the available tools."""
        if not self._settings.enabled:
            return {}

        discovered: dict[str, MCPToolDefinition] = {}
        async with self._session() as session:
            result = await session.list_tools()
            for tool in result.tools:
                server_name = str(tool.name)
                langchain_name = f"mcp_{server_name}"
                requires_approval = self._local_risk_policy(server_name)
                risk_level = "high" if requires_approval else "low"
                description = self._tool_description(tool, risk_level, requires_approval)
                discovered[langchain_name] = MCPToolDefinition(
                    server_name=server_name,
                    langchain_name=langchain_name,
                    description=description,
                    input_schema=dict(tool.inputSchema or {}),
                    requires_approval=requires_approval,
                    risk_level=risk_level,
                )
        return discovered

    async def _call_tool_async(self, langchain_name: str, arguments: dict[str, Any]) -> str:
        """Open a short-lived session and call one MCP tool."""
        definition = self._tool_definitions.get(langchain_name)
        if definition is None:
            return self._serialize_envelope(
                ok=False,
                tool_name=langchain_name,
                summary=f"MCP tool {langchain_name} is not available.",
                data={},
                error="tool_not_found",
            )

        try:
            async with self._session() as session:
                result = await session.call_tool(
                    definition.server_name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=self._settings.timeout_seconds),
                )
        except Exception as exc:
            return self._serialize_envelope(
                ok=False,
                tool_name=langchain_name,
                summary=f"MCP tool {definition.server_name} failed before completion.",
                data={"arguments": arguments},
                error=str(exc),
            )

        structured = result.structuredContent
        text_parts = self._text_parts(result.content)
        data: dict[str, Any] = {}
        if isinstance(structured, dict):
            data.update(structured)
        if text_parts:
            data["content_text"] = text_parts
        if "arguments" not in data:
            data["arguments"] = arguments

        summary = str(data.get("summary", "")).strip()
        if not summary:
            summary = text_parts[0] if text_parts else f"MCP tool {definition.server_name} completed."

        return self._serialize_envelope(
            ok=not result.isError,
            tool_name=langchain_name,
            summary=summary,
            data=data,
            error=None if not result.isError else summary,
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        """Create a short-lived stdio MCP session."""
        params = StdioServerParameters(
            command=self._settings.command,
            args=self._settings.args,
            env=self._child_env(),
            cwd=self._settings.cwd,
        )
        async with stdio_client(params) as streams:
            async with ClientSession(
                *streams,
                read_timeout_seconds=timedelta(seconds=self._settings.timeout_seconds),
            ) as session:
                await session.initialize()
                yield session

    def _build_langchain_tool(self, definition: MCPToolDefinition) -> StructuredTool:
        """Wrap one MCP tool as a LangChain StructuredTool."""
        args_schema = self._args_schema_from_json_schema(definition)

        def _invoke(**kwargs: Any) -> str:
            return self.call_tool_sync(definition.langchain_name, kwargs)

        _invoke.__name__ = definition.langchain_name
        _invoke.__doc__ = definition.description
        return StructuredTool.from_function(
            func=_invoke,
            name=definition.langchain_name,
            description=definition.description,
            args_schema=args_schema,
            infer_schema=False,
        )

    def _args_schema_from_json_schema(self, definition: MCPToolDefinition) -> type[BaseModel]:
        """Create a Pydantic model from the MCP tool input schema."""
        schema = definition.input_schema or {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        field_definitions: dict[str, tuple[Any, Field]] = {}

        for name, spec in properties.items():
            python_type = self._json_schema_type_to_python(spec)
            if name in required:
                annotation = python_type
                default = ...
            else:
                annotation = python_type | None
                default = None
            field_definitions[name] = (
                annotation,
                Field(
                    default=default,
                    description=str(spec.get("description", "")).strip() or None,
                ),
            )

        if not field_definitions:
            class EmptyArgs(BaseModel):
                """Empty MCP tool argument model."""

            return EmptyArgs

        model_name = "".join(part.title() for part in definition.langchain_name.split("_")) + "Args"
        return create_model(model_name, **field_definitions)

    @staticmethod
    def _json_schema_type_to_python(spec: dict[str, Any]) -> Any:
        """Map a simple JSON Schema property to a Python type."""
        json_type = spec.get("type")
        if json_type == "boolean":
            return bool
        if json_type == "integer":
            return int
        if json_type == "number":
            return float
        if json_type == "array":
            return list[Any]
        if json_type == "object":
            return dict[str, Any]
        return str

    def _child_env(self) -> dict[str, str]:
        """Build the environment used for the MCP server subprocess."""
        env = os.environ.copy()
        if self._settings.allowed_root:
            env["MCP_ALLOWED_ROOT"] = self._settings.allowed_root
        env["MCP_TRANSPORT"] = env.get("MCP_TRANSPORT", "stdio")
        return env

    def _local_risk_policy(self, server_name: str) -> bool:
        """Classify high-risk tools using local policy rather than server claims."""
        lowered = server_name.lower()
        if server_name in self._settings.approval_required_tools:
            return True
        risky_tokens = ("delete", "remove", "erase", "send_email", "email", "unlink")
        return any(token in lowered for token in risky_tokens)

    @staticmethod
    def _tool_description(
        tool: Tool,
        risk_level: str,
        requires_approval: bool,
    ) -> str:
        """Build a stable description for the LangChain wrapper."""
        risk_notice = (
            "This is a high-risk MCP tool and requires explicit human approval before execution."
            if requires_approval
            else "This MCP tool can run without extra human approval under the local policy."
        )
        original = str(tool.description or "").strip() or f"MCP tool {tool.name}"
        return (
            f"{original}\n\n"
            f"Remote MCP tool name: {tool.name}.\n"
            f"Risk level: {risk_level}.\n"
            f"{risk_notice}"
        )

    @staticmethod
    def _text_parts(content: list[Any]) -> list[str]:
        """Extract plain-text content parts from a CallToolResult."""
        result: list[str] = []
        for item in content:
            if isinstance(item, TextContent):
                text = str(item.text).strip()
                if text:
                    result.append(text)
            elif hasattr(item, "text"):
                text = str(getattr(item, "text")).strip()
                if text:
                    result.append(text)
        return result

    @staticmethod
    def _serialize_envelope(
        *,
        ok: bool,
        tool_name: str,
        summary: str,
        data: dict[str, Any],
        error: str | None,
    ) -> str:
        """Return a stable JSON envelope consistent with local tools."""
        return json.dumps(
            {
                "ok": ok,
                "tool_name": tool_name,
                "summary": summary,
                "data": data,
                "error": error,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _run_coroutine_in_thread(coroutine: Any) -> str:
        """Run a coroutine in a fresh thread when a loop is already active."""
        result: dict[str, Any] = {}

        def worker() -> None:
            try:
                result["value"] = asyncio.run(coroutine)
            except BaseException as exc:  # pragma: no cover - defensive guard
                result["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if "error" in result:
            raise result["error"]
        return str(result["value"])


@asynccontextmanager
async def managed_mcp_client() -> AsyncIterator[MCPClientBridge]:
    """Create and close the MCP stdio bridge for app lifespan."""
    client = MCPClientBridge(MCPClientSettings.from_env())
    await client.open()
    try:
        yield client
    finally:
        await client.close()

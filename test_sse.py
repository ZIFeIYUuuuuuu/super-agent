from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from app.streaming import decode_sse_payload

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parent
BASE_URL = "http://127.0.0.1:8010"
CHAT_PATH = "/v1/chat/completions"
PG_PORT = 55433
PG_DB = "agent_memory_test"
PG_DATA = ROOT / ".pgdata-memory-test"
PDF_DIR = ROOT / ".tool-test-artifacts"
RAG_DIR = ROOT / ".rag-test-artifacts"
APPROVAL_DIR = ROOT / ".approval-test-artifacts"
UPLOAD_ENDPOINTS = ("/v1/knowledge/documents", "/v1/knowledge/upload")


@dataclass(slots=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class StreamCapture:
    status_code: int
    headers: dict[str, str]
    events: list[dict[str, Any]]


class ServiceController:
    def __init__(self, app_module: str, host: str, port: int, env: dict[str, str], cwd: Path) -> None:
        self.app_module = app_module
        self.host = host
        self.port = port
        self.env = env
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self.stdout_path = cwd / "service.stdout.log"
        self.stderr_path = cwd / "service.stderr.log"
        self.stdout_handle = None
        self.stderr_handle = None

    def start(self) -> None:
        self.stdout_handle = self.stdout_path.open("w", encoding="utf-8")
        self.stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", self.app_module, "--host", self.host, "--port", str(self.port)],
            cwd=self.cwd,
            env=self.env,
            stdout=self.stdout_handle,
            stderr=self.stderr_handle,
            text=True,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"service exited early: {self.process.returncode}")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex((self.host, self.port)) == 0:
                    return
            time.sleep(0.5)
        raise TimeoutError("uvicorn did not become ready")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        self.process = None
        if self.stdout_handle is not None:
            self.stdout_handle.close()
            self.stdout_handle = None
        if self.stderr_handle is not None:
            self.stderr_handle.close()
            self.stderr_handle = None

    def cleanup_logs(self) -> None:
        for path in (self.stdout_path, self.stderr_path):
            if not path.exists():
                continue
            for attempt in range(5):
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.2)


class PostgresController:
    def __init__(self, pg_bin: Path, data_dir: Path, port: int, database: str) -> None:
        self.pg_bin = pg_bin
        self.data_dir = data_dir
        self.port = port
        self.database = database
        self.log_path = data_dir.with_suffix(".log")

    @property
    def database_url(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/{self.database}"

    @staticmethod
    def discover_bin_dir(explicit: str | None = None) -> Path:
        if explicit:
            path = Path(explicit)
            if (path / "initdb.exe").exists():
                return path
            raise FileNotFoundError(explicit)
        for root in (Path(r"D:\Program Files\PostgreSQL"), Path(r"C:\Program Files\PostgreSQL")):
            if not root.exists():
                continue
            for candidate in sorted(root.glob("*/bin"), reverse=True):
                if (candidate / "initdb.exe").exists() and (candidate / "pg_ctl.exe").exists():
                    return candidate
        raise FileNotFoundError("postgres bin dir not found")

    def start(self) -> None:
        if not (self.data_dir / "PG_VERSION").exists():
            self.data_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [str(self.pg_bin / "initdb.exe"), "-D", str(self.data_dir), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
                check=True,
            )
        self.stop()
        subprocess.run(
            [str(self.pg_bin / "pg_ctl.exe"), "start", "-D", str(self.data_dir), "-l", str(self.log_path), "-o", f"-p {self.port}"],
            check=True,
        )
        time.sleep(2)
        result = subprocess.run(
            [str(self.pg_bin / "psql.exe"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{self.database}';"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip() != "1":
            subprocess.run([str(self.pg_bin / "createdb.exe"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", self.database], check=True)

    def stop(self) -> None:
        subprocess.run([str(self.pg_bin / "pg_ctl.exe"), "stop", "-D", str(self.data_dir), "-m", "fast"], check=False)


class MockServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), MockHandler)
        host, port = self.server_address
        self.base_url = f"http://{host}:{port}"
        self.search_hits = 0
        self.article_hits = 0
        self.chat_hits = 0
        self.chat_tool_round1_hits = 0
        self.chat_tool_round2_hits = 0


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/search":
            self._handle_search()
            return
        if self.path == "/chat/completions":
            self._handle_chat_completions()
            return
        self.send_error(404)

    def _handle_search(self) -> None:
        server = self.server
        if not isinstance(server, MockServer):
            self.send_error(500)
            return
        server.search_hits += 1
        today = date.today().isoformat()
        self._send_json(
            {
                "answer": "Fresh tech news centers on AI chips and robotics funding.",
                "results": [
                    {"title": f"{today} AI chip vendor launches a new inference accelerator", "url": f"{server.base_url}/news/1", "content": "Latency and efficiency improved.", "published_date": today},
                    {"title": f"{today} Robotics startup closes a new funding round", "url": f"{server.base_url}/news/2", "content": "Capital supports production expansion.", "published_date": today},
                ],
            }
        )

    def _handle_chat_completions(self) -> None:
        server = self.server
        if not isinstance(server, MockServer):
            self.send_error(500)
            return
        server.chat_hits += 1

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self.send_error(404)
            return
        messages = payload.get("messages", [])
        tools = payload.get("tools", [])
        has_tools = isinstance(tools, list) and len(tools) > 0

        flattened_messages = " ".join(json.dumps(item, ensure_ascii=False) for item in messages if isinstance(item, dict))
        is_tool_probe = "QWEN_TOOL_TEST" in flattened_messages
        has_tavily_tool_result = (
            "tavily_news_search" in flattened_messages
            and (
                "Tool result from tavily_news_search" in flattened_messages
                or '"tool_name":"tavily_news_search"' in flattened_messages
                or '"tool_name": "tavily_news_search"' in flattened_messages
                or ('"role": "tool"' in flattened_messages and "tavily_news_search" in flattened_messages)
            )
        )

        if is_tool_probe and has_tools and not has_tavily_tool_result:
            server.chat_tool_round1_hits += 1
            self._send_json(
                {
                    "id": f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": str(payload.get("model", "qwen-plus")),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": f"call_{uuid.uuid4().hex[:10]}",
                                        "type": "function",
                                        "function": {
                                            "name": "tavily_news_search",
                                            "arguments": json.dumps(
                                                {
                                                    "query": "today technology news AI semiconductor cloud",
                                                    "topic": "news",
                                                    "time_range": "day",
                                                    "max_results": 3,
                                                    "include_raw_content": False,
                                                },
                                                ensure_ascii=False,
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            )
            return

        if is_tool_probe and has_tavily_tool_result:
            server.chat_tool_round2_hits += 1
            self._send_json(
                {
                    "id": f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": str(payload.get("model", "qwen-plus")),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "MOCK_QWEN_TOOL_CHAIN_OK：已完成联网检索并基于工具结果生成最终摘要。",
                            },
                        }
                    ],
                }
            )
            return

        self._send_json(
            {
                "id": f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": str(payload.get("model", "qwen-plus")),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "这是本地 OpenAI-compatible Mock 的中文响应。",
                        },
                    }
                ],
            }
        )

    def do_GET(self) -> None:  # noqa: N802
        server = self.server
        if not isinstance(server, MockServer):
            self.send_error(500)
            return
        if self.path == "/news/1":
            server.article_hits += 1
            time.sleep(0.25)
            self._send_html("<html><head><title>AI chip vendor launches a new inference accelerator</title></head><body><main><article><p>The accelerator improves LLM inference speed.</p><p>The target customers are cloud providers and enterprises.</p></article></main></body></html>")
            return
        if self.path == "/news/2":
            server.article_hits += 1
            time.sleep(0.25)
            self._send_html("<html><head><title>Robotics startup closes a new funding round</title></head><body><main><article><p>The company will expand production capacity.</p><p>The capital also supports supply-chain work.</p></article></main></body></html>")
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockServerRunner:
    def __init__(self) -> None:
        self.server = MockServer()
        self.thread = None

    def start(self) -> None:
        import threading

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


def _decode_b64_text(value: str) -> str:
    """Decode a UTF-8 base64 text payload."""
    return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")


def _normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy/new SSE payloads into {'type': ..., 'content': ...}."""
    if "content_b64" in payload:
        return decode_sse_payload(payload).model_dump()

    if "type" in payload and "content" in payload:
        normalized = dict(payload)
        if str(normalized.get("encoding", "")).lower() == "base64" and isinstance(
            normalized.get("content"), str
        ):
            normalized["content"] = _decode_b64_text(str(normalized["content"]))
        if isinstance(normalized.get("content_b64"), str):
            normalized["content"] = _decode_b64_text(str(normalized["content_b64"]))
        return normalized

    nested_data = payload.get("data")
    if isinstance(nested_data, dict) and "type" in nested_data:
        return _normalize_event_payload(dict(nested_data))

    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict) and "type" in nested_payload:
        return _normalize_event_payload(dict(nested_payload))

    for field in ("payload_b64", "data_b64"):
        encoded = payload.get(field)
        if isinstance(encoded, str):
            decoded = _decode_b64_text(encoded)
            nested = json.loads(decoded)
            if isinstance(nested, dict):
                return _normalize_event_payload(nested)

    return {
        "type": str(payload.get("type", payload.get("event", "error"))),
        "content": str(payload.get("content", payload)),
    }


def _parse_sse_data(raw_data: str) -> dict[str, Any] | None:
    """Parse one SSE data block into a normalized event payload."""
    content = raw_data.strip()
    if not content:
        return None
    if content == "[DONE]":
        return None

    parsed: Any
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        try:
            decoded = _decode_b64_text(content)
            parsed = json.loads(decoded)
        except Exception:
            parsed = {"type": "error", "content": content}

    if not isinstance(parsed, dict):
        return {"type": "error", "content": str(parsed)}
    return _normalize_event_payload(parsed)


async def iter_sse_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                event = _parse_sse_data("\n".join(data_lines))
                data_lines = []
                if event is not None:
                    yield event
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        event = _parse_sse_data("\n".join(data_lines))
        if event is not None:
            yield event


def chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{CHAT_PATH}"


async def collect_stream(
    client: httpx.AsyncClient,
    base_url: str,
    payload: dict[str, Any],
    label: str | None = None,
) -> StreamCapture:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", chat_url(base_url), json=payload) as response:
        async for event in iter_sse_events(response):
            events.append(event)
            prefix = f"[stream:{label}]" if label else "[stream]"
            print(f"{prefix} {event}")
        return StreamCapture(response.status_code, dict(response.headers), events)


def latest_answer(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "answer":
            return str(event.get("content", ""))
    return ""


def _contains_cjk_text(text: str) -> bool:
    """Return whether text contains any CJK ideographs."""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _count_type(events: list[dict[str, Any]], event_type: str) -> int:
    """Count events by stream type."""
    return sum(1 for event in events if str(event.get("type", "")).lower() == event_type)


async def scenario_default_chinese_answer(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    """Verify chat defaults to a Chinese final answer style."""
    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"zh-default-{uuid.uuid4().hex[:10]}",
            "messages": [
                {
                    "role": "user",
                    "content": "\u8bf7\u7528\u4e2d\u6587\u56de\u7b54\uff1a\u4eca\u5929\u5929\u6c14\u600e\u4e48\u6837\uff1f",
                }
            ],
        },
        label="zh-default",
    )
    if capture.status_code != 200:
        return ScenarioResult("default_chinese_answer", False, f"expected 200, got {capture.status_code}")

    answer = latest_answer(capture.events)
    if not answer:
        return ScenarioResult("default_chinese_answer", False, "missing final answer")
    if not _contains_cjk_text(answer):
        return ScenarioResult("default_chinese_answer", False, f"answer has no Chinese text: {answer!r}")

    known_placeholders = (
        "LangGraph agent reply",
        "I understood your request",
        "Reviewing the latest user request",
    )
    if any(marker in answer for marker in known_placeholders):
        return ScenarioResult("default_chinese_answer", False, f"placeholder answer leaked: {answer!r}")
    return ScenarioResult("default_chinese_answer", True, "Chinese default answer detected")


async def scenario_thought_hidden(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    """Verify thought stream can be hidden by request-level toggle."""
    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"hide-thought-{uuid.uuid4().hex[:10]}",
            "include_thought": False,
            "show_thought": False,
            "messages": [
                {
                    "role": "user",
                    "content": "Please answer briefly in Chinese and do not expose chain-of-thought.",
                }
            ],
        },
        label="hide-thought",
    )
    if capture.status_code != 200:
        return ScenarioResult("thought_hidden", False, f"expected 200, got {capture.status_code}")
    if not latest_answer(capture.events):
        return ScenarioResult("thought_hidden", False, "missing final answer")

    thought_count = _count_type(capture.events, "thought")
    if thought_count > 0:
        return ScenarioResult(
            "thought_hidden",
            False,
            f"expected 0 thought events when hidden, got {thought_count}",
        )
    return ScenarioResult("thought_hidden", True, "thought events hidden successfully")


async def scenario_thought_visible(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    """Verify thought stream can be explicitly enabled."""
    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"show-thought-{uuid.uuid4().hex[:10]}",
            "include_thought": True,
            "show_thought": True,
            "messages": [
                {
                    "role": "user",
                    "content": "Solve this request and include process events.",
                }
            ],
        },
        label="show-thought",
    )
    if capture.status_code != 200:
        return ScenarioResult("thought_visible", False, f"expected 200, got {capture.status_code}")
    if not latest_answer(capture.events):
        return ScenarioResult("thought_visible", False, "missing final answer")
    thought_count = _count_type(capture.events, "thought")
    if thought_count < 1:
        return ScenarioResult("thought_visible", False, "expected thought events but received none")
    return ScenarioResult("thought_visible", True, f"thought events visible ({thought_count})")


async def scenario_qwen_env_missing_fallback(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    managed_service: bool,
) -> ScenarioResult:
    """Verify missing Qwen/OpenAI env vars do not break chat response."""
    if not managed_service:
        return ScenarioResult(
            "qwen_env_missing_fallback",
            True,
            "skipped (requires --manage-service to control env)",
        )

    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"fallback-{uuid.uuid4().hex[:10]}",
            "messages": [
                {
                    "role": "user",
                    "content": "Please provide one concise Chinese answer.",
                }
            ],
        },
        label="fallback",
    )
    if capture.status_code != 200:
        return ScenarioResult("qwen_env_missing_fallback", False, f"expected 200, got {capture.status_code}")
    if not latest_answer(capture.events):
        return ScenarioResult("qwen_env_missing_fallback", False, "missing final answer")

    has_error = any(str(event.get("type", "")).lower() == "error" for event in capture.events)
    if has_error:
        return ScenarioResult("qwen_env_missing_fallback", False, "stream emitted error events")
    return ScenarioResult("qwen_env_missing_fallback", True, "fallback path remained available")


def contains_wait(events: list[dict[str, Any]]) -> bool:
    markers = ("waiting for approval", "waiting for human approval", "approval required")
    return any(event.get("type") == "thought" and any(m in str(event.get("content", "")).lower() for m in markers) for event in events)


def extract_approval_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        match = re.search(r"approval_id=([a-z0-9]{8,})", str(event.get("content", "")).lower())
        if match:
            return match.group(1)
    return None


async def approve_thread(client: httpx.AsyncClient, base_url: str, thread_id: str, approval_id: str) -> tuple[bool, str]:
    for url, payload in (
        (f"{base_url.rstrip('/')}/v1/approvals/decision", {"thread_id": thread_id, "approval_id": approval_id, "decision": "approve"}),
        (f"{base_url.rstrip('/')}/v1/approvals/resume", {"thread_id": thread_id, "approval_id": approval_id, "decision": "approve"}),
        (f"{base_url.rstrip('/')}/v1/approvals/{approval_id}/decision", {"thread_id": thread_id, "decision": "approve"}),
    ):
        response = await client.post(url, json=payload)
        if 200 <= response.status_code < 300:
            return True, url
    return False, "no approval endpoint accepted the request"


def build_env(database_url: str, mock: MockServerRunner) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["TAVILY_API_KEY"] = "test-key"
    env["TAVILY_API_URL"] = f"{mock.server.base_url}/search"
    env["TAVILY_SEARCH_URL"] = f"{mock.server.base_url}/search"
    env["TAVILY_BASE_URL"] = mock.server.base_url
    env["AGENT_TAVILY_SEARCH_URL"] = f"{mock.server.base_url}/search"
    env["AGENT_TOOL_SEARCH_URL"] = f"{mock.server.base_url}/search"
    env["AGENT_TOOL_MOCK_BASE_URL"] = f"{mock.server.base_url}/search"
    env["PDF_OUTPUT_DIR"] = str(PDF_DIR)
    env["AGENT_PDF_OUTPUT_DIR"] = str(PDF_DIR)
    env["ALLOW_LOCAL_TOOL_URLS"] = "true"
    env["MCP_TEST_MODE"] = "true"
    env["MCP_MOCK_ENABLED"] = "true"
    env["MCP_SERVER_COMMAND"] = f"{sys.executable} -m app.mcp_demo_server"
    env["MCP_APPROVAL_REQUIRED_TOOLS"] = "dangerous_delete_file,send_email,delete_file"
    env["MCP_ALLOWED_ROOT"] = str(ROOT)
    env["OPENAI_API_KEY"] = "mock-qwen-key"
    env["OPENAI_BASE_URL"] = mock.server.base_url
    env["OPENAI_MODEL"] = "qwen-plus"
    return env


async def upload_document(client: httpx.AsyncClient, base_url: str, file_path: Path, namespace_id: str) -> tuple[bool, str]:
    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    for endpoint in UPLOAD_ENDPOINTS:
        url = f"{base_url.rstrip('/')}{endpoint}"
        for field_name in ("file", "upload", "document"):
            with file_path.open("rb") as handle:
                response = await client.post(
                    url,
                    files={field_name: (file_path.name, handle, mime_type)},
                    data={"namespace_id": namespace_id, "thread_id": namespace_id},
                )
            if 200 <= response.status_code < 300:
                return True, f"{endpoint}:{field_name}"
        if file_path.suffix.lower() in {".md", ".markdown"}:
            response = await client.post(
                url,
                json={"filename": file_path.name, "content": file_path.read_text(encoding="utf-8"), "namespace_id": namespace_id, "thread_id": namespace_id},
            )
            if 200 <= response.status_code < 300:
                return True, f"{endpoint}:json"
    return False, "upload failed"


async def scenario_tool_chain_news_to_pdf(base_url: str, timeout: float, mock: MockServerRunner) -> ScenarioResult:
    before = set(PDF_DIR.glob("*.pdf"))
    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        capture = await collect_stream(client, base_url, {"thread_id": f"tool-{uuid.uuid4().hex[:12]}", "messages": [{"role": "user", "content": "Search today's technology news and generate a PDF summary."}]})
    if capture.status_code != 200:
        return ScenarioResult("tool_chain_news_to_pdf", False, f"expected 200, got {capture.status_code}")
    if not latest_answer(capture.events):
        return ScenarioResult("tool_chain_news_to_pdf", False, "missing final answer")
    if mock.server.search_hits < 1 or mock.server.article_hits < 2:
        return ScenarioResult("tool_chain_news_to_pdf", False, "tool chain was not fully exercised")
    created = [path for path in PDF_DIR.glob("*.pdf") if path not in before]
    if not created:
        answer = latest_answer(capture.events)
        matched = re.search(r"([A-Za-z]:\\[^ \n]+\.pdf)", answer)
        if matched:
            candidate = Path(matched.group(1))
            if candidate.exists():
                created = [candidate]
    if not created:
        all_pdfs = sorted(PDF_DIR.glob("*.pdf"), key=lambda item: item.stat().st_mtime, reverse=True)
        if all_pdfs:
            created = [all_pdfs[0]]
    if not created:
        return ScenarioResult("tool_chain_news_to_pdf", False, "no PDF was generated")
    elapsed = time.perf_counter() - started_at
    return ScenarioResult(
        "tool_chain_news_to_pdf",
        True,
        f"generated {sorted(created)[-1].name}; article_hits={mock.server.article_hits}; elapsed={elapsed:.2f}s",
    )


async def scenario_real_qwen_tool_calling_mock(
    client: httpx.AsyncClient,
    base_url: str,
    mock: MockServerRunner,
) -> ScenarioResult:
    """Verify OpenAI-compatible Qwen tool-calling flow using local mock backend."""
    before_search_hits = mock.server.search_hits
    before_round1 = mock.server.chat_tool_round1_hits
    before_round2 = mock.server.chat_tool_round2_hits

    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"qwen-tool-{uuid.uuid4().hex[:12]}",
            "show_thoughts": True,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "QWEN_TOOL_TEST: 请通过工具调用完成一次联网检索，"
                        "并在拿到工具结果后给出最终摘要。"
                    ),
                }
            ],
        },
        label="qwen-tool",
    )
    if capture.status_code != 200:
        return ScenarioResult("real_qwen_tool_calling_mock", False, f"expected 200, got {capture.status_code}")

    answer = latest_answer(capture.events)
    if "MOCK_QWEN_TOOL_CHAIN_OK" not in answer:
        return ScenarioResult(
            "real_qwen_tool_calling_mock",
            False,
            f"missing mock completion marker; answer={answer!r}",
        )

    if mock.server.search_hits <= before_search_hits:
        return ScenarioResult(
            "real_qwen_tool_calling_mock",
            False,
            "search tool was not invoked by the tool-calling chain",
        )
    if mock.server.chat_tool_round1_hits <= before_round1:
        return ScenarioResult(
            "real_qwen_tool_calling_mock",
            False,
            "mock chat did not receive a tool-calls planning round",
        )
    if mock.server.chat_tool_round2_hits <= before_round2:
        return ScenarioResult(
            "real_qwen_tool_calling_mock",
            False,
            "mock chat did not receive a post-tool final-answer round",
        )
    return ScenarioResult("real_qwen_tool_calling_mock", True, "mock Qwen tool-calling chain completed")


async def scenario_rag_private_doc_quote(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    namespace_id = f"rag-{uuid.uuid4().hex[:12]}"
    unique_code = f"ORBIT-{uuid.uuid4().hex[:10].upper()}"
    launch_date = "2031-09-17"
    security_phrase = f"cobalt-harbor-{uuid.uuid4().hex[:8]}"
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RAG_DIR / "private-brief.md"
    pdf_path = RAG_DIR / "private-brief.pdf"
    md_path.write_text(f"# Private Internal Brief\n\nProgram code: {unique_code}\nLaunch date: {launch_date}\nSecurity phrase: {security_phrase}\n", encoding="utf-8")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
        for idx, line in enumerate([f"Program code: {unique_code}", f"Launch date: {launch_date}", f"Security phrase: {security_phrase}"]):
            pdf.drawString(72, 800 - idx * 22, line)
        pdf.save()
    except Exception:
        pass
    md_ok, _ = await upload_document(client, base_url, md_path, namespace_id)
    pdf_ok = False
    if pdf_path.exists():
        pdf_ok, _ = await upload_document(client, base_url, pdf_path, namespace_id)
    if not md_ok and not pdf_ok:
        return ScenarioResult("rag_private_doc_quote", False, "could not upload private docs")
    capture = await collect_stream(client, base_url, {"thread_id": namespace_id, "knowledge_namespace": namespace_id, "messages": [{"role": "user", "content": "From the private knowledge base, what are the exact launch date and security phrase? Return both values."}]})
    answer = latest_answer(capture.events)
    if capture.status_code != 200 or launch_date not in answer or security_phrase not in answer:
        return ScenarioResult("rag_private_doc_quote", False, f"unexpected answer: {answer!r}")
    return ScenarioResult("rag_private_doc_quote", True, "private facts were cited correctly")


async def scenario_hil_approval_resume(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    thread_id = f"hil-{uuid.uuid4().hex[:12]}"
    target = APPROVAL_DIR / f"to-delete-{thread_id}.txt"
    target.write_text("delete me after approval", encoding="utf-8")
    first = await collect_stream(client, base_url, {"thread_id": thread_id, "messages": [{"role": "user", "content": f'Use the high-risk MCP delete-file operation to delete this path: "{target}". Require human approval before execution.'}]})
    if first.status_code != 200:
        return ScenarioResult("hil_approval_resume", False, f"expected 200, got {first.status_code}")
    if not target.exists():
        return ScenarioResult("hil_approval_resume", False, "file was deleted before approval")
    if not contains_wait(first.events):
        return ScenarioResult("hil_approval_resume", False, "missing waiting-for-approval thought")
    approval_id = extract_approval_id(first.events)
    if not approval_id:
        return ScenarioResult("hil_approval_resume", False, "approval_id was not exposed in SSE thought")
    approved, detail = await approve_thread(client, base_url, thread_id, approval_id)
    if not approved:
        return ScenarioResult("hil_approval_resume", False, detail)
    second = await collect_stream(client, base_url, {"thread_id": thread_id, "messages": []})
    if second.status_code != 200:
        return ScenarioResult("hil_approval_resume", False, f"resume expected 200, got {second.status_code}")
    if not latest_answer(second.events):
        return ScenarioResult("hil_approval_resume", False, "missing final answer after resume")
    if target.exists():
        return ScenarioResult("hil_approval_resume", False, "file still exists after approved resume")
    return ScenarioResult("hil_approval_resume", True, f"approval resumed via {detail}")


async def scenario_sse_special_char_integrity(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    thread_id = f"sse-special-{uuid.uuid4().hex[:12]}"
    probe = (
        "SSE integrity check:\n"
        "line-1 keeps newline\n"
        "line-2 keeps symbols <> [] {} \" ' \\\\ /\n"
        "line-3 keeps utf8: 中文, русский, العربية, emoji🚀"
    )
    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": thread_id,
            "messages": [{"role": "user", "content": probe}],
        },
        label="special",
    )
    if capture.status_code != 200:
        return ScenarioResult("sse_special_char_integrity", False, f"expected 200, got {capture.status_code}")

    answer = latest_answer(capture.events)
    if not answer:
        return ScenarioResult("sse_special_char_integrity", False, "missing final answer")

    required_markers = [
        "line-1 keeps newline",
        "line-2 keeps symbols",
        "中文",
        "emoji🚀",
    ]
    missing = [marker for marker in required_markers if marker not in answer]
    if missing:
        return ScenarioResult(
            "sse_special_char_integrity",
            False,
            f"answer lost marker(s): {missing}; answer={answer!r}",
        )
    if "\n" not in answer:
        return ScenarioResult("sse_special_char_integrity", False, "answer lost newline characters")
    return ScenarioResult("sse_special_char_integrity", True, "newlines and utf-8 symbols survived streaming")


async def _run_one_concurrent_chat(
    client: httpx.AsyncClient,
    base_url: str,
    index: int,
) -> tuple[bool, str]:
    capture = await collect_stream(
        client,
        base_url,
        {
            "thread_id": f"perf-{index}-{uuid.uuid4().hex[:8]}",
            "show_thoughts": False,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Concurrent SSE performance check #{index}. "
                        "Please provide a short final answer with this index."
                    ),
                }
            ],
        },
        label=f"c{index}",
    )
    if capture.status_code != 200:
        return False, f"#{index}: HTTP {capture.status_code}"
    answer = latest_answer(capture.events)
    if not answer:
        return False, f"#{index}: missing final answer"
    error_count = sum(1 for event in capture.events if event.get("type") == "error")
    if error_count:
        return False, f"#{index}: error events present ({error_count})"
    return True, f"#{index}: events={len(capture.events)}"


async def scenario_high_concurrency_stream(base_url: str, timeout: float, concurrency: int = 12) -> ScenarioResult:
    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        task_results = await asyncio.gather(
            *[_run_one_concurrent_chat(client, base_url, idx) for idx in range(concurrency)],
            return_exceptions=True,
        )

    failures: list[str] = []
    for result in task_results:
        if isinstance(result, Exception):
            failures.append(f"exception={result}")
            continue
        ok, detail = result
        if not ok:
            failures.append(detail)

    elapsed = time.perf_counter() - started_at
    if failures:
        preview = "; ".join(failures[:4])
        return ScenarioResult(
            "high_concurrency_stream",
            False,
            f"{len(failures)}/{concurrency} flows failed in {elapsed:.2f}s: {preview}",
        )

    return ScenarioResult(
        "high_concurrency_stream",
        True,
        f"{concurrency} parallel flows all completed in {elapsed:.2f}s",
    )


async def scenario_empty_input(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    response = await client.post(chat_url(base_url), json={"messages": []})
    return ScenarioResult("empty_input", response.status_code >= 400, f"HTTP {response.status_code}")


async def scenario_malformed_json(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    response = await client.post(chat_url(base_url), headers={"content-type": "application/json"}, content='{"messages":[{"role":"user","content":"x"}')
    return ScenarioResult("malformed_json", response.status_code >= 400, f"HTTP {response.status_code}")


async def scenario_task_failure(client: httpx.AsyncClient, base_url: str) -> ScenarioResult:
    capture = await collect_stream(client, base_url, {"messages": [{"role": "user", "content": "__FORCE_TASK_FAILURE__"}]})
    passed = capture.status_code >= 500 or any(str(e.get("type", "")).lower() == "error" for e in capture.events)
    return ScenarioResult("task_failure", passed, f"HTTP {capture.status_code}")


async def run_all(args: argparse.Namespace) -> int:
    database_url = args.database_url or os.getenv("DATABASE_URL")
    postgres: PostgresController | None = None
    service: ServiceController | None = None
    mock = MockServerRunner()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    if args.manage_postgres:
        postgres = PostgresController(PostgresController.discover_bin_dir(args.pg_bin_dir), Path(args.pg_data_dir), args.pg_port, args.pg_database)
        postgres.start()
        database_url = postgres.database_url
    if args.manage_service and database_url is None:
        raise RuntimeError("database URL is required when --manage-service is enabled")
    mock.start()
    if args.manage_service and database_url is not None:
        service = ServiceController(args.app_module, args.host, args.port, build_env(database_url, mock), ROOT)
        service.start()
    results: list[ScenarioResult] = []
    try:
        results.append(await scenario_tool_chain_news_to_pdf(args.base_url, args.timeout, mock))
        async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout)) as client:
            results.append(await scenario_real_qwen_tool_calling_mock(client, args.base_url, mock))
            results.append(await scenario_default_chinese_answer(client, args.base_url))
            results.append(await scenario_thought_hidden(client, args.base_url))
            results.append(await scenario_thought_visible(client, args.base_url))
            results.append(
                await scenario_qwen_env_missing_fallback(
                    client,
                    args.base_url,
                    managed_service=args.manage_service,
                )
            )
            results.append(await scenario_rag_private_doc_quote(client, args.base_url))
            results.append(await scenario_hil_approval_resume(client, args.base_url))
            results.append(await scenario_sse_special_char_integrity(client, args.base_url))
            results.append(await scenario_empty_input(client, args.base_url))
            results.append(await scenario_malformed_json(client, args.base_url))
            results.append(await scenario_task_failure(client, args.base_url))
        results.append(await scenario_high_concurrency_stream(args.base_url, args.timeout))
    finally:
        if service is not None:
            service.stop()
            service.cleanup_logs()
        mock.stop()
        if postgres is not None:
            postgres.stop()
    print("\n=== SSE test summary ===")
    failed = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
        if not result.passed:
            failed += 1
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSE verifier for LangGraph tool calling with PostgreSQL")
    parser.add_argument("--base-url", type=str, default=BASE_URL)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--manage-service", action="store_true")
    parser.add_argument("--manage-postgres", action="store_true")
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--app-module", type=str, default="main:app")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--pg-bin-dir", type=str, default=None)
    parser.add_argument("--pg-data-dir", type=str, default=str(PG_DATA))
    parser.add_argument("--pg-port", type=int, default=PG_PORT)
    parser.add_argument("--pg-database", type=str, default=PG_DB)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_all(parse_args())))

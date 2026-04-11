from __future__ import annotations

import base64
import json
from typing import Any, AsyncIterator

from langchain_core.messages import ToolMessage

from app.agent import AgentRuntime
from app.models import ChatCompletionRequest, ChatStreamEvent

SSE_PROTOCOL_VERSION = 1
SSE_ENCODING = "base64+utf-8"


def build_sse_payload(event: ChatStreamEvent) -> dict[str, Any]:
    """Build the robust wire payload used for every SSE event."""
    encoded = _encode_content(event.content)
    return {
        "v": SSE_PROTOCOL_VERSION,
        "encoding": SSE_ENCODING,
        "type": event.type,
        "content_b64": encoded,
        "content_bytes": len(event.content.encode("utf-8")),
    }


def format_sse_data(event: ChatStreamEvent) -> str:
    """Serialize one event using the stable base64-backed SSE envelope."""
    payload = build_sse_payload(event)
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def decode_sse_payload(payload: dict[str, Any]) -> ChatStreamEvent:
    """Decode either the new SSE envelope or the legacy plain-text payload."""
    if "content_b64" in payload:
        raw_type = str(payload.get("type", "")).strip()
        content = _decode_content(str(payload.get("content_b64", "")))
        return ChatStreamEvent(type=raw_type, content=content)

    return ChatStreamEvent(
        type=str(payload.get("type", "")).strip(),
        content=str(payload.get("content", "")),
    )


def decode_sse_data_line(line: str) -> ChatStreamEvent | None:
    """Decode a raw `data:` line into a normalized stream event."""
    if not line or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return None
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("SSE payload must be a JSON object")
    return decode_sse_payload(parsed)


def _encode_content(content: str) -> str:
    """Encode content so SSE framing never depends on raw text characters."""
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def _decode_content(encoded: str) -> str:
    """Decode a base64-encoded UTF-8 content field."""
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception as exc:  # pragma: no cover - guard for malformed payloads
        raise ValueError("Invalid SSE base64 content") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - guard for malformed payloads
        raise ValueError("Invalid SSE UTF-8 content") from exc


def _map_langgraph_update(update: dict[str, Any]) -> list[ChatStreamEvent]:
    """Convert one LangGraph update payload into public SSE events."""
    events: list[ChatStreamEvent] = []
    payload: Any = update.get("data") if update.get("type") == "updates" else update
    if not isinstance(payload, dict):
        return events

    interrupts = payload.get("__interrupt__")
    if interrupts:
        message = _summarize_interrupts(interrupts)
        if message:
            events.append(ChatStreamEvent(type="thought", content=message))

    for node_name in ("retrieve_context", "call_model", "approval_gate", "await_approval"):
        node_update = payload.get(node_name)
        if isinstance(node_update, dict):
            summary = str(
                node_update.get("approval_message")
                or node_update.get("approval_thought")
                or node_update.get("human_review_message")
                or node_update.get("thought")
                or node_update.get("retrieval_summary")
                or ""
            ).strip()
            if summary:
                events.append(ChatStreamEvent(type="thought", content=summary))

    tools_update: Any = payload.get("tools")
    if isinstance(tools_update, dict):
        tool_messages: Any = tools_update.get("messages", [])
        if isinstance(tool_messages, list):
            for tool_message in tool_messages:
                summary = _summarize_tool_message(tool_message)
                if summary:
                    events.append(ChatStreamEvent(type="thought", content=summary))

    emit_answer_update: Any = payload.get("emit_answer")
    if isinstance(emit_answer_update, dict):
        answer = str(emit_answer_update.get("answer", "")).strip()
        if answer:
            events.append(ChatStreamEvent(type="answer", content=answer))

    return _dedupe_adjacent(events)


def _summarize_interrupts(interrupts: Any) -> str:
    """Turn LangGraph interrupts into approval-oriented thought text."""
    items = list(interrupts) if isinstance(interrupts, (list, tuple)) else [interrupts]
    if not items:
        return ""

    first = items[0]
    value = getattr(first, "value", first)
    if isinstance(value, dict):
        message = str(
            value.get("message")
            or value.get("approval_message")
            or value.get("summary")
            or ""
        ).strip()
        if message:
            return message
        approval_id = str(value.get("approval_id", "")).strip()
        tool_name = str(value.get("tool_name", "tool")).strip() or "tool"
        if approval_id:
            return f"Waiting for human approval before running {tool_name}. approval_id={approval_id}"
        return f"Waiting for human approval before running {tool_name}."
    return str(value).strip()


def _summarize_tool_message(message: Any) -> str:
    """Convert one ToolMessage payload into a concise thought summary."""
    tool_name = ""
    raw_content = ""

    if isinstance(message, ToolMessage):
        tool_name = str(message.name or "tool").strip()
        raw_content = _normalize_message_content(message.content)
    elif isinstance(message, dict):
        tool_name = str(message.get("name", "tool")).strip()
        raw_content = _normalize_message_content(message.get("content", ""))
    else:
        return ""

    if not raw_content:
        return f"Tool {tool_name or 'tool'} returned a result."

    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        compact = raw_content[:180].strip()
        return f"Tool {tool_name or 'tool'} returned: {compact}"

    if not isinstance(payload, dict):
        return f"Tool {tool_name or 'tool'} completed."

    approval_status = str(
        payload.get("approval_status")
        or payload.get("status")
        or payload.get("state")
        or payload.get("decision")
        or ""
    ).strip()
    if payload.get("requires_approval") or approval_status:
        if approval_status in {"pending", "awaiting", "waiting"}:
            approval_id = str(payload.get("approval_id", "")).strip()
            if approval_id:
                return f"Waiting for human approval. approval_id={approval_id}"
            return "Waiting for human approval."
        if approval_status in {"approved", "approve"}:
            return "Approval received, resuming execution."
        if approval_status in {"rejected", "reject"}:
            target = str(payload.get("target") or tool_name or "the guarded action").strip()
            return f"Approval rejected, skipped {target}."

    summary = str(payload.get("summary", "")).strip()
    if summary:
        return f"Tool {tool_name or 'tool'}: {summary}"
    error = str(payload.get("error", "")).strip()
    if error:
        return f"Tool {tool_name or 'tool'} failed: {error}"
    return f"Tool {tool_name or 'tool'} completed."


def _normalize_message_content(content: Any) -> str:
    """Flatten LangChain message content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    return str(content).strip()


def _dedupe_adjacent(events: list[ChatStreamEvent]) -> list[ChatStreamEvent]:
    """Avoid repeating the same thought message in adjacent updates."""
    deduped: list[ChatStreamEvent] = []
    for event in events:
        if deduped and deduped[-1].type == event.type and deduped[-1].content == event.content:
            continue
        deduped.append(event)
    return deduped


def _should_emit_event(event: ChatStreamEvent, show_thoughts: bool) -> bool:
    """Whether one mapped event should be visible to the API caller."""
    if event.type != "thought":
        return True
    if show_thoughts:
        return True
    lowered = event.content.lower()
    critical_markers = (
        "approval",
        "approval_id",
        "awaiting_approval",
        "waiting for human approval",
    )
    return any(marker in lowered for marker in critical_markers)


async def iter_stream_events(
    payload: ChatCompletionRequest,
    runtime: AgentRuntime,
    thread_id: str,
) -> AsyncIterator[ChatStreamEvent]:
    """Yield normalized public stream events from LangGraph updates."""
    show_thoughts = bool(payload.show_thoughts)
    async for update in runtime.astream_updates(payload, thread_id):
        for mapped_event in _map_langgraph_update(update):
            if _should_emit_event(mapped_event, show_thoughts):
                yield mapped_event


async def stream_chat_events(
    payload: ChatCompletionRequest,
    runtime: AgentRuntime,
    thread_id: str,
) -> AsyncIterator[str]:
    """Yield SSE-formatted events derived from LangGraph execution."""
    async for event in iter_stream_events(payload, runtime, thread_id):
        yield format_sse_data(event)


async def collect_chat_events(
    payload: ChatCompletionRequest,
    runtime: AgentRuntime,
    thread_id: str,
) -> list[ChatStreamEvent]:
    """Collect the normalized events for non-streaming JSON responses."""
    collected: list[ChatStreamEvent] = []
    async for event in iter_stream_events(payload, runtime, thread_id):
        collected.append(event)
    return collected

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter
import threading
from typing import Annotated, Any, AsyncIterator, Awaitable, Callable, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from app.approvals import ApprovalStore
from app.llm import DeterministicToolCallingLLM, LLMDecision
from app.mcp_client import MCPClientBridge
from app.models import ChatCompletionRequest, ChatMessage
from app.rag import KnowledgeBase
from app.tools import get_agent_tools

NextStep = Literal["approval_gate", "await_approval", "tools", "emit_answer", "finish"]


class AgentState(TypedDict):
    """Internal LangGraph state for one controllable agent turn."""

    messages: Annotated[list[BaseMessage], add_messages]
    next_step: NextStep
    step_count: int
    max_steps: int
    thought: str
    answer: str
    thread_id: str
    knowledge_namespace: str
    retrieval_queries: list[str]
    retrieval_hits: list[dict[str, Any]]
    retrieval_context: str
    pending_approval_id: str
    approval_status: str
    approval_summary: str
    pending_tool_name: str
    pending_tool_args: dict[str, Any]


class AgentRuntime:
    """Owns the LangGraph workflow, approval gate, tool node, and planner."""

    def __init__(
        self,
        checkpointer: PostgresSaver,
        knowledge_base: KnowledgeBase,
        approval_store: ApprovalStore,
        mcp_client: MCPClientBridge,
        llm: DeterministicToolCallingLLM | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._knowledge_base = knowledge_base
        self._approval_store = approval_store
        self._mcp_client = mcp_client
        tool_definitions = get_agent_tools() + self._mcp_client.get_langchain_tools()
        available_tool_names = {tool.name for tool in tool_definitions if getattr(tool, "name", "")}
        self._llm = llm or DeterministicToolCallingLLM(
            available_tool_names=available_tool_names,
            tool_definitions=tool_definitions,
        )
        self._is_open = False
        self._tool_node = ToolNode(
            tool_definitions,
            handle_tool_errors=self._handle_tool_error,
            awrap_tool_call=self._timed_tool_call,
        )
        self._graph = self._build_graph()

    async def open(self) -> None:
        """Acquire any async resources required by the runtime."""
        await asyncio.sleep(0)
        self._is_open = True

    async def close(self) -> None:
        """Release async resources held by the runtime."""
        await asyncio.sleep(0)
        self._is_open = False

    async def has_resumable_approval(self, thread_id: str) -> bool:
        """Return whether the thread has a resolved approval waiting to resume."""
        record = await self._approval_store.get_resumable_for_thread(thread_id)
        return record is not None

    async def astream_updates(
        self,
        payload: ChatCompletionRequest,
        thread_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream LangGraph updates for one chat-completion request."""
        self._ensure_open()
        graph_input = await self._graph_input_for_request(payload, thread_id)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | BaseException | None] = asyncio.Queue()

        def worker() -> None:
            try:
                for update in self._graph.stream(
                    graph_input,
                    config=self._config_for_thread(thread_id),
                    stream_mode="updates",
                    version="v2",
                ):
                    normalized = dict(update) if isinstance(update, dict) else {"type": "updates", "data": update}
                    loop.call_soon_threadsafe(queue.put_nowait, normalized)
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item

    async def ainvoke(
        self,
        payload: ChatCompletionRequest,
        thread_id: str,
    ) -> AgentState:
        """Run the graph to completion and return the final state."""
        self._ensure_open()
        graph_input = await self._graph_input_for_request(payload, thread_id)
        result: dict[str, Any] = await asyncio.to_thread(
            self._graph.invoke,
            graph_input,
            self._config_for_thread(thread_id),
        )
        return AgentState(**result)

    @staticmethod
    def resolve_thread_id(payload: ChatCompletionRequest) -> str:
        """Return the user thread ID or generate a new conversation ID."""
        return payload.thread_id or uuid4().hex

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("retrieve_context", self._timed_sync_node("retrieve_context", self.retrieve_context))
        builder.add_node("call_model", self._timed_sync_node("call_model", self.call_model))
        builder.add_node("approval_gate", self._timed_sync_node("approval_gate", self.approval_gate))
        builder.add_node("await_approval", self._timed_sync_node("await_approval", self.await_approval))
        builder.add_node("tools", self._timed_sync_node("tools", self.run_tools))
        builder.add_node("emit_answer", self._timed_sync_node("emit_answer", self.emit_answer))
        builder.add_edge(START, "retrieve_context")
        builder.add_edge("retrieve_context", "call_model")
        builder.add_conditional_edges(
            "call_model",
            self.route_next_step,
            {
                "approval_gate": "approval_gate",
                "emit_answer": "emit_answer",
                "finish": END,
            },
        )
        builder.add_conditional_edges(
            "approval_gate",
            self.route_next_step,
            {
                "await_approval": "await_approval",
                "tools": "tools",
                "emit_answer": "emit_answer",
                "finish": END,
            },
        )
        builder.add_conditional_edges(
            "await_approval",
            self.route_next_step,
            {
                "tools": "tools",
                "emit_answer": "emit_answer",
                "finish": END,
            },
        )
        builder.add_edge("tools", "call_model")
        builder.add_edge("emit_answer", END)
        return builder.compile(checkpointer=self._checkpointer)

    def retrieve_context(self, state: AgentState) -> dict[str, object]:
        """Retrieve private knowledge snippets and stage them for system injection."""
        latest_user_message = self._latest_user_message(state["messages"])
        namespace_id = state["knowledge_namespace"].strip()
        if not latest_user_message or not namespace_id:
            return {
                "retrieval_queries": [],
                "retrieval_hits": [],
                "retrieval_context": "",
                "thought": "",
            }

        try:
            queries, hits, context = asyncio.run(
                self._knowledge_base.retrieve(
                    namespace_id=namespace_id,
                    question=latest_user_message,
                )
            )
        except Exception as exc:
            return {
                "retrieval_queries": [],
                "retrieval_hits": [],
                "retrieval_context": "",
                "thought": f"Knowledge retrieval was skipped because the retriever failed: {exc}",
            }

        if not hits:
            return {
                "retrieval_queries": queries,
                "retrieval_hits": [],
                "retrieval_context": "",
                "thought": "",
            }

        return {
            "retrieval_queries": queries,
            "retrieval_hits": [asdict(hit) for hit in hits],
            "retrieval_context": context,
            "thought": (
                f"Knowledge retrieval matched {len(hits)} chunk(s) in namespace "
                f"{namespace_id}; reranked context is ready."
            ),
        }

    def call_model(self, state: AgentState) -> dict[str, object]:
        """Call the deterministic planner and record the next action."""
        augmented_messages = list(state["messages"])
        retrieval_context = state["retrieval_context"].strip()
        if retrieval_context:
            augmented_messages = [SystemMessage(content=retrieval_context), *augmented_messages]

        decision: LLMDecision = self._llm.invoke(
            augmented_messages,
            retrieved_chunks=state["retrieval_hits"],
        )
        next_step: NextStep = "approval_gate" if decision.next_step == "tools" else decision.next_step
        return {
            "messages": [decision.message],
            "next_step": next_step,
            "step_count": state["step_count"] + 1,
            "thought": decision.thought,
            "answer": decision.answer,
        }

    def approval_gate(self, state: AgentState) -> dict[str, object]:
        """Create a pending approval record before any high-risk tools run."""
        latest_ai = self._latest_ai_message(state["messages"])
        tool_calls = list(getattr(latest_ai, "tool_calls", []) or [])
        if not tool_calls:
            return {"next_step": "finish"}

        guarded_calls = [
            {"name": str(call.get("name", "")).strip(), "args": dict(call.get("args") or {})}
            for call in tool_calls
            if self._mcp_client.requires_approval(str(call.get("name", "")).strip())
        ]
        if not guarded_calls:
            return {"next_step": "tools"}

        approval_name = self._approval_batch_name(guarded_calls)
        summary = self._summarize_tool_batch(guarded_calls)
        record = asyncio.run(
            self._approval_store.create_pending(
                thread_id=state["thread_id"],
                tool_name=approval_name,
                risk_level="high",
                summary=summary,
                tool_args={"calls": guarded_calls},
            )
        )
        waiting_message = (
            f"High-risk MCP tool {approval_name} is waiting for human approval. "
            f"approval_id={record.approval_id}"
            if len(guarded_calls) == 1
            else (
                "High-risk MCP tools are waiting for human approval. "
                f"approval_id={record.approval_id}"
            )
        )
        return {
            "next_step": "await_approval",
            "pending_approval_id": record.approval_id,
            "approval_status": record.status,
            "approval_summary": record.summary,
            "pending_tool_name": approval_name,
            "pending_tool_args": {"calls": guarded_calls},
            "thought": waiting_message,
        }

    def await_approval(self, state: AgentState) -> dict[str, object]:
        """Pause the graph until a human approves or rejects the pending tool call."""
        approval_id = state["pending_approval_id"].strip()
        tool_name = state["pending_tool_name"].strip()
        summary = state["approval_summary"].strip() or self._summarize_tool_batch(
            list(state["pending_tool_args"].get("calls", []))
        )
        if not approval_id or not tool_name:
            return {"next_step": "finish"}

        decision_payload = interrupt(
            {
                "kind": "approval_required",
                "approval_id": approval_id,
                "thread_id": state["thread_id"],
                "tool_name": tool_name,
                "summary": summary,
                "risk_level": "high",
                "message": (
                    f"Waiting for human approval before running {tool_name}. "
                    f"approval_id={approval_id}"
                ),
            }
        )
        decision = self._normalize_approval_decision(decision_payload)
        asyncio.run(self._approval_store.mark_resumed(approval_id))

        if decision == "approved":
            return {
                "approval_status": "approved",
                "next_step": "tools",
                "thought": "Approval received, resuming execution.",
            }

        answer = f"Human approval rejected. Skipped high-risk tool {tool_name}."
        return {
            "approval_status": "rejected",
            "next_step": "emit_answer",
            "answer": answer,
            "thought": f"Approval rejected, skipped {tool_name}.",
        }

    def run_tools(self, state: AgentState) -> Any:
        """Execute the current batch of tool calls via ToolNode async gather."""
        return asyncio.run(self._tool_node.ainvoke(state))

    def emit_answer(self, state: AgentState) -> dict[str, object]:
        """Expose the final answer in a dedicated graph update."""
        latest_answer = state["answer"]
        if not latest_answer:
            latest_ai = self._latest_ai_message(state["messages"])
            latest_answer = latest_ai.content if latest_ai is not None else ""
        return {
            "next_step": "finish",
            "step_count": state["step_count"] + 1,
            "answer": str(latest_answer).strip(),
        }

    @staticmethod
    def route_next_step(state: AgentState) -> NextStep:
        """Pick the next node from the current agent state."""
        if state["step_count"] >= state["max_steps"]:
            return "emit_answer" if state["answer"] else "finish"
        return state["next_step"]

    async def _graph_input_for_request(
        self,
        payload: ChatCompletionRequest,
        thread_id: str,
    ) -> AgentState | Command[str]:
        resumable = await self._approval_store.get_resumable_for_thread(thread_id)
        if resumable is not None:
            return Command(
                resume={
                    "approval_id": resumable.approval_id,
                    "decision": resumable.status,
                    "comment": resumable.comment,
                }
            )
        return self._build_initial_state(payload, thread_id)

    @staticmethod
    def _build_initial_state(
        payload: ChatCompletionRequest,
        thread_id: str,
    ) -> AgentState:
        """Convert API request data into LangChain messages and graph state."""
        namespace_id = payload.knowledge_namespace or thread_id
        return AgentState(
            messages=[AgentRuntime._to_langchain_message(item) for item in payload.messages],
            next_step="finish",
            step_count=0,
            max_steps=10,
            thought="",
            answer="",
            thread_id=thread_id,
            knowledge_namespace=namespace_id,
            retrieval_queries=[],
            retrieval_hits=[],
            retrieval_context="",
            pending_approval_id="",
            approval_status="",
            approval_summary="",
            pending_tool_name="",
            pending_tool_args={},
        )

    @staticmethod
    def _to_langchain_message(message: ChatMessage) -> BaseMessage:
        """Convert API request messages into LangChain message objects."""
        if message.role == "system":
            return SystemMessage(content=message.content)
        if message.role == "assistant":
            return AIMessage(content=message.content)
        return HumanMessage(content=message.content)

    @staticmethod
    def _config_for_thread(thread_id: str) -> RunnableConfig:
        """Return the LangGraph config carrying the persistent thread identifier."""
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _handle_tool_error(error: Exception) -> str:
        """Turn an unhandled tool crash into a safe tool result payload."""
        return json.dumps(
            {
                "ok": False,
                "tool_name": "tool_node",
                "summary": (
                    "ToolNode caught an unexpected tool failure: "
                    f"{error.__class__.__name__}"
                ),
                "data": {},
                "error": str(error),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _latest_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
        """Return the latest AI message from the current message history."""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return message
        return None

    @staticmethod
    def _latest_user_message(messages: list[BaseMessage]) -> str:
        """Return the latest human message content."""
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return str(message.content)
        return ""

    @staticmethod
    def _normalize_approval_decision(decision_payload: Any) -> Literal["approved", "rejected"]:
        """Normalize a resume payload into an approval decision."""
        if isinstance(decision_payload, dict):
            raw = (
                decision_payload.get("decision")
                or decision_payload.get("status")
                or decision_payload.get("approved")
            )
        else:
            raw = decision_payload

        if isinstance(raw, bool):
            return "approved" if raw else "rejected"

        normalized = str(raw).strip().lower()
        if normalized in {"approve", "approved", "allow", "allowed", "true", "yes"}:
            return "approved"
        if normalized in {"reject", "rejected", "deny", "denied", "false", "no"}:
            return "rejected"
        raise ValueError(f"Unsupported approval decision: {decision_payload!r}")

    @staticmethod
    def _approval_batch_name(calls: list[dict[str, Any]]) -> str:
        """Build a stable approval target name for one or more guarded calls."""
        if not calls:
            return "tool"
        if len(calls) == 1:
            return str(calls[0].get("name", "tool")).strip() or "tool"
        names = [str(call.get("name", "tool")).strip() or "tool" for call in calls]
        return ", ".join(names)

    @staticmethod
    def _summarize_tool_batch(calls: list[dict[str, Any]]) -> str:
        """Build a compact summary for one or more guarded tool calls."""
        if not calls:
            return "high-risk tool execution requested"
        if len(calls) == 1:
            tool_name = str(calls[0].get("name", "tool")).strip() or "tool"
            tool_args = dict(calls[0].get("args") or {})
            return AgentRuntime._summarize_tool_call(tool_name, tool_args)
        parts = [
            AgentRuntime._summarize_tool_call(
                str(call.get("name", "tool")).strip() or "tool",
                dict(call.get("args") or {}),
            )
            for call in calls
        ]
        return "; ".join(parts)

    @staticmethod
    def _summarize_tool_call(tool_name: str, tool_args: dict[str, Any]) -> str:
        """Build a compact human-readable summary of a pending high-risk action."""
        if "path" in tool_args:
            path = Path(str(tool_args["path"])).name or str(tool_args["path"])
            return f"{tool_name} requested for file '{path}'"
        compact_args = json.dumps(tool_args, ensure_ascii=False)[:200]
        return f"{tool_name} requested with args {compact_args}"

    def _timed_sync_node(
        self,
        node_name: str,
        func: Callable[[AgentState], Any],
    ) -> Callable[[AgentState], Any]:
        """Wrap one sync node and print a compact execution timing line."""

        def wrapped(state: AgentState) -> Any:
            started_at = perf_counter()
            status = "ok"
            try:
                return func(state)
            except Exception:
                status = "error"
                raise
            finally:
                elapsed_ms = (perf_counter() - started_at) * 1000
                self._log_timing(node_name, state.get("thread_id", ""), elapsed_ms, status)

        return wrapped

    async def _timed_tool_call(self, request: Any, execute: Callable[[Any], Awaitable[Any]]) -> Any:
        """Time one tool execution without changing ToolNode semantics."""
        thread_id = ""
        state = getattr(request, "state", None)
        if isinstance(state, dict):
            thread_id = str(state.get("thread_id", "")).strip()
        tool_call = getattr(request, "tool_call", {}) or {}
        tool_name = str(tool_call.get("name", "tool")).strip() or "tool"
        started_at = perf_counter()
        status = "ok"
        try:
            return await execute(request)
        except Exception:
            status = "error"
            raise
        finally:
            elapsed_ms = (perf_counter() - started_at) * 1000
            self._log_timing(f"tool:{tool_name}", thread_id, elapsed_ms, status)

    @staticmethod
    def _log_timing(node_name: str, thread_id: str, elapsed_ms: float, status: str) -> None:
        """Emit a compact console timing record for bottleneck analysis."""
        print(
            f"[agent-timing] thread_id={thread_id or '-'} node={node_name} "
            f"status={status} duration_ms={elapsed_ms:.2f}"
        )

    def _ensure_open(self) -> None:
        """Guard against use before async initialization."""
        if not self._is_open:
            raise RuntimeError("AgentRuntime must be opened before use")


@asynccontextmanager
async def managed_agent_runtime(
    checkpointer: PostgresSaver,
    knowledge_base: KnowledgeBase,
    approval_store: ApprovalStore,
    mcp_client: MCPClientBridge,
) -> AsyncIterator[AgentRuntime]:
    """Create and close the agent runtime with async context management."""
    runtime = AgentRuntime(
        checkpointer=checkpointer,
        knowledge_base=knowledge_base,
        approval_store=approval_store,
        mcp_client=mcp_client,
    )
    await runtime.open()
    try:
        yield runtime
    finally:
        await runtime.close()

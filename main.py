from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from app.env_loader import load_env_file

# Load .env as early as possible so downstream modules see env vars on import/use.
load_env_file()

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import AgentRuntime, managed_agent_runtime
from app.approvals import ApprovalRecord, ApprovalStore, managed_approval_store
from app.mcp_client import MCPClientBridge, managed_mcp_client
from app.models import (
    ApprovalDecisionPathRequest,
    ApprovalDecisionRequest,
    ApprovalStatusResponse,
    ChatCompletionRequest,
    ChatStreamEvent,
    KnowledgeStatusResponse,
    KnowledgeUploadResponse,
    PendingApprovalResponse,
)
from app.persistence import managed_postgres_checkpointer
from app.rag import IngestResult, KnowledgeBase, KnowledgeBaseStatus, managed_knowledge_base
from app.streaming import collect_chat_events, format_sse_data, stream_chat_events


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Manage application lifecycle resources asynchronously."""
    async with managed_postgres_checkpointer() as checkpoint_store:
        async with managed_knowledge_base() as knowledge_base:
            async with managed_approval_store() as approval_store:
                async with managed_mcp_client() as mcp_client:
                    async with managed_agent_runtime(
                        checkpoint_store.checkpointer,
                        knowledge_base,
                        approval_store,
                        mcp_client,
                    ) as runtime:
                        resources: dict[str, Any] = {
                            "service": "agent-backend-ready",
                            "agent_runtime": runtime,
                            "checkpoint_store": checkpoint_store,
                            "knowledge_base": knowledge_base,
                            "approval_store": approval_store,
                            "mcp_client": mcp_client,
                        }
                        app.state.agent_runtime = runtime
                        app.state.checkpoint_store = checkpoint_store
                        app.state.knowledge_base = knowledge_base
                        app.state.approval_store = approval_store
                        app.state.mcp_client = mcp_client
                        try:
                            yield resources
                        finally:
                            resources.clear()


app = FastAPI(
    title="AI Agent Backend",
    version="4.0.0",
    lifespan=lifespan,
)

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
WEB_INDEX = WEB_ROOT / "index.html"

# Mount static assets for the SPA without requiring the directory to exist yet.
app.mount(
    "/web",
    StaticFiles(directory=str(WEB_ROOT), check_dir=False),
    name="web",
)


@app.get("/", include_in_schema=False)
async def index() -> Response:
    """Serve SPA entrypoint for the unified frontend workspace."""
    if WEB_INDEX.exists():
        return FileResponse(WEB_INDEX)
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Frontend entrypoint is not available yet. Expected web/index.html.",
        },
    )


async def _ingest_from_request(
    request: Request,
    file: UploadFile | None,
    namespace_id: str | None,
    thread_id: str | None,
) -> KnowledgeUploadResponse:
    """Accept multipart or JSON uploads and write them into the knowledge base."""
    knowledge_base: KnowledgeBase = request.app.state.knowledge_base

    resolved_namespace = (namespace_id or thread_id or "").strip()
    filename = ""
    payload = b""

    if file is not None:
        filename = file.filename or ""
        payload = await file.read()
        await file.close()
    else:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid upload payload") from exc
        filename = str(body.get("filename", "")).strip()
        resolved_namespace = (
            resolved_namespace
            or str(body.get("namespace_id") or body.get("thread_id") or "").strip()
        )
        payload = str(body.get("content", "")).encode("utf-8")

    if not resolved_namespace:
        raise HTTPException(status_code=400, detail="namespace_id or thread_id is required")
    if not filename:
        raise HTTPException(status_code=400, detail="uploaded file must have a filename")
    if not payload:
        raise HTTPException(status_code=400, detail="uploaded content must not be empty")

    try:
        result: IngestResult = await knowledge_base.ingest_document(
            namespace_id=resolved_namespace,
            filename=filename,
            content=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to ingest knowledge document: {exc}",
        ) from exc

    return KnowledgeUploadResponse(
        document_id=result.document_id,
        namespace_id=result.namespace_id,
        filename=result.filename,
        file_type=result.file_type,  # type: ignore[arg-type]
        chunk_count=result.chunk_count,
        backend_mode=result.backend_mode,  # type: ignore[arg-type]
        vector_extension_available=result.vector_extension_available,
        notice=result.notice,
        created_at=result.created_at,
    )


def _pick_upload_file(*candidates: UploadFile | None) -> UploadFile | None:
    """Return the first provided upload field for compatibility across clients."""
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _approval_response(record: ApprovalRecord) -> ApprovalStatusResponse:
    """Convert an internal approval record into a response model."""
    return ApprovalStatusResponse(
        approval_id=record.approval_id,
        thread_id=record.thread_id,
        status=record.status,  # type: ignore[arg-type]
        tool_name=record.tool_name,
        risk_level=record.risk_level,
        summary=record.summary,
        created_at=record.created_at,
        updated_at=record.updated_at,
        comment=record.comment,
        resumed_at=record.resumed_at,
    )


@app.post("/v1/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge_document_legacy(
    request: Request,
    file: UploadFile | None = File(default=None),
    upload: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    namespace_id: str | None = Form(default=None),
    thread_id: str | None = Form(default=None),
) -> KnowledgeUploadResponse:
    """Upload one private PDF/Markdown file and ingest it into the RAG knowledge base."""
    return await _ingest_from_request(
        request,
        _pick_upload_file(file, upload, document),
        namespace_id,
        thread_id,
    )


@app.post("/v1/knowledge/documents", response_model=KnowledgeUploadResponse)
async def upload_knowledge_document(
    request: Request,
    file: UploadFile | None = File(default=None),
    upload: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    namespace_id: str | None = Form(default=None),
    thread_id: str | None = Form(default=None),
) -> KnowledgeUploadResponse:
    """Preferred upload endpoint for private PDF/Markdown knowledge documents."""
    return await _ingest_from_request(
        request,
        _pick_upload_file(file, upload, document),
        namespace_id,
        thread_id,
    )


@app.get("/v1/knowledge/status", response_model=KnowledgeStatusResponse)
async def knowledge_status(request: Request) -> KnowledgeStatusResponse:
    """Return current RAG backend state and pgvector availability."""
    knowledge_base: KnowledgeBase = request.app.state.knowledge_base
    status: KnowledgeBaseStatus = await knowledge_base.status()
    return KnowledgeStatusResponse(
        backend_mode=status.backend_mode,  # type: ignore[arg-type]
        vector_extension_available=status.vector_extension_available,
        vector_extension_notice=status.vector_extension_notice,
        chunk_count=status.chunk_count,
        updated_at=status.updated_at,
    )


@app.get("/v1/approvals/pending/{thread_id}", response_model=PendingApprovalResponse)
async def get_pending_approval(thread_id: str, request: Request) -> PendingApprovalResponse:
    """Return the latest approval state for one thread."""
    approval_store: ApprovalStore = request.app.state.approval_store
    latest = await approval_store.get_latest_for_thread(thread_id)
    resumable = await request.app.state.agent_runtime.has_resumable_approval(thread_id)
    return PendingApprovalResponse(
        thread_id=thread_id,
        resumable=resumable,
        approval=_approval_response(latest) if latest is not None else None,
    )


@app.post("/v1/approvals/decision", response_model=ApprovalStatusResponse)
async def decide_approval(
    payload: ApprovalDecisionRequest,
    request: Request,
) -> ApprovalStatusResponse:
    """Record a human approval or rejection decision."""
    approval_store: ApprovalStore = request.app.state.approval_store
    status = "approved" if payload.decision == "approve" else "rejected"
    try:
        record = await approval_store.decide(
            thread_id=payload.thread_id,
            approval_id=payload.approval_id,
            decision=status,  # type: ignore[arg-type]
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _approval_response(record)


@app.post("/v1/approvals/resume", response_model=ApprovalStatusResponse)
async def resume_approval(
    payload: ApprovalDecisionRequest,
    request: Request,
) -> ApprovalStatusResponse:
    """Alias endpoint that records a decision before chat resumption."""
    return await decide_approval(payload, request)


@app.post("/v1/approvals/{approval_id}/decision", response_model=ApprovalStatusResponse)
async def decide_approval_by_path(
    approval_id: str,
    payload: ApprovalDecisionPathRequest,
    request: Request,
) -> ApprovalStatusResponse:
    """Path-based approval decision endpoint for compatibility with multiple clients."""
    return await decide_approval(
        ApprovalDecisionRequest(
            thread_id=payload.thread_id,
            approval_id=approval_id,
            decision=payload.decision,
            comment=payload.comment,
        ),
        request,
    )


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
) -> Response:
    """Provide SSE chat completions backed by a LangGraph workflow."""
    runtime: AgentRuntime = request.app.state.agent_runtime
    thread_id: str = runtime.resolve_thread_id(payload)
    can_resume = await runtime.has_resumable_approval(thread_id)
    if not payload.messages and not can_resume:
        raise HTTPException(
            status_code=400,
            detail="messages must not be empty unless the thread is resuming from approval",
        )

    if payload.stream:
        event_iterator: AsyncIterator[str] = stream_chat_events(payload, runtime, thread_id)
        try:
            first_event: str = await anext(event_iterator)
        except StopAsyncIteration as exc:
            raise HTTPException(
                status_code=500,
                detail="Agent did not produce any stream events",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Agent execution failed before streaming started",
            ) from exc

        async def event_stream() -> AsyncIterator[str]:
            yield first_event
            try:
                async for raw_event in event_iterator:
                    if await request.is_disconnected():
                        break
                    yield raw_event
            except Exception:
                yield format_sse_data(
                    ChatStreamEvent(
                        type="error",
                        content="Agent execution failed during streaming",
                    )
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Thread-Id": thread_id,
            },
        )

    collected_events: list[ChatStreamEvent] = await collect_chat_events(
        payload,
        runtime,
        thread_id,
    )

    answer_content: str = next(
        (event.content for event in reversed(collected_events) if event.type == "answer"),
        "",
    )
    if not answer_content:
        latest_approval = await request.app.state.approval_store.get_latest_for_thread(thread_id)
        if latest_approval is not None and latest_approval.status == "pending":
            return JSONResponse(
                status_code=202,
                content={
                    "thread_id": thread_id,
                    "status": "awaiting_approval",
                    "approval": _approval_response(latest_approval).model_dump(),
                    "events": [event.model_dump() for event in collected_events],
                },
            )
        raise HTTPException(
            status_code=500,
            detail="Agent did not produce a final answer",
        )

    return JSONResponse(
        content={
            "model": payload.model,
            "thread_id": thread_id,
            "answer": answer_content,
            "events": [event.model_dump() for event in collected_events],
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)

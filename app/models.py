from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

StreamEventType = Literal["thought", "answer", "error"]
MessageRole = Literal["system", "user", "assistant"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ApprovalDecision = Literal["approve", "reject"]


class ChatMessage(BaseModel):
    """Input message unit for chat completion requests."""

    role: MessageRole = Field(
        ...,
        description="Role of the chat message author.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Message content.",
    )


class ChatCompletionRequest(BaseModel):
    """Request model for /v1/chat/completions."""

    model: str = Field(
        default="agent-v1",
        min_length=1,
        description="Model identifier used for completion.",
    )
    messages: list[ChatMessage] = Field(
        default_factory=list,
        description="Conversation messages in chronological order.",
    )
    stream: bool = Field(
        default=True,
        description="Whether to stream response as SSE.",
    )
    show_thoughts: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "show_thoughts",
            "show_thought",
            "include_thought",
            "include_thoughts",
        ),
        serialization_alias="show_thoughts",
        description="Whether SSE output should include internal thought events.",
    )
    thread_id: str | None = Field(
        default=None,
        min_length=1,
        description="Stable conversation thread identifier for persistent memory.",
    )
    knowledge_namespace: str | None = Field(
        default=None,
        min_length=1,
        description="Optional namespace used to isolate uploaded private knowledge.",
    )


class ChatStreamEvent(BaseModel):
    """Stable SSE payload shape emitted to API consumers."""

    type: StreamEventType = Field(
        ...,
        description='Event type: "thought", "answer", or "error".',
    )
    content: str = Field(
        ...,
        description="Event body text.",
    )


class KnowledgeDocumentResponse(BaseModel):
    """Response returned after uploading one knowledge document."""

    document_id: str = Field(..., description="Stored document identifier.")
    namespace_id: str = Field(..., description="Knowledge namespace used for retrieval.")
    filename: str = Field(..., description="Original uploaded filename.")
    file_type: str = Field(..., description="Normalized file type, e.g. pdf or markdown.")
    chunk_count: int = Field(..., ge=1, description="Number of stored text chunks.")
    backend_mode: str = Field(..., description="Active retrieval backend mode.")
    vector_extension_available: bool = Field(
        ...,
        description="Whether the PostgreSQL vector extension is available.",
    )
    notice: str | None = Field(
        default=None,
        description="Capability warning, typically present when running in compatibility mode.",
    )


class KnowledgeUploadResponse(BaseModel):
    """Response model for uploaded private knowledge documents."""

    document_id: str = Field(..., description="Generated knowledge document identifier.")
    namespace_id: str = Field(..., description="Knowledge namespace used for retrieval.")
    filename: str = Field(..., description="Original uploaded filename.")
    file_type: Literal["pdf", "markdown"] = Field(
        ...,
        description="Detected normalized file type.",
    )
    chunk_count: int = Field(..., ge=1, description="Number of produced text chunks.")
    backend_mode: Literal["pgvector", "python_fallback"] = Field(
        ...,
        description="Retriever backend currently serving the knowledge base.",
    )
    vector_extension_available: bool = Field(
        ...,
        description="Whether PostgreSQL pgvector extension is available.",
    )
    notice: str | None = Field(
        default=None,
        description="Optional warning about backend fallbacks.",
    )
    created_at: str = Field(..., description="ISO timestamp of ingestion completion.")


class KnowledgeStatusResponse(BaseModel):
    """Current runtime status of the RAG knowledge base."""

    backend_mode: Literal["pgvector", "python_fallback"] = Field(
        ...,
        description="Retriever backend currently serving the knowledge base.",
    )
    vector_extension_available: bool = Field(
        ...,
        description="Whether PostgreSQL pgvector extension is available.",
    )
    vector_extension_notice: str | None = Field(
        default=None,
        description="Latest pgvector availability notice, if any.",
    )
    chunk_count: int = Field(..., ge=0, description="Total chunk count in the KB.")
    updated_at: str = Field(..., description="ISO timestamp of status generation.")


class ApprovalDecisionRequest(BaseModel):
    """Decision payload submitted by a human approver."""

    thread_id: str = Field(..., min_length=1, description="Conversation thread identifier.")
    approval_id: str = Field(..., min_length=1, description="Approval request identifier.")
    decision: ApprovalDecision = Field(..., description="Approval decision.")
    comment: str | None = Field(
        default=None,
        description="Optional human decision comment.",
    )


class ApprovalDecisionPathRequest(BaseModel):
    """Decision payload variant for path-based approval endpoints."""

    thread_id: str = Field(..., min_length=1, description="Conversation thread identifier.")
    decision: ApprovalDecision = Field(..., description="Approval decision.")
    comment: str | None = Field(
        default=None,
        description="Optional human decision comment.",
    )


class ApprovalStatusResponse(BaseModel):
    """Current approval status for one high-risk tool request."""

    approval_id: str = Field(..., description="Approval request identifier.")
    thread_id: str = Field(..., description="Conversation thread identifier.")
    status: ApprovalStatus = Field(..., description="Current approval status.")
    tool_name: str = Field(..., description="Tool awaiting or using approval.")
    risk_level: str = Field(..., description="Locally assigned risk level.")
    summary: str = Field(..., description="Human-readable summary of the guarded action.")
    created_at: str = Field(..., description="ISO timestamp when the approval was created.")
    updated_at: str = Field(..., description="ISO timestamp when the approval was last updated.")
    comment: str | None = Field(
        default=None,
        description="Optional human decision comment.",
    )
    resumed_at: str | None = Field(
        default=None,
        description="ISO timestamp when execution resumed after approval.",
    )


class PendingApprovalResponse(BaseModel):
    """Latest approval state for a thread."""

    thread_id: str = Field(..., description="Conversation thread identifier.")
    resumable: bool = Field(
        ...,
        description="Whether the thread can resume execution right now.",
    )
    approval: ApprovalStatusResponse | None = Field(
        default=None,
        description="Latest approval record for the thread, if any.",
    )

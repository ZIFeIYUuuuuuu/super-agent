export type StreamEventType = "thought" | "answer" | "error";
export type ApprovalDecision = "approve" | "reject";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type BackendMode = "pgvector" | "python_fallback";
export type MessageRole = "system" | "user" | "assistant";

export type ChatMessage = {
  role: MessageRole;
  content: string;
};

export type ChatStreamEvent = {
  type: StreamEventType;
  content: string;
};

export type HistoryMessageKind = "user" | "thought" | "answer" | "error";

export type ThreadHistoryMessage = {
  kind: HistoryMessageKind;
  content: string;
  created_at: string;
};

export type ThreadHistoryResponse = {
  thread_id: string;
  messages: ThreadHistoryMessage[];
  cached: boolean;
};

export type KnowledgeStatus = {
  backend_mode: BackendMode;
  vector_extension_available: boolean;
  vector_extension_notice: string | null;
  chunk_count: number;
  updated_at: string;
};

export type ApprovalRecord = {
  approval_id: string;
  thread_id: string;
  status: ApprovalStatus;
  tool_name: string;
  risk_level: string;
  summary: string;
  created_at: string;
  updated_at: string;
  comment: string | null;
  resumed_at: string | null;
};

export type PendingApproval = {
  thread_id: string;
  resumable: boolean;
  approval: ApprovalRecord | null;
};

export type KnowledgeUploadResponse = {
  document_id: string;
  namespace_id: string;
  filename: string;
  file_type: "pdf" | "markdown";
  chunk_count: number;
  backend_mode: BackendMode;
  vector_extension_available: boolean;
  notice: string | null;
  created_at: string;
};

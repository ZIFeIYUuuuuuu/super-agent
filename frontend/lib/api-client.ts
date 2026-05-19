type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | null;
  fallbackMessage: string;
};

export type StreamResponse = Response & {
  body: ReadableStream<Uint8Array>;
};

const STATIC_DEMO = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";

async function readErrorDetail(response: Response, fallbackMessage: string) {
  try {
    const data = (await response.json()) as { detail?: string };
    return data.detail || JSON.stringify(data);
  } catch {
    return response.statusText || fallbackMessage;
  }
}

function mergeHeaders(headers?: HeadersInit, defaults?: HeadersInit) {
  const merged = new Headers(defaults);
  if (!headers) return merged;
  new Headers(headers).forEach((value, key) => merged.set(key, value));
  return merged;
}

export async function request(input: string, options: ApiRequestOptions) {
  const { fallbackMessage, headers, cache = "no-store", ...init } = options;
  if (STATIC_DEMO && input.startsWith("/api/")) {
    return mockApiResponse(input, init);
  }

  const response = await fetch(input, {
    ...init,
    cache,
    headers,
  });

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, fallbackMessage));
  }

  return response;
}

function jsonResponse(data: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
}

async function mockApiResponse(input: string, init: Omit<RequestInit, "cache" | "headers">) {
  const now = new Date().toISOString();

  if (input === "/api/knowledge/status") {
    return jsonResponse({
      backend_mode: "python_fallback",
      vector_extension_available: false,
      vector_extension_notice: "Static demo mode: PostgreSQL/PGVector is not connected on GitHub Pages.",
      chunk_count: 12,
      updated_at: now,
    });
  }

  if (input === "/api/knowledge/documents") {
    const body = init.body instanceof FormData ? init.body : null;
    const file = body?.get("file") as File | null;
    const namespaceId = String(body?.get("namespace_id") || "personal-memory");
    return jsonResponse({
      document_id: `doc-${Date.now().toString(36)}`,
      namespace_id: namespaceId,
      filename: file?.name || "portfolio-demo.md",
      file_type: file?.name?.toLowerCase().endsWith(".pdf") ? "pdf" : "markdown",
      chunk_count: 5,
      backend_mode: "python_fallback",
      vector_extension_available: false,
      notice: "Static demo upload simulated in the browser.",
      created_at: now,
    });
  }

  const historyMatch = input.match(/^\/api\/threads\/([^/]+)\/history$/);
  if (historyMatch) {
    const threadId = decodeURIComponent(historyMatch[1]);
    return jsonResponse({
      thread_id: threadId,
      cached: false,
      messages: [
        {
          kind: "user",
          content: "帮我分析这份项目文档，找出可以放进简历的智能体亮点。",
          created_at: now,
        },
        {
          kind: "thought",
          content: "先检查知识库命名空间，再把回答拆成架构、工程能力和风险控制三类。",
          created_at: now,
        },
        {
          kind: "answer",
          content:
            "这个项目最适合强调 LangGraph 编排、RAG 文档检索、SSE 流式输出、人类审批恢复、Redis 热缓存和 PGVector 持久化。面试时建议把重点放在边界设计和失败恢复，而不是只说调用了模型。",
          created_at: now,
        },
      ],
    });
  }

  const approvalMatch = input.match(/^\/api\/approvals\/pending\/([^/]+)$/);
  if (approvalMatch) {
    const threadId = decodeURIComponent(approvalMatch[1]);
    return jsonResponse({
      thread_id: threadId,
      resumable: true,
      approval: {
        approval_id: "approval-demo",
        thread_id: threadId,
        status: "pending",
        tool_name: "send_email",
        risk_level: "high",
        summary: "静态演示：高风险工具调用会先暂停，等待人工批准。",
        created_at: now,
        updated_at: now,
        comment: null,
        resumed_at: null,
      },
    });
  }

  if (input === "/api/approvals/decision") {
    const rawBody = typeof init.body === "string" ? JSON.parse(init.body) : {};
    return jsonResponse({
      approval_id: rawBody.approval_id || "approval-demo",
      thread_id: rawBody.thread_id || "thread-demo",
      status: rawBody.decision === "reject" ? "rejected" : "approved",
      tool_name: "send_email",
      risk_level: "high",
      summary: "静态演示：审批决定已记录。",
      created_at: now,
      updated_at: now,
      comment: rawBody.comment || null,
      resumed_at: rawBody.decision === "approve" ? now : null,
    });
  }

  if (input === "/api/chat/completions") {
    const rawBody = typeof init.body === "string" ? JSON.parse(init.body) : {};
    const threadId = rawBody.thread_id || `thread-${Date.now().toString(36)}`;
    const prompt = rawBody.messages?.at?.(-1)?.content || "继续执行";
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const events = [
          {
            type: "thought",
            content: `静态 demo 收到请求：“${prompt}”。真实部署时这里由 FastAPI + LangGraph 生成。`,
          },
          {
            type: "thought",
            content: "模拟检索知识库、检查审批状态，并准备带来源的回答。",
          },
          {
            type: "answer",
            content:
              "这是 GitHub Pages 上的 Super Agent 静态演示。它展示完整工作台交互：流式聊天、知识库上传、线程历史和人工审批。真实运行版本需要部署 FastAPI 后端，并配置 PostgreSQL/PGVector、Redis 和模型 API Key。",
          },
        ];
        for (const event of events) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        }
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      },
    });
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "X-Thread-Id": threadId,
        "Cache-Control": "no-cache",
      },
    });
  }

  return jsonResponse({ detail: "Static demo route not implemented." }, { status: 404 });
}

export async function getJson<T>(input: string, fallbackMessage: string, init?: Omit<RequestInit, "method">) {
  const response = await request(input, {
    ...init,
    method: "GET",
    fallbackMessage,
  });
  return (await response.json()) as T;
}

export async function postJson<TResponse>(
  input: string,
  body: unknown,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body">,
) {
  const response = await request(input, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
    headers: mergeHeaders(init?.headers, { "Content-Type": "application/json" }),
    fallbackMessage,
  });
  return (await response.json()) as TResponse;
}

export async function postFormData<TResponse>(
  input: string,
  body: FormData,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body" | "headers">,
) {
  const response = await request(input, {
    ...init,
    method: "POST",
    body,
    fallbackMessage,
  });
  return (await response.json()) as TResponse;
}

export async function postStream(
  input: string,
  body: unknown,
  fallbackMessage: string,
  init?: Omit<RequestInit, "method" | "body">,
): Promise<StreamResponse> {
  const response = await request(input, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
    headers: mergeHeaders(init?.headers, { "Content-Type": "application/json" }),
    fallbackMessage,
  });

  if (!response.body) {
    throw new Error(fallbackMessage);
  }

  return response as StreamResponse;
}

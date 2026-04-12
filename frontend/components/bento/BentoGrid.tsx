"use client";

import { useDeferredValue, useEffect, useRef, useState, useTransition } from "react";
import { motion } from "motion/react";
import {
  Activity,
  Bot,
  CheckCircle2,
  FileUp,
  Globe2,
  History,
  LoaderCircle,
  RefreshCcw,
  ShieldAlert,
  Sparkles,
  SquarePen,
  Waves,
  XCircle,
} from "lucide-react";

import type {
  ApprovalDecision,
  ChatMessage,
  ChatStreamEvent,
  KnowledgeStatus,
  KnowledgeUploadResponse,
  PendingApproval,
  ThreadHistoryResponse,
} from "@/lib/workspace-types";

import { translations, type Locale } from "./content";
import styles from "./BentoGrid.module.css";

type ChatItemKind = "user" | "thought" | "answer" | "error";
type ChatItem = {
  id: string;
  kind: ChatItemKind;
  content: string;
  time: string;
};

type ActivityItem = {
  id: string;
  message: string;
  time: string;
};

const LANGUAGE_STORAGE_KEY = "super-agent-language-v5";
const SHOW_THOUGHT_STORAGE_KEY = "super-agent-show-thought-v2";

const cardVariants = {
  hidden: { opacity: 0, y: 28, filter: "blur(10px)" },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: {
      duration: 0.7,
      ease: "easeOut" as const,
    },
  },
};

function createThreadId() {
  if (typeof window !== "undefined" && typeof window.crypto?.randomUUID === "function") {
    return `thread-${window.crypto.randomUUID().slice(0, 8)}`;
  }
  return `thread-${Date.now().toString(36)}`;
}

function readLocale(): Locale {
  if (typeof window === "undefined") return "zh";
  try {
    return localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

function readShowThoughts() {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(SHOW_THOUGHT_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function formatClock(locale: Locale) {
  return new Date().toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatHistoryClock(locale: Locale, value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return formatClock(locale);
  }
  return parsed.toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function decodeBase64Utf8(value: string) {
  const binary = window.atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder("utf-8").decode(bytes);
}

function decodeSsePayload(payload: Record<string, unknown>): ChatStreamEvent {
  if (typeof payload.content_b64 === "string") {
    return {
      type: String(payload.type || "thought") as ChatStreamEvent["type"],
      content: decodeBase64Utf8(payload.content_b64),
    };
  }

  return {
    type: String(payload.type || "thought") as ChatStreamEvent["type"],
    content: String(payload.content || ""),
  };
}

async function extractError(response: Response, fallback: string) {
  try {
    const data = (await response.json()) as { detail?: string };
    return data.detail || JSON.stringify(data);
  } catch {
    return response.statusText || fallback;
  }
}

function createChatItem(kind: ChatItemKind, content: string, time: string): ChatItem {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    kind,
    content,
    time,
  };
}

export default function BentoGrid() {
  const [locale, setLocale] = useState<Locale>(readLocale);
  const [showThoughts, setShowThoughts] = useState(readShowThoughts);
  const [threadId, setThreadId] = useState(() => createThreadId());
  const [namespaceId, setNamespaceId] = useState("");
  const [approvalThreadId, setApprovalThreadId] = useState("");
  const [approvalComment, setApprovalComment] = useState("");
  const [prompt, setPrompt] = useState("");
  const [chatStatus, setChatStatus] = useState("");
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [historyItems, setHistoryItems] = useState<ChatItem[]>([]);
  const [historyCacheEnabled, setHistoryCacheEnabled] = useState<boolean | null>(null);
  const [historySyncedAt, setHistorySyncedAt] = useState("");
  const [latestOutput, setLatestOutput] = useState("");
  const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
  const [knowledgeStatus, setKnowledgeStatus] = useState<KnowledgeStatus | null>(null);
  const [uploadResult, setUploadResult] = useState("");
  const [approvalResult, setApprovalResult] = useState("");
  const [approvalState, setApprovalState] = useState<PendingApproval | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputResetKey, setFileInputResetKey] = useState(0);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isUploading, startUploadTransition] = useTransition();
  const [isRefreshingStatus, startStatusTransition] = useTransition();
  const [isRefreshingApproval, startApprovalTransition] = useTransition();
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false);
  const chatStreamRef = useRef<HTMLDivElement | null>(null);
  const previousThreadIdRef = useRef(threadId);
  const deferredThreadId = useDeferredValue(threadId.trim());

  const t = translations[locale];
  const resolvedNamespace = namespaceId.trim() || threadId.trim();
  const resolvedApprovalThread = approvalThreadId.trim() || threadId.trim();
  const visibleChatItems = chatItems.filter((item) => showThoughts || item.kind !== "thought");
  const visibleHistoryItems = historyItems.filter((item) => showThoughts || item.kind !== "thought");
  const serviceStatusText = isRefreshingStatus
    ? t.loading
    : knowledgeStatus
      ? t.online
      : t.unavailable;
  const historyStatusText =
    historyCacheEnabled == null
      ? t.loading
      : historyCacheEnabled
        ? t.historyCacheOn
        : t.historyCacheOff;

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = locale === "zh" ? "Super Agent 工作台" : "Super Agent Workspace";
    localStorage.setItem(LANGUAGE_STORAGE_KEY, locale);
  }, [locale]);

  useEffect(() => {
    localStorage.setItem(SHOW_THOUGHT_STORAGE_KEY, showThoughts ? "true" : "false");
  }, [showThoughts]);

  useEffect(() => {
    setNamespaceId((current) =>
      !current || current === previousThreadIdRef.current ? threadId : current,
    );
    setApprovalThreadId((current) =>
      !current || current === previousThreadIdRef.current ? threadId : current,
    );
    previousThreadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    setChatStatus(t.ready);
    setLatestOutput(t.outputEmpty);
    setUploadResult(t.uploadIdle);
  }, [t.ready, t.outputEmpty, t.uploadIdle]);

  useEffect(() => {
    void refreshKnowledgeStatus();
    void refreshApprovalState(threadId);
    appendActivity(t.ready);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chatStreamRef.current) {
      chatStreamRef.current.scrollTop = chatStreamRef.current.scrollHeight;
    }
  }, [visibleChatItems]);

  function appendActivity(message: string) {
    setActivityItems((current) => [
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        message,
        time: formatClock(locale),
      },
      ...current,
    ].slice(0, 12));
  }

  function pushChatItem(kind: ChatItemKind, content: string) {
    const nextItem = createChatItem(kind, content, formatClock(locale));
    setChatItems((current) => [...current, nextItem]);
    setHistoryItems((current) => [...current, nextItem]);
  }

  async function refreshKnowledgeStatus() {
    return new Promise<void>((resolve) => {
      startStatusTransition(async () => {
        try {
          const response = await fetch("/api/knowledge/status", { cache: "no-store" });
          if (!response.ok) {
            throw new Error(await extractError(response, t.errors.requestFailed));
          }
          const data = (await response.json()) as KnowledgeStatus;
          setKnowledgeStatus(data);
          appendActivity(t.knowledgeLoaded);
        } catch (error) {
          setKnowledgeStatus(null);
          appendActivity(error instanceof Error ? error.message : t.errors.requestFailed);
        } finally {
          resolve();
        }
      });
    });
  }

  async function refreshApprovalState(targetThreadId?: string) {
    const currentThread = (targetThreadId || resolvedApprovalThread).trim();
    if (!currentThread) return;

    return new Promise<void>((resolve) => {
      startApprovalTransition(async () => {
        try {
          const response = await fetch(
            `/api/approvals/pending/${encodeURIComponent(currentThread)}`,
            { cache: "no-store" },
          );
          if (!response.ok) {
            throw new Error(await extractError(response, t.errors.requestFailed));
          }
          const data = (await response.json()) as PendingApproval;
          setApprovalState(data);
          setApprovalResult(JSON.stringify(data, null, 2));
          appendActivity(t.approvalLoaded);
        } catch (error) {
          setApprovalState(null);
          setApprovalResult(error instanceof Error ? error.message : t.errors.requestFailed);
        } finally {
          resolve();
        }
      });
    });
  }

  async function loadThreadHistory(targetThreadId: string) {
    const resolvedThreadId = targetThreadId.trim();
    if (!resolvedThreadId) return;

    setIsRefreshingHistory(true);
    try {
      const response = await fetch(`/api/threads/${encodeURIComponent(resolvedThreadId)}/history`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await extractError(response, t.errors.requestFailed));
      }

      const data = (await response.json()) as ThreadHistoryResponse;
      const mappedItems: ChatItem[] = data.messages.map((message, index) => ({
        id: `${resolvedThreadId}-${index}-${message.created_at}`,
        kind: message.kind,
        content: message.content,
        time: formatHistoryClock(locale, message.created_at),
      }));

      setChatItems(mappedItems);
      setHistoryItems(mappedItems);
      setHistoryCacheEnabled(data.cached);
      setHistorySyncedAt(new Date().toISOString());
      const latestVisibleOutput = [...mappedItems]
        .reverse()
        .find((item) => item.kind === "answer" || item.kind === "error");
      setLatestOutput(latestVisibleOutput?.content || t.outputEmpty);

      appendActivity(mappedItems.length ? `${t.historyLoaded} (${mappedItems.length})` : t.historyEmpty);
    } catch (error) {
      setHistoryCacheEnabled(false);
      appendActivity(error instanceof Error ? `${t.historyLoadFailed} ${error.message}` : t.historyLoadFailed);
    } finally {
      setIsRefreshingHistory(false);
    }
  }

  useEffect(() => {
    if (!deferredThreadId) return;
    void loadThreadHistory(deferredThreadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deferredThreadId, locale]);

  async function streamChat(messages: ChatMessage[], targetThreadId: string) {
    const response = await fetch("/api/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "agent-v1",
        stream: true,
        show_thoughts: showThoughts,
        thread_id: targetThreadId,
        knowledge_namespace: resolvedNamespace,
        messages,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error(await extractError(response, t.errors.requestFailed));
    }

    const resolvedThread = response.headers.get("x-thread-id");
    if (resolvedThread) {
      setThreadId(resolvedThread);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        const payloadLines = block
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim());

        if (!payloadLines.length) continue;

        const rawPayload = payloadLines.join("\n");
        if (rawPayload === "[DONE]") continue;

        try {
          const event = decodeSsePayload(JSON.parse(rawPayload) as Record<string, unknown>);
          if (event.type === "thought" && !showThoughts) continue;
          pushChatItem(event.type, event.content);
          if (event.type === "answer" || event.type === "error") {
            setLatestOutput(event.content);
          }
        } catch {
          appendActivity(t.errors.requestFailed);
        }
      }
    }
  }

  async function handleSendMessage() {
    const userPrompt = prompt.trim();
    if (!userPrompt) {
      setChatStatus(t.errors.emptyPrompt);
      return;
    }

    const activeThread = threadId.trim() || createThreadId();
    if (activeThread !== threadId) {
      setThreadId(activeThread);
    }

    pushChatItem("user", userPrompt);
    setPrompt("");
    setChatStatus(t.startChat);
    appendActivity(t.startChat);
    setIsChatLoading(true);

    try {
      await streamChat([{ role: "user", content: userPrompt }], activeThread);
      setChatStatus(t.finishChat);
      appendActivity(t.finishChat);
      await refreshApprovalState(activeThread);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      setChatStatus(message);
      pushChatItem("error", message);
      setLatestOutput(message);
    } finally {
      setIsChatLoading(false);
    }
  }

  function handleCreateFreshThread() {
    const nextThreadId = createThreadId();
    setThreadId(nextThreadId);
    setNamespaceId(nextThreadId);
    setApprovalThreadId(nextThreadId);
    setSelectedFile(null);
    setFileInputResetKey((value) => value + 1);
    setChatItems([]);
    setHistoryItems([]);
    setHistoryCacheEnabled(null);
    setHistorySyncedAt("");
    setChatStatus(t.ready);
    setLatestOutput(t.outputEmpty);
    setApprovalState(null);
    setApprovalResult("");
    setUploadResult(t.uploadIdle);
    appendActivity(`${t.newThread}: ${nextThreadId}`);
  }

  function handleClearChat() {
    setChatItems([]);
    setChatStatus(t.ready);
    setLatestOutput(t.outputEmpty);
  }

  function handleThreadInputChange(value: string) {
    const nextValue = value.trimStart();
    const previousThread = threadId;
    setThreadId(nextValue);
    setNamespaceId((current) =>
      !current || current === previousThread ? nextValue : current,
    );
    setApprovalThreadId((current) =>
      !current || current === previousThread ? nextValue : current,
    );
  }

  function renderBadge(kind: ChatItemKind) {
    if (kind === "thought") return t.thought;
    if (kind === "answer") return t.answer;
    if (kind === "error") return t.error;
    return t.user;
  }

  function renderApprovalStatus() {
    if (!approvalState?.approval) {
      return t.notResumable;
    }

    if (approvalState.approval.status === "pending") return t.pending;
    if (approvalState.approval.status === "approved") {
      return approvalState.resumable ? `${t.approved} / ${t.resumable}` : t.approved;
    }
    if (approvalState.approval.status === "rejected") return t.rejected;
    return approvalState.resumable ? t.resumable : t.notResumable;
  }

  function renderApprovalSummary() {
    const approval = approvalState?.approval;
    if (!approval) return t.approvalEmpty;

    const lines = [
      `${t.labels.approvalId}: ${approval.approval_id}`,
      `${t.labels.tool}: ${approval.tool_name}`,
      `${t.labels.risk}: ${approval.risk_level}`,
      `${t.labels.summary}: ${approval.summary}`,
      `${t.labels.updatedAt}: ${approval.updated_at}`,
      `${t.labels.resumable}: ${approvalState?.resumable ? t.resumable : t.notResumable}`,
    ];

    if (approval.comment) {
      lines.push(`${t.labels.comment}: ${approval.comment}`);
    }

    return lines.join("\n");
  }

  async function handleUploadFile() {
    if (!selectedFile) {
      setUploadResult(t.errors.uploadMissing);
      return;
    }

    return new Promise<void>((resolve) => {
      startUploadTransition(async () => {
        const formData = new FormData();
        formData.append("file", selectedFile);
        formData.append("namespace_id", resolvedNamespace);
        formData.append("thread_id", threadId);

        try {
          const response = await fetch("/api/knowledge/documents", {
            method: "POST",
            body: formData,
          });
          if (!response.ok) {
            throw new Error(await extractError(response, t.errors.requestFailed));
          }
          const data = (await response.json()) as KnowledgeUploadResponse;
          setUploadResult(JSON.stringify(data, null, 2));
          setNamespaceId(data.namespace_id);
          appendActivity(t.uploadDone);
          await refreshKnowledgeStatus();
        } catch (error) {
          setUploadResult(error instanceof Error ? error.message : t.errors.requestFailed);
        } finally {
          resolve();
        }
      });
    });
  }

  async function handleApprovalDecision(decision: ApprovalDecision) {
    const approval = approvalState?.approval;
    if (!approval || approval.status !== "pending") {
      setApprovalResult(t.errors.approvalMissing);
      return;
    }

    try {
      const response = await fetch("/api/approvals/decision", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          thread_id: approval.thread_id,
          approval_id: approval.approval_id,
          decision,
          comment: approvalComment.trim() || null,
        }),
      });
      if (!response.ok) {
        throw new Error(await extractError(response, t.errors.requestFailed));
      }
      const data = await response.json();
      setApprovalResult(JSON.stringify(data, null, 2));
      appendActivity(t.approvalUpdated);
      await refreshApprovalState(approval.thread_id);
    } catch (error) {
      setApprovalResult(error instanceof Error ? error.message : t.errors.requestFailed);
    }
  }

  async function handleResume() {
    if (!approvalState?.resumable) {
      setApprovalResult(t.errors.resumeUnavailable);
      return;
    }

    appendActivity(t.resumeSent);
    setIsChatLoading(true);

    try {
      await streamChat([], resolvedApprovalThread);
      await refreshApprovalState(resolvedApprovalThread);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      pushChatItem("error", message);
      setLatestOutput(message);
    } finally {
      setIsChatLoading(false);
    }
  }

  return (
    <motion.section
      className={styles.wrapper}
      initial="hidden"
      animate="visible"
      transition={{ staggerChildren: 0.08, delayChildren: 0.06 }}
      aria-label="Super Agent workspace"
    >
      <motion.article className={`${styles.card} ${styles.heroCard}`} variants={cardVariants}>
        <div className={styles.heroHeader}>
          <div>
            <span className={styles.eyebrow}>{t.kicker}</span>
            <h2 className={styles.heroTitle}>{t.title}</h2>
            <p className={styles.heroDescription}>{t.description}</p>
          </div>
          <button
            type="button"
            className={styles.localeToggle}
            onClick={() => setLocale((current) => (current === "zh" ? "en" : "zh"))}
          >
            {locale === "zh" ? "EN" : "中"}
          </button>
        </div>

        <div className={styles.heroInputs}>
          <label className={styles.field}>
            <span>{t.threadLabel}</span>
            <input
              value={threadId}
              onChange={(event) => handleThreadInputChange(event.target.value)}
              placeholder={t.threadPlaceholder}
            />
          </label>
          <label className={styles.field}>
            <span>{t.namespaceLabel}</span>
            <input
              value={namespaceId}
              onChange={(event) => setNamespaceId(event.target.value)}
              placeholder={t.namespacePlaceholder}
            />
          </label>
        </div>

        <div className={styles.metricsGrid}>
          <div className={styles.metricBox}>
            <span>{t.service}</span>
            <strong>{serviceStatusText}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.mode}</span>
            <strong>{knowledgeStatus?.backend_mode || "-"}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.chunks}</span>
            <strong>{knowledgeStatus?.chunk_count ?? "-"}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.approval}</span>
            <strong>{renderApprovalStatus()}</strong>
          </div>
        </div>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.chatCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>Chat</span>
            <h3>Streaming workspace</h3>
          </div>
          <div className={styles.headerActions}>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={showThoughts}
                onChange={(event) => setShowThoughts(event.target.checked)}
              />
              <span>{t.showThoughts}</span>
            </label>
            <button type="button" className={styles.secondaryButton} onClick={handleCreateFreshThread}>
              <SquarePen size={16} />
              <span>{t.newThread}</span>
            </button>
            <button type="button" className={styles.secondaryButton} onClick={handleClearChat}>
              <XCircle size={16} />
              <span>{t.clearChat}</span>
            </button>
          </div>
        </div>

        <div className={styles.inlineStatus}>
          {isChatLoading ? <LoaderCircle className={styles.spin} size={16} /> : <Bot size={16} />}
          <span>{chatStatus || t.ready}</span>
        </div>

        <div ref={chatStreamRef} className={styles.chatStream}>
          {visibleChatItems.map((item) => (
            <article key={item.id} className={styles.chatItem} data-kind={item.kind}>
              <div className={styles.chatItemHead}>
                <span className={styles.chatBadge}>{renderBadge(item.kind)}</span>
                <time>{item.time}</time>
              </div>
              <pre className={styles.chatContent}>{item.content}</pre>
            </article>
          ))}
        </div>

        <div className={styles.composer}>
          <label className={styles.field}>
            <span>Prompt</span>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t.inputPlaceholder}
              rows={4}
            />
          </label>
          <div className={styles.composerFooter}>
            <p className={styles.hint}>{showThoughts ? t.thought : t.answer}</p>
            <button type="button" className={styles.primaryButton} onClick={handleSendMessage}>
              <Sparkles size={16} />
              <span>{t.send}</span>
            </button>
          </div>
        </div>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.uploadCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>Knowledge</span>
            <h3>{t.uploadTitle}</h3>
          </div>
        </div>

        <label className={styles.field}>
          <span>{t.namespaceLabel}</span>
          <input
            value={namespaceId}
            onChange={(event) => setNamespaceId(event.target.value)}
            placeholder={t.namespacePlaceholder}
          />
        </label>

        <label className={styles.filePicker}>
          <span>{selectedFile?.name || t.chooseFile}</span>
          <input
            key={fileInputResetKey}
            type="file"
            accept=".pdf,.md,.markdown"
            onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
          />
        </label>

        <button
          type="button"
          className={styles.primaryButton}
          onClick={() => void handleUploadFile()}
          disabled={isUploading}
        >
          <FileUp size={16} />
          <span>{isUploading ? t.loading : t.upload}</span>
        </button>

        <pre className={styles.rawPanel}>{uploadResult || t.uploadIdle}</pre>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.statusCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>Status</span>
            <h3>{t.knowledgeTitle}</h3>
          </div>
          <button type="button" className={styles.secondaryButton} onClick={() => void refreshKnowledgeStatus()}>
            <RefreshCcw size={16} />
            <span>{t.refresh}</span>
          </button>
        </div>

        <div className={styles.statusList}>
          <div className={styles.statusRow}>
            <Globe2 size={16} />
            <span>{t.service}</span>
            <strong>{serviceStatusText}</strong>
          </div>
          <div className={styles.statusRow}>
            <Waves size={16} />
            <span>{t.mode}</span>
            <strong>{knowledgeStatus?.backend_mode || "-"}</strong>
          </div>
          <div className={styles.statusRow}>
            <Activity size={16} />
            <span>{t.chunks}</span>
            <strong>{knowledgeStatus?.chunk_count ?? "-"}</strong>
          </div>
        </div>

        <pre className={styles.rawPanel}>
          {knowledgeStatus ? JSON.stringify(knowledgeStatus, null, 2) : t.loading}
        </pre>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.historyCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>History</span>
            <h3>{t.historyTitle}</h3>
          </div>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void loadThreadHistory(threadId)}
            disabled={isRefreshingHistory}
          >
            {isRefreshingHistory ? <LoaderCircle className={styles.spin} size={16} /> : <RefreshCcw size={16} />}
            <span>{isRefreshingHistory ? t.loading : t.refresh}</span>
          </button>
        </div>

        <p className={styles.hint}>{t.historyHint}</p>

        <div className={styles.historyMetaGrid}>
          <div className={styles.metricBox}>
            <span>{t.historyThreadLabel}</span>
            <strong>{threadId || "-"}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.historyCountLabel}</span>
            <strong>{visibleHistoryItems.length}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.historySyncedLabel}</span>
            <strong>{historySyncedAt ? formatHistoryClock(locale, historySyncedAt) : "-"}</strong>
          </div>
          <div className={styles.metricBox}>
            <span>{t.historyCacheLabel}</span>
            <strong>{historyStatusText}</strong>
          </div>
        </div>

        <div className={styles.historyList}>
          {visibleHistoryItems.length ? (
            [...visibleHistoryItems].reverse().slice(0, 8).map((item) => (
              <article key={`history-${item.id}`} className={styles.historyRow}>
                <div className={styles.historyRowHead}>
                  <span className={styles.chatBadge}>{renderBadge(item.kind)}</span>
                  <time>{item.time}</time>
                </div>
                <p className={styles.historyContent}>{item.content}</p>
              </article>
            ))
          ) : (
            <div className={styles.emptyHistory}>
              <History size={18} />
              <span>{t.historyEmpty}</span>
            </div>
          )}
        </div>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.approvalCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>Approval</span>
            <h3>{t.approvalTitle}</h3>
          </div>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void refreshApprovalState()}
          >
            <RefreshCcw size={16} />
            <span>{t.refresh}</span>
          </button>
        </div>

        <label className={styles.field}>
          <span>{t.approvalThreadLabel}</span>
          <input
            value={approvalThreadId}
            onChange={(event) => setApprovalThreadId(event.target.value)}
            placeholder={t.threadPlaceholder}
          />
        </label>

        <label className={styles.field}>
          <span>{t.commentLabel}</span>
          <input
            value={approvalComment}
            onChange={(event) => setApprovalComment(event.target.value)}
            placeholder={t.commentPlaceholder}
          />
        </label>

        <pre className={styles.approvalSummary}>{renderApprovalSummary()}</pre>

        <div className={styles.buttonGrid}>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={() => void handleApprovalDecision("approve")}
          >
            <CheckCircle2 size={16} />
            <span>{t.approve}</span>
          </button>
          <button
            type="button"
            className={styles.dangerButton}
            onClick={() => void handleApprovalDecision("reject")}
          >
            <ShieldAlert size={16} />
            <span>{t.reject}</span>
          </button>
          <button type="button" className={styles.secondaryButton} onClick={() => void handleResume()}>
            <LoaderCircle size={16} />
            <span>{t.resume}</span>
          </button>
        </div>

        <pre className={styles.rawPanel}>{approvalResult || t.approvalEmpty}</pre>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.outputCard}`} variants={cardVariants}>
        <span className={styles.eyebrow}>Output</span>
        <h3>{t.latestOutputTitle}</h3>
        <pre className={styles.outputPanel}>{latestOutput || t.outputEmpty}</pre>
      </motion.article>

      <motion.article className={`${styles.card} ${styles.activityCard}`} variants={cardVariants}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>Activity</span>
            <h3>{t.activityTitle}</h3>
          </div>
        </div>
        <ul className={styles.activityList}>
          {activityItems.map((item) => (
            <li key={item.id}>
              <time>{item.time}</time>
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      </motion.article>
    </motion.section>
  );
}

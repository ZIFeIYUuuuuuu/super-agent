"use client";

import { useDeferredValue, useEffect, useRef, useState, useTransition } from "react";
import { motion } from "motion/react";
import {
  CheckCircle2,
  FileUp,
  Globe2,
  History,
  LoaderCircle,
  RefreshCcw,
  SendHorizontal,
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
type ChatItem = { id: string; kind: ChatItemKind; content: string; time: string };
type ThreadRecord = { threadId: string; title: string; preview: string; updatedAt: string };

const LANGUAGE_STORAGE_KEY = "super-agent-language-v6";
const SHOW_THOUGHT_STORAGE_KEY = "super-agent-show-thought-v3";
const RECENT_THREADS_STORAGE_KEY = "super-agent-recent-threads-v2";
const KNOWLEDGE_NAMESPACE_STORAGE_KEY = "super-agent-knowledge-namespace-v1";

const panelVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: "easeOut" as const },
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

function readRecentThreads(): ThreadRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_THREADS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Array<Partial<ThreadRecord>>;
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, 10).map((item) => ({
      threadId: String(item.threadId || ""),
      title: String(item.title || item.preview || item.threadId || "").slice(0, 20),
      preview: String(item.preview || ""),
      updatedAt: String(item.updatedAt || new Date().toISOString()),
    }));
  } catch {
    return [];
  }
}

function readKnowledgeNamespace() {
  if (typeof window === "undefined") return "personal-memory";
  try {
    return localStorage.getItem(KNOWLEDGE_NAMESPACE_STORAGE_KEY)?.trim() || "personal-memory";
  } catch {
    return "personal-memory";
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
  if (Number.isNaN(parsed.getTime())) return formatClock(locale);
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
  return { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, kind, content, time };
}

function truncateMessage(value: string, limit = 10) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  return Array.from(normalized).slice(0, limit).join("");
}

function renderBadge(kind: ChatItemKind, t: ReturnType<typeof getTranslations>) {
  if (kind === "thought") return t.thought;
  if (kind === "answer") return t.answer;
  if (kind === "error") return t.error;
  return t.user;
}

function getTranslations(locale: Locale) {
  return translations[locale];
}

export default function BentoGrid() {
  const [locale, setLocale] = useState<Locale>(readLocale);
  const [showThoughts, setShowThoughts] = useState(readShowThoughts);
  const [threadId, setThreadId] = useState(() => createThreadId());
  const [namespaceId, setNamespaceId] = useState(readKnowledgeNamespace);
  const [approvalThreadId, setApprovalThreadId] = useState("");
  const [approvalComment, setApprovalComment] = useState("");
  const [prompt, setPrompt] = useState("");
  const [chatStatus, setChatStatus] = useState("");
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [recentThreads, setRecentThreads] = useState<ThreadRecord[]>(readRecentThreads);
  const [historyCacheEnabled, setHistoryCacheEnabled] = useState<boolean | null>(null);
  const [knowledgeStatus, setKnowledgeStatus] = useState<KnowledgeStatus | null>(null);
  const [uploadResult, setUploadResult] = useState("");
  const [uploadFeedback, setUploadFeedback] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [approvalResult, setApprovalResult] = useState("");
  const [approvalState, setApprovalState] = useState<PendingApproval | null>(null);
  const [isApprovalModalOpen, setIsApprovalModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputResetKey, setFileInputResetKey] = useState(0);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false);
  const [isUploading, startUploadTransition] = useTransition();
  const [isRefreshingStatus, startStatusTransition] = useTransition();
  const [isRefreshingApproval, startApprovalTransition] = useTransition();
  const chatViewportRef = useRef<HTMLDivElement | null>(null);
  const deferredThreadId = useDeferredValue(threadId.trim());

  const t = getTranslations(locale);
  const resolvedThreadId = threadId.trim() || createThreadId();
  const resolvedNamespace = namespaceId.trim() || "personal-memory";
  const resolvedApprovalThread = approvalThreadId.trim() || resolvedThreadId;
  const visibleChatItems = chatItems.filter((item) => showThoughts || item.kind !== "thought");
  const serviceStatusText = isRefreshingStatus ? t.loading : knowledgeStatus ? t.online : t.unavailable;
  const approvalStatusText = approvalState?.approval
    ? approvalState.approval.status === "pending"
      ? t.pending
      : approvalState.approval.status === "approved"
        ? approvalState.resumable
          ? `${t.approved} / ${t.resumable}`
          : t.approved
        : t.rejected
    : t.notResumable;
  const activeThreadRecord = recentThreads.find((item) => item.threadId === resolvedThreadId);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = locale === "zh" ? "Super Agent 工作台" : "Super Agent Workspace";
    localStorage.setItem(LANGUAGE_STORAGE_KEY, locale);
  }, [locale]);

  useEffect(() => {
    localStorage.setItem(SHOW_THOUGHT_STORAGE_KEY, showThoughts ? "true" : "false");
  }, [showThoughts]);

  useEffect(() => {
    document.title = locale === "zh" ? "Super Agent 工作台" : "Super Agent Workspace";
  }, [locale]);

  useEffect(() => {
    localStorage.setItem(RECENT_THREADS_STORAGE_KEY, JSON.stringify(recentThreads.slice(0, 10)));
  }, [recentThreads]);

  useEffect(() => {
    localStorage.setItem(KNOWLEDGE_NAMESPACE_STORAGE_KEY, resolvedNamespace);
  }, [resolvedNamespace]);

  useEffect(() => {
    setApprovalThreadId((current) => (!current ? threadId : current));
  }, [threadId]);

  useEffect(() => {
    setChatStatus(t.ready);
    setUploadResult(t.uploadIdle);
    setUploadFeedback(null);
  }, [t.ready, t.uploadIdle]);

  useEffect(() => {
    if (approvalState?.approval?.status === "pending" || approvalState?.resumable) {
      setIsApprovalModalOpen(true);
    }
  }, [approvalState]);

  useEffect(() => {
    void refreshKnowledgeStatus();
    void refreshApprovalState(threadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chatViewportRef.current) {
      chatViewportRef.current.scrollTop = chatViewportRef.current.scrollHeight;
    }
  }, [visibleChatItems]);

  useEffect(() => {
    if (!deferredThreadId) return;
    void loadThreadHistory(deferredThreadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deferredThreadId, locale]);

  function touchRecentThread(targetThreadId: string, options?: { title?: string; preview?: string }) {
    const cleanThreadId = targetThreadId.trim();
    if (!cleanThreadId) return;
    setRecentThreads((current) => {
      const existing = current.find((item) => item.threadId === cleanThreadId);
      const nextTitle = existing?.title || truncateMessage(options?.title || "", 10) || cleanThreadId;
      const nextPreview = truncateMessage(options?.preview || "", 28) || existing?.preview || nextTitle;
      const nextRecord: ThreadRecord = {
        threadId: cleanThreadId,
        title: nextTitle,
        preview: nextPreview,
        updatedAt: new Date().toISOString(),
      };
      return [nextRecord, ...current.filter((item) => item.threadId !== cleanThreadId)].slice(0, 10);
    });
  }

  async function refreshKnowledgeStatus() {
    return new Promise<void>((resolve) => {
      startStatusTransition(async () => {
        try {
          const response = await fetch("/api/knowledge/status", { cache: "no-store" });
          if (!response.ok) throw new Error(await extractError(response, t.errors.requestFailed));
          const data = (await response.json()) as KnowledgeStatus;
          setKnowledgeStatus(data);
        } catch {
          setKnowledgeStatus(null);
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
          const response = await fetch(`/api/approvals/pending/${encodeURIComponent(currentThread)}`, {
            cache: "no-store",
          });
          if (!response.ok) throw new Error(await extractError(response, t.errors.requestFailed));
          const data = (await response.json()) as PendingApproval;
          setApprovalState(data);
          setApprovalResult(JSON.stringify(data, null, 2));
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
    const cleanThreadId = targetThreadId.trim();
    if (!cleanThreadId) return;
    setIsRefreshingHistory(true);
    try {
      const response = await fetch(`/api/threads/${encodeURIComponent(cleanThreadId)}/history`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await extractError(response, t.errors.requestFailed));
      const data = (await response.json()) as ThreadHistoryResponse;
      const mappedItems: ChatItem[] = data.messages.map((message, index) => ({
        id: `${cleanThreadId}-${index}-${message.created_at}`,
        kind: message.kind,
        content: message.content,
        time: formatHistoryClock(locale, message.created_at),
      }));
      setChatItems(mappedItems);
      setHistoryCacheEnabled(data.cached);
      const firstUserMessage = mappedItems.find((item) => item.kind === "user")?.content || "";
      const latestAnswer = [...mappedItems].reverse().find((item) => item.kind === "answer" || item.kind === "error")
        ?.content;
      touchRecentThread(cleanThreadId, {
        title: firstUserMessage,
        preview: latestAnswer || firstUserMessage,
      });
      setChatStatus(mappedItems.length ? t.historyLoaded : t.historyEmpty);
    } catch (error) {
      setHistoryCacheEnabled(false);
      setChatStatus(error instanceof Error ? error.message : t.historyLoadFailed);
    } finally {
      setIsRefreshingHistory(false);
    }
  }

  async function streamChat(messages: ChatMessage[], targetThreadId: string) {
    const response = await fetch("/api/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "agent-v1",
        stream: true,
        show_thoughts: showThoughts,
        thread_id: targetThreadId,
        knowledge_namespace: resolvedNamespace,
        messages,
      }),
    });
    if (!response.ok || !response.body) throw new Error(await extractError(response, t.errors.requestFailed));
    const returnedThreadId = response.headers.get("x-thread-id");
    if (returnedThreadId) setThreadId(returnedThreadId);
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
          const nextItem = createChatItem(event.type, event.content, formatClock(locale));
          setChatItems((current) => [...current, nextItem]);
          if (event.type === "answer" || event.type === "error") {
            touchRecentThread(targetThreadId, { preview: event.content });
          }
        } catch {
          setChatStatus(t.errors.requestFailed);
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
    const activeThread = resolvedThreadId;
    const userItem = createChatItem("user", userPrompt, formatClock(locale));
    setChatItems((current) => [...current, userItem]);
    touchRecentThread(activeThread, { title: userPrompt, preview: userPrompt });
    setPrompt("");
    setChatStatus(t.startChat);
    setIsChatLoading(true);
    try {
      await streamChat([{ role: "user", content: userPrompt }], activeThread);
      setChatStatus(t.finishChat);
      await refreshApprovalState(activeThread);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      setChatStatus(message);
      setChatItems((current) => [...current, createChatItem("error", message, formatClock(locale))]);
    } finally {
      setIsChatLoading(false);
    }
  }

  function handleCreateFreshThread() {
    const nextThreadId = createThreadId();
    setThreadId(nextThreadId);
    setApprovalThreadId(nextThreadId);
    setSelectedFile(null);
    setFileInputResetKey((value) => value + 1);
    setChatItems([]);
    setHistoryCacheEnabled(null);
    setChatStatus(t.ready);
    setApprovalState(null);
    setApprovalResult("");
    setUploadResult(t.uploadIdle);
    setUploadFeedback(null);
    setPrompt("");
  }

  function handleClearChat() {
    setChatItems([]);
    setChatStatus(t.ready);
    setPrompt("");
  }

  function openRecentThread(targetThreadId: string) {
    const cleanThreadId = targetThreadId.trim();
    if (!cleanThreadId) return;
    setThreadId(cleanThreadId);
    setApprovalThreadId(cleanThreadId);
    setPrompt("");
    setChatStatus(t.loading);
    void loadThreadHistory(cleanThreadId);
    void refreshApprovalState(cleanThreadId);
  }

  async function handleUploadFile() {
    if (!selectedFile) {
      setUploadResult(t.errors.uploadMissing);
      setUploadFeedback({ kind: "error", message: t.errors.uploadMissing });
      return;
    }
    return new Promise<void>((resolve) => {
      startUploadTransition(async () => {
        const formData = new FormData();
        formData.append("file", selectedFile);
        formData.append("namespace_id", resolvedNamespace);
        formData.append("thread_id", resolvedThreadId);
        try {
          const response = await fetch("/api/knowledge/documents", { method: "POST", body: formData });
          if (!response.ok) throw new Error(await extractError(response, t.errors.requestFailed));
          const data = (await response.json()) as KnowledgeUploadResponse;
          setUploadResult(JSON.stringify(data, null, 2));
          setNamespaceId(data.namespace_id);
          setUploadFeedback({
            kind: "success",
            message: `${t.uploadDone} ${selectedFile.name}`,
          });
          await refreshKnowledgeStatus();
        } catch (error) {
          const message = error instanceof Error ? error.message : t.errors.requestFailed;
          setUploadResult(message);
          setUploadFeedback({ kind: "error", message });
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: approval.thread_id,
          approval_id: approval.approval_id,
          decision,
          comment: approvalComment.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await extractError(response, t.errors.requestFailed));
      const data = await response.json();
      setApprovalResult(JSON.stringify(data, null, 2));
      await refreshApprovalState(approval.thread_id);
      if (decision === "reject") setIsApprovalModalOpen(false);
    } catch (error) {
      setApprovalResult(error instanceof Error ? error.message : t.errors.requestFailed);
    }
  }

  async function handleResume() {
    if (!approvalState?.resumable) {
      setApprovalResult(t.errors.resumeUnavailable);
      return;
    }
    setIsChatLoading(true);
    try {
      await streamChat([], resolvedApprovalThread);
      await refreshApprovalState(resolvedApprovalThread);
      setIsApprovalModalOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      setChatItems((current) => [...current, createChatItem("error", message, formatClock(locale))]);
      setChatStatus(message);
    } finally {
      setIsChatLoading(false);
    }
  }

  return (
    <motion.section
      className={styles.shell}
      initial="hidden"
      animate="visible"
      transition={{ staggerChildren: 0.05, delayChildren: 0.03 }}
      aria-label="Super Agent workspace"
    >
      <motion.aside className={styles.sidebar} variants={panelVariants}>
        <section className={styles.sidebarPanel}>
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionLabel}>{t.uploadTitle}</span>
              <h2 className={styles.sidebarTitle}>{t.knowledgeTitle}</h2>
            </div>
            <button type="button" className={styles.iconButton} onClick={() => void refreshKnowledgeStatus()}>
              <RefreshCcw size={16} />
            </button>
          </div>
          <p className={styles.sectionHint}>{t.knowledgeHint}</p>
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
          {uploadFeedback ? (
            <div
              className={styles.noticeBanner}
              data-kind={uploadFeedback.kind}
              role="status"
              aria-live="polite"
            >
              {uploadFeedback.message}
            </div>
          ) : null}
          <div className={styles.statusGrid}>
            <div className={styles.statusCard}>
              <span>{t.service}</span>
              <strong>{serviceStatusText}</strong>
            </div>
            <div className={styles.statusCard}>
              <span>{t.mode}</span>
              <strong>{knowledgeStatus?.backend_mode || "-"}</strong>
            </div>
            <div className={styles.statusCard}>
              <span>{t.chunks}</span>
              <strong>{knowledgeStatus?.chunk_count ?? "-"}</strong>
            </div>
            <div className={styles.statusCard}>
              <span>{t.approval}</span>
              <strong>{approvalStatusText}</strong>
            </div>
          </div>
          <pre className={styles.codePanel}>{uploadResult || t.uploadIdle}</pre>
        </section>

        <section className={`${styles.sidebarPanel} ${styles.threadPanel}`}>
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionLabel}>{t.recentThreadsTitle}</span>
              <h2 className={styles.sidebarTitle}>{t.historyTitle}</h2>
            </div>
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => void loadThreadHistory(resolvedThreadId)}
              disabled={isRefreshingHistory}
            >
              {isRefreshingHistory ? <LoaderCircle className={styles.spin} size={16} /> : <RefreshCcw size={16} />}
            </button>
          </div>
          <p className={styles.sectionHint}>{t.recentThreadsHint}</p>
          <div className={styles.threadList}>
            {recentThreads.length ? (
              recentThreads.map((item) => (
                <button
                  key={item.threadId}
                  type="button"
                  className={styles.threadRow}
                  data-active={item.threadId === resolvedThreadId}
                  onClick={() => openRecentThread(item.threadId)}
                >
                  <div className={styles.threadRowHead}>
                    <strong>{item.title}</strong>
                    <time>{formatHistoryClock(locale, item.updatedAt)}</time>
                  </div>
                  <p>{item.preview || item.threadId}</p>
                </button>
              ))
            ) : (
              <div className={styles.placeholderPanel}>{t.recentThreadsEmpty}</div>
            )}
          </div>
        </section>
      </motion.aside>

      <motion.main className={styles.mainPanel} variants={panelVariants}>
        <header className={styles.mainHeader}>
          <div className={styles.mainHeaderCopy}>
            <span className={styles.kicker}>{t.kicker}</span>
            <h1 className={styles.mainTitle}>Super Agent</h1>
            <p className={styles.mainDescription}>{t.description}</p>
          </div>
          <div className={styles.mainHeaderActions}>
            <button
              type="button"
              className={styles.localeToggle}
              onClick={() => setLocale((current) => (current === "zh" ? "en" : "zh"))}
            >
              {locale === "zh" ? "EN" : "中"}
            </button>
            <label className={styles.thoughtToggle}>
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
          </div>
        </header>

        <div className={styles.mainMetaBar}>
          <div className={styles.metaPill}>
            <History size={14} />
            <span>{activeThreadRecord?.title || resolvedThreadId}</span>
          </div>
          <div className={styles.metaPill}>
            <Globe2 size={14} />
            <span>{resolvedNamespace}</span>
          </div>
          <div className={styles.metaPill}>
            <Waves size={14} />
            <span>{knowledgeStatus?.backend_mode || "-"}</span>
          </div>
          <div className={styles.metaPill}>
            <Sparkles size={14} />
            <span>{historyCacheEnabled == null ? t.loading : historyCacheEnabled ? t.historyCacheOn : t.historyCacheOff}</span>
          </div>
          {(approvalState?.approval || approvalState?.resumable) && (
            <button type="button" className={styles.warningPill} onClick={() => setIsApprovalModalOpen(true)}>
              <ShieldAlert size={14} />
              <span>{approvalStatusText}</span>
            </button>
          )}
        </div>

        <div ref={chatViewportRef} className={styles.chatViewport}>
          <div className={styles.chatViewportInner}>
            {visibleChatItems.length ? (
              <div className={styles.messageList}>
                {visibleChatItems.map((item) => (
                  <article key={item.id} className={styles.messageRow} data-kind={item.kind}>
                    <div className={styles.messageMeta}>
                      <span className={styles.messageRole}>{renderBadge(item.kind, t)}</span>
                      <time>{item.time}</time>
                    </div>
                    <div className={styles.messageBubble}>
                      <pre className={styles.messageContent}>{item.content}</pre>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className={styles.emptyState}>
                <div className={styles.emptyOrb}>
                  <Sparkles size={22} />
                </div>
                <span className={styles.sectionLabel}>{t.workspaceLabel}</span>
                <h3>{t.emptyStateTitle}</h3>
                <p>{t.emptyStateDescription}</p>
              </div>
            )}
          </div>
        </div>

        <footer className={styles.composerShell}>
          <div className={styles.composerMeta}>
            <span>{chatStatus || t.ready}</span>
            <button type="button" className={styles.secondaryButton} onClick={handleClearChat}>
              <XCircle size={16} />
              <span>{t.clearChat}</span>
            </button>
          </div>
          <div className={styles.composer}>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t.inputPlaceholder}
              rows={3}
            />
            <button type="button" className={styles.sendButton} onClick={handleSendMessage}>
              {isChatLoading ? <LoaderCircle className={styles.spin} size={18} /> : <SendHorizontal size={18} />}
            </button>
          </div>
        </footer>
      </motion.main>

      {isApprovalModalOpen ? (
        <div className={styles.modalBackdrop} onClick={() => setIsApprovalModalOpen(false)}>
          <motion.section
            className={styles.modalCard}
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <div>
                <span className={styles.sectionLabel}>{t.approvalTitle}</span>
                <h3 className={styles.modalTitle}>{t.approvalModalTitle}</h3>
                <p className={styles.modalDescription}>{t.approvalModalDescription}</p>
              </div>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => setIsApprovalModalOpen(false)}
                aria-label={t.close}
              >
                <XCircle size={16} />
              </button>
            </div>
            <div className={styles.modalMeta}>
              <div className={styles.metaPill}>
                <History size={14} />
                <span>{resolvedApprovalThread}</span>
              </div>
              <div className={styles.warningPill}>
                <ShieldAlert size={14} />
                <span>{approvalStatusText}</span>
              </div>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => void refreshApprovalState()}
                disabled={isRefreshingApproval}
                aria-label={t.refresh}
              >
                {isRefreshingApproval ? <LoaderCircle className={styles.spin} size={16} /> : <RefreshCcw size={16} />}
              </button>
            </div>
            <pre className={styles.codePanel}>{approvalResult || t.approvalEmpty}</pre>
            <label className={styles.field}>
              <span>{t.commentLabel}</span>
              <input
                value={approvalComment}
                onChange={(event) => setApprovalComment(event.target.value)}
                placeholder={t.commentPlaceholder}
              />
            </label>
            <div className={styles.modalActions}>
              <button type="button" className={styles.primaryButton} onClick={() => void handleApprovalDecision("approve")}>
                <CheckCircle2 size={16} />
                <span>{t.approve}</span>
              </button>
              <button type="button" className={styles.dangerButton} onClick={() => void handleApprovalDecision("reject")}>
                <ShieldAlert size={16} />
                <span>{t.reject}</span>
              </button>
              <button type="button" className={styles.secondaryButton} onClick={() => void handleResume()}>
                <LoaderCircle size={16} />
                <span>{t.resume}</span>
              </button>
            </div>
          </motion.section>
        </div>
      ) : null}
    </motion.section>
  );
}

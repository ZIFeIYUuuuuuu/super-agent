import { useEffect, useState, useTransition } from "react";

import type {
  ChatMessage,
  KnowledgeStatus,
  KnowledgeUploadResponse,
  ThreadHistoryResponse,
} from "@/lib/workspace-types";
import { getJson, postFormData, postStream } from "@/lib/api-client";

import { translations, type Locale } from "./content";
import type { ChatItem, ThreadRecord, UploadFeedback } from "./types";
import {
  createChatItem,
  createThreadId,
  decodeSsePayload,
  formatClock,
  formatHistoryClock,
  readKnowledgeNamespace,
  readLocale,
  readRecentThreads,
  readShowThoughts,
  storageKeys,
  truncateMessage,
} from "./utils";

type AfterStreamHook = (threadId: string) => Promise<void> | void;

export function useChatWorkspace() {
  const [locale, setLocale] = useState<Locale>(readLocale);
  const [showThoughts, setShowThoughts] = useState(readShowThoughts);
  const [threadId, setThreadId] = useState(() => createThreadId());
  const [namespaceId, setNamespaceId] = useState(readKnowledgeNamespace);
  const [prompt, setPrompt] = useState("");
  const [chatStatus, setChatStatus] = useState("");
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [recentThreads, setRecentThreads] = useState<ThreadRecord[]>(readRecentThreads);
  const [historyCacheEnabled, setHistoryCacheEnabled] = useState<boolean | null>(null);
  const [knowledgeStatus, setKnowledgeStatus] = useState<KnowledgeStatus | null>(null);
  const [uploadResult, setUploadResult] = useState("");
  const [uploadFeedback, setUploadFeedback] = useState<UploadFeedback | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputResetKey, setFileInputResetKey] = useState(0);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false);
  const [isUploading, startUploadTransition] = useTransition();
  const [isRefreshingStatus, startStatusTransition] = useTransition();

  const t = translations[locale];
  const safeDocumentTitle = locale === "zh" ? "Super Agent \u5de5\u4f5c\u53f0" : "Super Agent Workspace";
  const resolvedThreadId = threadId.trim() || createThreadId();
  const resolvedNamespace = namespaceId.trim() || "personal-memory";
  const visibleChatItems = chatItems.filter((item) => showThoughts || item.kind !== "thought");
  const serviceStatusText = isRefreshingStatus ? t.loading : knowledgeStatus ? t.online : t.unavailable;
  const activeThreadRecord = recentThreads.find((item) => item.threadId === resolvedThreadId);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = safeDocumentTitle;
    localStorage.setItem(storageKeys.language, locale);
  }, [locale, safeDocumentTitle]);

  useEffect(() => {
    localStorage.setItem(storageKeys.showThoughts, showThoughts ? "true" : "false");
  }, [showThoughts]);

  useEffect(() => {
    localStorage.setItem(storageKeys.recentThreads, JSON.stringify(recentThreads.slice(0, 10)));
  }, [recentThreads]);

  useEffect(() => {
    localStorage.setItem(storageKeys.knowledgeNamespace, resolvedNamespace);
  }, [resolvedNamespace]);

  useEffect(() => {
    setChatStatus(t.ready);
    setUploadResult(t.uploadIdle);
    setUploadFeedback(null);
  }, [t.ready, t.uploadIdle]);

  useEffect(() => {
    if (!uploadFeedback) return;
    const timeoutId = window.setTimeout(() => {
      setUploadFeedback(null);
    }, 3200);

    return () => window.clearTimeout(timeoutId);
  }, [uploadFeedback]);

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
          const data = await getJson<KnowledgeStatus>("/api/knowledge/status", t.errors.requestFailed);
          setKnowledgeStatus(data);
        } catch {
          setKnowledgeStatus(null);
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
      const data = await getJson<ThreadHistoryResponse>(
        `/api/threads/${encodeURIComponent(cleanThreadId)}/history`,
        t.errors.requestFailed,
      );
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

  async function runThreadStream(
    messages: ChatMessage[],
    targetThreadId: string,
    afterStream?: AfterStreamHook,
  ) {
    const response = await postStream(
      "/api/chat/completions",
      {
        model: "agent-v1",
        stream: true,
        show_thoughts: showThoughts,
        thread_id: targetThreadId,
        knowledge_namespace: resolvedNamespace,
        messages,
      },
      t.errors.requestFailed,
    );

    const returnedThreadId = response.headers.get("x-thread-id");
    const activeThreadId = returnedThreadId || targetThreadId;
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
            touchRecentThread(activeThreadId, { preview: event.content });
          }
        } catch {
          setChatStatus(t.errors.requestFailed);
        }
      }
    }

    if (afterStream) {
      await afterStream(activeThreadId);
    }
  }

  async function handleSendMessage(afterStream?: AfterStreamHook) {
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
      await runThreadStream([{ role: "user", content: userPrompt }], activeThread, afterStream);
      setChatStatus(t.finishChat);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      setChatStatus(message);
      setChatItems((current) => [...current, createChatItem("error", message, formatClock(locale))]);
    } finally {
      setIsChatLoading(false);
    }
  }

  async function resumeThread(targetThreadId: string, afterStream?: AfterStreamHook) {
    setIsChatLoading(true);
    try {
      await runThreadStream([], targetThreadId, afterStream);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.errors.requestFailed;
      setChatItems((current) => [...current, createChatItem("error", message, formatClock(locale))]);
      setChatStatus(message);
      throw error;
    } finally {
      setIsChatLoading(false);
    }
  }

  function handleCreateFreshThread() {
    const nextThreadId = createThreadId();
    setThreadId(nextThreadId);
    setSelectedFile(null);
    setFileInputResetKey((value) => value + 1);
    setChatItems([]);
    setHistoryCacheEnabled(null);
    setChatStatus(t.ready);
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
    setPrompt("");
    setChatStatus(t.loading);
    void loadThreadHistory(cleanThreadId);
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
          const data = await postFormData<KnowledgeUploadResponse>(
            "/api/knowledge/documents",
            formData,
            t.errors.requestFailed,
          );
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

  return {
    locale,
    t,
    showThoughts,
    prompt,
    chatStatus,
    recentThreads,
    historyCacheEnabled,
    knowledgeStatus,
    uploadResult,
    uploadFeedback,
    selectedFile,
    fileInputResetKey,
    isChatLoading,
    isRefreshingHistory,
    isUploading,
    resolvedThreadId,
    resolvedNamespace,
    visibleChatItems,
    serviceStatusText,
    activeThreadRecord,
    setLocale,
    setShowThoughts,
    setNamespaceId,
    setPrompt,
    setSelectedFile,
    refreshKnowledgeStatus,
    loadThreadHistory,
    handleSendMessage,
    resumeThread,
    handleCreateFreshThread,
    handleClearChat,
    openRecentThread,
    handleUploadFile,
  };
}

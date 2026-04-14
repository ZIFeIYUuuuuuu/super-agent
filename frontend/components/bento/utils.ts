import type { ChatStreamEvent } from "@/lib/workspace-types";

import type { Locale, TranslationShape } from "./content";
import type { ChatItem, ChatItemKind, ThreadRecord } from "./types";

const LANGUAGE_STORAGE_KEY = "super-agent-language-v6";
const SHOW_THOUGHT_STORAGE_KEY = "super-agent-show-thought-v3";
const RECENT_THREADS_STORAGE_KEY = "super-agent-recent-threads-v2";
const KNOWLEDGE_NAMESPACE_STORAGE_KEY = "super-agent-knowledge-namespace-v1";

export const storageKeys = {
  language: LANGUAGE_STORAGE_KEY,
  showThoughts: SHOW_THOUGHT_STORAGE_KEY,
  recentThreads: RECENT_THREADS_STORAGE_KEY,
  knowledgeNamespace: KNOWLEDGE_NAMESPACE_STORAGE_KEY,
} as const;

export function createThreadId() {
  if (typeof window !== "undefined" && typeof window.crypto?.randomUUID === "function") {
    return `thread-${window.crypto.randomUUID().slice(0, 8)}`;
  }
  return `thread-${Date.now().toString(36)}`;
}

export function readLocale(): Locale {
  if (typeof window === "undefined") return "zh";
  try {
    return localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

export function readShowThoughts() {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(SHOW_THOUGHT_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function readRecentThreads(): ThreadRecord[] {
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

export function readKnowledgeNamespace() {
  if (typeof window === "undefined") return "personal-memory";
  try {
    return localStorage.getItem(KNOWLEDGE_NAMESPACE_STORAGE_KEY)?.trim() || "personal-memory";
  } catch {
    return "personal-memory";
  }
}

export function formatClock(locale: Locale) {
  return new Date().toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatHistoryClock(locale: Locale, value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return formatClock(locale);
  return parsed.toLocaleTimeString(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function decodeBase64Utf8(value: string) {
  const binary = window.atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder("utf-8").decode(bytes);
}

export function decodeSsePayload(payload: Record<string, unknown>): ChatStreamEvent {
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

export function createChatItem(kind: ChatItemKind, content: string, time: string): ChatItem {
  return { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, kind, content, time };
}

export function truncateMessage(value: string, limit = 10) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  return Array.from(normalized).slice(0, limit).join("");
}

export function renderBadge(kind: ChatItemKind, t: TranslationShape) {
  if (kind === "thought") return t.thought;
  if (kind === "answer") return t.answer;
  if (kind === "error") return t.error;
  return t.user;
}

const LANGUAGE_STORAGE_KEY = "super-agent-language-v4";

const SHOW_THOUGHT_STORAGE_KEY = "super-agent-show-thought-v1";

try {
  localStorage.removeItem("super-agent-language");
  localStorage.removeItem("super-agent-language-v2");
  localStorage.removeItem("super-agent-language-v3");
} catch (_error) {
  // Ignore storage access issues and fall back to runtime defaults.
}

const translations = {
  zh: {
    brandKicker: "统一智能体工作台",
    brandName: "Super Agent",
    docsLink: "接口文档",
    heroEyebrow: "一个页面，整合全部能力。",
    heroTitle: "把对话、知识库、审批和系统状态放进同一张安静的画布。",
    heroDescription: "保留现有后端接口，在一个克制、清晰、可持续操作的页面里完成主要工作流。",
    threadLabel: "线程 ID",
    namespaceLabel: "知识命名空间",
    summaryService: "服务状态",
    summaryKnowledge: "知识模式",
    summaryChunks: "分片数量",
    summaryApproval: "审批状态",
    chatLabel: "对话",
    chatTitle: "流式工作区",
    newThreadBtn: "新建线程",
    clearChatBtn: "清空对话",
    chatReady: "已连接，准备就绪。",
    chatPrompt: "输入提示词",
    chatHint: "默认只展示回答；可手动打开思考过程。",
    showThoughtLabel: "显示思考过程",
    sendBtn: "发送",
    uploadLabel: "知识库",
    uploadTitle: "上传私有文档",
    uploadNamespaceLabel: "命名空间 / 线程",
    uploadFileLabel: "文档文件",
    uploadBtn: "上传",
    statusLabel: "状态",
    statusTitle: "知识后端",
    refreshBtn: "刷新",
    approvalLabel: "审批",
    approvalTitle: "人工介入",
    approvalThreadLabel: "审批线程",
    approvalCommentLabel: "备注",
    approvalEmpty: "当前线程还没有审批记录。",
    approveBtn: "批准",
    rejectBtn: "拒绝",
    resumeBtn: "恢复执行",
    outputLabel: "结果",
    outputTitle: "最新输出",
    activityLabel: "系统",
    activityTitle: "最近活动",
    placeholders: {
      thread: "输入或自动生成 thread_id",
      namespace: "可选，默认跟随 thread_id",
      prompt: "直接向 Agent 提问，或触发需要审批的任务。",
      comment: "给本次审批留下说明（可选）",
    },
    badgeThought: "思考",
    badgeAnswer: "回答",
    badgeError: "错误",
    badgeUser: "用户",
    activityReady: "页面已连接到后端。",
    activityStatusLoaded: "知识库状态已刷新。",
    activityChatStarted: "开始流式对话。",
    activityChatFinished: "流式输出完成。",
    activityUploadDone: "知识文档上传完成。",
    activityApprovalLoaded: "审批状态已刷新。",
    activityApprovalUpdated: "审批决定已提交。",
    activityResumeSent: "恢复执行请求已发送。",
    statusOnline: "在线",
    statusUnavailable: "不可用",
    statusLoading: "加载中",
    approvalPending: "等待审批",
    approvalApproved: "已批准",
    approvalRejected: "已拒绝",
    approvalResumable: "可恢复",
    approvalNotResumable: "不可恢复",
    noOutput: "这里会显示最近一次回答或关键结果。",
    noStatus: "点击刷新后查看当前知识库后端状态。",
    uploadWaiting: "选择 PDF 或 Markdown 文档后再上传。",
    errors: {
      emptyPrompt: "请先输入消息内容。",
      uploadMissing: "请先选择要上传的文件。",
      approvalMissing: "当前没有可操作的审批记录。",
      resumeUnavailable: "当前线程没有可恢复的审批流程。",
      requestFailed: "请求失败，请稍后重试。",
    },
    labels: {
      approvalId: "审批 ID",
      tool: "工具",
      risk: "风险等级",
      summary: "摘要",
      comment: "备注",
      resumable: "恢复能力",
      updatedAt: "更新时间",
    },
  },
  en: {
    brandKicker: "Unified AI Workspace",
    brandName: "Super Agent",
    docsLink: "API Docs",
    heroEyebrow: "One page, every capability.",
    heroTitle: "Keep chat, knowledge, approvals, and system state on one calm canvas.",
    heroDescription: "Reuse the current backend interfaces and operate the critical workflow from a restrained, focused single-page workspace.",
    threadLabel: "Thread ID",
    namespaceLabel: "Knowledge Namespace",
    summaryService: "Service",
    summaryKnowledge: "Knowledge Mode",
    summaryChunks: "Chunks",
    summaryApproval: "Approval",
    chatLabel: "Chat",
    chatTitle: "Streaming workspace",
    newThreadBtn: "New Thread",
    clearChatBtn: "Clear Chat",
    chatReady: "Connected and ready.",
    chatPrompt: "Prompt",
    chatHint: "Only answers are shown by default. You can enable thought details.",
    showThoughtLabel: "Show thought process",
    sendBtn: "Send",
    uploadLabel: "Knowledge",
    uploadTitle: "Upload private documents",
    uploadNamespaceLabel: "Namespace / Thread",
    uploadFileLabel: "Document",
    uploadBtn: "Upload",
    statusLabel: "Status",
    statusTitle: "Knowledge backend",
    refreshBtn: "Refresh",
    approvalLabel: "Approval",
    approvalTitle: "Human in the loop",
    approvalThreadLabel: "Approval Thread",
    approvalCommentLabel: "Comment",
    approvalEmpty: "No approval record for this thread yet.",
    approveBtn: "Approve",
    rejectBtn: "Reject",
    resumeBtn: "Resume",
    outputLabel: "Result",
    outputTitle: "Latest output",
    activityLabel: "System",
    activityTitle: "Recent activity",
    placeholders: {
      thread: "Enter or auto-generate a thread_id",
      namespace: "Optional, defaults to thread_id",
      prompt: "Ask the agent directly, or trigger a guarded workflow.",
      comment: "Optional note for this approval action",
    },
    badgeThought: "Thought",
    badgeAnswer: "Answer",
    badgeError: "Error",
    badgeUser: "User",
    activityReady: "The page is connected to the backend.",
    activityStatusLoaded: "Knowledge status refreshed.",
    activityChatStarted: "Streaming chat started.",
    activityChatFinished: "Streaming output completed.",
    activityUploadDone: "Knowledge document uploaded.",
    activityApprovalLoaded: "Approval status refreshed.",
    activityApprovalUpdated: "Approval decision submitted.",
    activityResumeSent: "Resume request sent.",
    statusOnline: "Online",
    statusUnavailable: "Unavailable",
    statusLoading: "Loading",
    approvalPending: "Pending approval",
    approvalApproved: "Approved",
    approvalRejected: "Rejected",
    approvalResumable: "Resumable",
    approvalNotResumable: "Not resumable",
    noOutput: "The latest answer or key result will appear here.",
    noStatus: "Refresh to inspect the current knowledge backend status.",
    uploadWaiting: "Choose a PDF or Markdown document before uploading.",
    errors: {
      emptyPrompt: "Please enter a message first.",
      uploadMissing: "Please choose a file before uploading.",
      approvalMissing: "There is no actionable approval record.",
      resumeUnavailable: "This thread has no resumable approval flow.",
      requestFailed: "Request failed. Please try again.",
    },
    labels: {
      approvalId: "Approval ID",
      tool: "Tool",
      risk: "Risk",
      summary: "Summary",
      comment: "Comment",
      resumable: "Resume",
      updatedAt: "Updated at",
    },
  },
};

const state = {
  language: readLanguage(),
  showThought: readShowThought(),
  currentThreadId: "",
  latestApproval: null,
};

const refs = {};

document.addEventListener("DOMContentLoaded", () => {
  bindRefs();
  ensureThread();
  bindEvents();
  syncSharedInputs();
  applyLanguage();
  setLatestOutput(t("noOutput"));
  refs.statusRaw.textContent = t("noStatus");
  refs.uploadResult.textContent = t("uploadWaiting");
  refreshKnowledgeStatus();
  refreshApprovalState();
  appendActivity(t("activityReady"));
});

function readLanguage() {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return stored === "en" ? "en" : "zh";
  } catch (_error) {
    return "zh";
  }
}

function writeLanguage(language) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch (_error) {
    // Ignore storage failures.
  }
}

function readShowThought() {
  try {
    return localStorage.getItem(SHOW_THOUGHT_STORAGE_KEY) === "true";
  } catch (_error) {
    return false;
  }
}

function writeShowThought(enabled) {
  try {
    localStorage.setItem(SHOW_THOUGHT_STORAGE_KEY, enabled ? "true" : "false");
  } catch (_error) {
    // Ignore storage failures.
  }
}

function bindRefs() {
  refs.localeToggle = document.getElementById("localeToggle");
  refs.threadId = document.getElementById("threadId");
  refs.namespaceId = document.getElementById("namespaceId");
  refs.serverStatusValue = document.getElementById("serverStatusValue");
  refs.kbBackendValue = document.getElementById("kbBackendValue");
  refs.kbChunksValue = document.getElementById("kbChunksValue");
  refs.approvalStateValue = document.getElementById("approvalStateValue");
  refs.newThreadBtn = document.getElementById("newThreadBtn");
  refs.clearChatBtn = document.getElementById("clearChatBtn");
  refs.showThoughtToggle = document.getElementById("showThoughtToggle");
  refs.chatStatus = document.getElementById("chatStatus");
  refs.chatStream = document.getElementById("chatStream");
  refs.chatForm = document.getElementById("chatForm");
  refs.chatInput = document.getElementById("chatInput");
  refs.sendBtn = document.getElementById("sendBtn");
  refs.uploadForm = document.getElementById("uploadForm");
  refs.uploadNamespace = document.getElementById("uploadNamespace");
  refs.uploadFile = document.getElementById("uploadFile");
  refs.uploadResult = document.getElementById("uploadResult");
  refs.refreshStatusBtn = document.getElementById("refreshStatusBtn");
  refs.statusRaw = document.getElementById("statusRaw");
  refs.refreshApprovalBtn = document.getElementById("refreshApprovalBtn");
  refs.approvalThreadId = document.getElementById("approvalThreadId");
  refs.approvalComment = document.getElementById("approvalComment");
  refs.approvalSummary = document.getElementById("approvalSummary");
  refs.approveBtn = document.getElementById("approveBtn");
  refs.rejectBtn = document.getElementById("rejectBtn");
  refs.resumeBtn = document.getElementById("resumeBtn");
  refs.approvalResult = document.getElementById("approvalResult");
  refs.latestOutput = document.getElementById("latestOutput");
  refs.activityList = document.getElementById("activityList");
  refs.chatItemTemplate = document.getElementById("chatItemTemplate");
}

function bindEvents() {
  refs.localeToggle.addEventListener("click", toggleLanguage);
  refs.newThreadBtn.addEventListener("click", createFreshThread);
  refs.clearChatBtn.addEventListener("click", clearChatSurface);
  refs.showThoughtToggle.addEventListener("change", onShowThoughtToggleChange);
  refs.threadId.addEventListener("change", handleThreadChange);
  refs.namespaceId.addEventListener("change", syncUploadNamespaceFromInputs);
  refs.chatForm.addEventListener("submit", onChatSubmit);
  refs.uploadForm.addEventListener("submit", onUploadSubmit);
  refs.refreshStatusBtn.addEventListener("click", refreshKnowledgeStatus);
  refs.refreshApprovalBtn.addEventListener("click", refreshApprovalState);
  refs.approveBtn.addEventListener("click", () => submitApprovalDecision("approve"));
  refs.rejectBtn.addEventListener("click", () => submitApprovalDecision("reject"));
  refs.resumeBtn.addEventListener("click", resumeApprovalThread);
}

function onShowThoughtToggleChange(event) {
  state.showThought = Boolean(event.target?.checked);
  writeShowThought(state.showThought);
}

function toggleLanguage() {
  state.language = state.language === "zh" ? "en" : "zh";
  writeLanguage(state.language);
  applyLanguage();
}

function applyLanguage() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = state.language === "zh" ? "Super Agent 工作台" : "Super Agent Workbench";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.dataset.i18n;
    if (key) {
      node.textContent = t(key);
    }
  });
  refs.localeToggle.textContent = state.language === "zh" ? "EN" : "中";
  refs.threadId.placeholder = t("placeholders.thread");
  refs.namespaceId.placeholder = t("placeholders.namespace");
  refs.chatInput.placeholder = t("placeholders.prompt");
  refs.uploadNamespace.placeholder = t("placeholders.namespace");
  refs.approvalThreadId.placeholder = t("placeholders.thread");
  refs.approvalComment.placeholder = t("placeholders.comment");
  refs.showThoughtToggle.checked = state.showThought;
  if (!refs.chatStream.children.length) {
    setLatestOutput(t("noOutput"));
  }
  if (!refs.statusRaw.dataset.loaded) {
    refs.statusRaw.textContent = t("noStatus");
  }
  if (!refs.uploadResult.dataset.loaded) {
    refs.uploadResult.textContent = t("uploadWaiting");
  }
  renderApprovalPanel(state.latestApproval);
}

function t(key) {
  const dict = translations[state.language] || translations.en;
  const parts = key.split(".");
  let value = dict;
  for (const part of parts) {
    value = value?.[part];
  }
  return typeof value === "string" ? value : key;
}

function ensureThread() {
  state.currentThreadId = refs.threadId.value.trim() || createThreadId();
}

function createThreadId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `thread-${window.crypto.randomUUID().slice(0, 8)}`;
  }
  return `thread-${Date.now().toString(36)}`;
}

function createFreshThread() {
  state.currentThreadId = createThreadId();
  refs.namespaceId.value = state.currentThreadId;
  syncSharedInputs();
  clearChatSurface();
  state.latestApproval = null;
  renderApprovalPanel(null);
  refs.approvalResult.textContent = "";
  refs.approvalResult.dataset.loaded = "";
  appendActivity(`${t("newThreadBtn")}: ${state.currentThreadId}`);
}

function handleThreadChange() {
  state.currentThreadId = refs.threadId.value.trim() || createThreadId();
  syncSharedInputs();
  refreshApprovalState();
}

function syncSharedInputs() {
  refs.threadId.value = state.currentThreadId;
  refs.approvalThreadId.value = state.currentThreadId;
  if (!refs.namespaceId.value.trim()) {
    refs.namespaceId.value = state.currentThreadId;
  }
  if (!refs.uploadNamespace.value.trim()) {
    refs.uploadNamespace.value = refs.namespaceId.value.trim() || state.currentThreadId;
  }
}

function syncUploadNamespaceFromInputs() {
  if (!refs.uploadNamespace.value.trim()) {
    refs.uploadNamespace.value = refs.namespaceId.value.trim() || state.currentThreadId;
  }
}

function clearChatSurface() {
  refs.chatStream.innerHTML = "";
  refs.chatStatus.textContent = t("chatReady");
  setLatestOutput(t("noOutput"));
}

function setLatestOutput(content) {
  refs.latestOutput.textContent = content;
}

function appendActivity(message) {
  const item = document.createElement("li");
  const now = new Date().toLocaleTimeString(state.language === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  item.textContent = `${now}  ${message}`;
  refs.activityList.prepend(item);
  while (refs.activityList.children.length > 10) {
    refs.activityList.removeChild(refs.activityList.lastChild);
  }
}

function appendStreamMessage(kind, content) {
  const fragment = refs.chatItemTemplate.content.cloneNode(true);
  const item = fragment.querySelector(".chat-item");
  const badge = fragment.querySelector(".chat-badge");
  const timeNode = fragment.querySelector(".chat-time");
  const contentNode = fragment.querySelector(".chat-content");
  item.dataset.kind = kind;
  badge.textContent = badgeText(kind);
  timeNode.textContent = new Date().toLocaleTimeString(state.language === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
  contentNode.textContent = content;
  refs.chatStream.appendChild(fragment);
  refs.chatStream.scrollTop = refs.chatStream.scrollHeight;
}

function badgeText(kind) {
  if (kind === "thought") return t("badgeThought");
  if (kind === "answer") return t("badgeAnswer");
  if (kind === "error") return t("badgeError");
  return t("badgeUser");
}

async function onChatSubmit(event) {
  event.preventDefault();
  const prompt = refs.chatInput.value.trim();
  if (!prompt) {
    refs.chatStatus.textContent = t("errors.emptyPrompt");
    return;
  }

  appendStreamMessage("user", prompt);
  refs.chatInput.value = "";
  refs.chatStatus.textContent = t("activityChatStarted");
  appendActivity(t("activityChatStarted"));

  try {
    await streamChat({
      model: "agent-v1",
      stream: true,
      show_thoughts: state.showThought,
      thread_id: refs.threadId.value.trim(),
      knowledge_namespace: refs.namespaceId.value.trim() || refs.threadId.value.trim(),
      messages: [{ role: "user", content: prompt }],
    });
    refs.chatStatus.textContent = t("activityChatFinished");
    appendActivity(t("activityChatFinished"));
    await refreshApprovalState();
  } catch (error) {
    const message = error instanceof Error ? error.message : t("errors.requestFailed");
    refs.chatStatus.textContent = message;
    appendStreamMessage("error", message);
    setLatestOutput(message);
  }
}

async function streamChat(payload) {
  const response = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const detail = await extractError(response);
    throw new Error(detail || t("errors.requestFailed"));
  }

  const resolvedThreadId = response.headers.get("x-thread-id");
  if (resolvedThreadId) {
    state.currentThreadId = resolvedThreadId;
    syncSharedInputs();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      handleSseBlock(part);
    }
  }

  if (buffer.trim()) {
    handleSseBlock(buffer);
  }
}

function handleSseBlock(block) {
  const lines = block.split(/\r?\n/);
  const payloadLines = [];
  for (const line of lines) {
    if (line.startsWith("data:")) {
      payloadLines.push(line.slice(5).trim());
    }
  }
  if (!payloadLines.length) return;
  const rawPayload = payloadLines.join("\n");
  if (rawPayload === "[DONE]") return;
  let event;
  try {
    event = decodeSsePayload(JSON.parse(rawPayload));
  } catch (_error) {
    appendActivity(t("errors.requestFailed"));
    return;
  }
  if (event.type === "thought" && !state.showThought) return;
  appendStreamMessage(event.type, event.content);
  if (event.type === "answer" || event.type === "error") {
    setLatestOutput(event.content);
  }
}

function decodeSsePayload(payload) {
  if (payload && typeof payload.content_b64 === "string") {
    return {
      type: String(payload.type || "thought"),
      content: decodeBase64Utf8(payload.content_b64),
    };
  }
  return {
    type: String(payload?.type || "thought"),
    content: String(payload?.content || ""),
  };
}

function decodeBase64Utf8(value) {
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder("utf-8").decode(bytes);
}

async function onUploadSubmit(event) {
  event.preventDefault();
  const file = refs.uploadFile.files?.[0];
  if (!file) {
    refs.uploadResult.textContent = t("errors.uploadMissing");
    return;
  }

  const namespace = refs.uploadNamespace.value.trim() || refs.namespaceId.value.trim() || refs.threadId.value.trim();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("namespace_id", namespace);
  formData.append("thread_id", refs.threadId.value.trim());

  refs.uploadResult.textContent = t("statusLoading");
  try {
    const response = await fetch("/v1/knowledge/documents", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      throw new Error(await extractError(response));
    }
    const data = await response.json();
    refs.uploadResult.textContent = JSON.stringify(data, null, 2);
    refs.uploadResult.dataset.loaded = "true";
    refs.namespaceId.value = data.namespace_id || namespace;
    refs.uploadNamespace.value = data.namespace_id || namespace;
    appendActivity(t("activityUploadDone"));
    await refreshKnowledgeStatus();
  } catch (error) {
    refs.uploadResult.textContent = error instanceof Error ? error.message : t("errors.requestFailed");
  }
}

async function refreshKnowledgeStatus() {
  refs.serverStatusValue.textContent = t("statusLoading");
  refs.kbBackendValue.textContent = "-";
  refs.kbChunksValue.textContent = "-";
  try {
    const response = await fetch("/v1/knowledge/status");
    if (!response.ok) {
      throw new Error(await extractError(response));
    }
    const data = await response.json();
    refs.serverStatusValue.textContent = t("statusOnline");
    refs.kbBackendValue.textContent = data.backend_mode || "-";
    refs.kbChunksValue.textContent = String(data.chunk_count ?? "-");
    refs.statusRaw.textContent = JSON.stringify(data, null, 2);
    refs.statusRaw.dataset.loaded = "true";
    appendActivity(t("activityStatusLoaded"));
  } catch (error) {
    refs.serverStatusValue.textContent = t("statusUnavailable");
    refs.statusRaw.textContent = error instanceof Error ? error.message : t("errors.requestFailed");
  }
}

async function refreshApprovalState() {
  const threadId = refs.approvalThreadId.value.trim() || refs.threadId.value.trim();
  if (!threadId) return;

  refs.approvalStateValue.textContent = t("statusLoading");
  try {
    const response = await fetch(`/v1/approvals/pending/${encodeURIComponent(threadId)}`);
    if (!response.ok) {
      throw new Error(await extractError(response));
    }
    const data = await response.json();
    state.latestApproval = data;
    renderApprovalPanel(data);
    refs.approvalResult.textContent = JSON.stringify(data, null, 2);
    refs.approvalResult.dataset.loaded = "true";
    appendActivity(t("activityApprovalLoaded"));
  } catch (error) {
    state.latestApproval = null;
    renderApprovalPanel(null);
    refs.approvalResult.textContent = error instanceof Error ? error.message : t("errors.requestFailed");
  }
}

function renderApprovalPanel(data) {
  const approval = data?.approval || null;
  if (!approval) {
    refs.approvalSummary.className = "approval-summary empty";
    refs.approvalSummary.textContent = t("approvalEmpty");
    refs.approvalStateValue.textContent = t("approvalNotResumable");
    refs.approveBtn.disabled = true;
    refs.rejectBtn.disabled = true;
    refs.resumeBtn.disabled = true;
    return;
  }

  const summaryLines = [
    `${t("labels.approvalId")}: ${approval.approval_id}`,
    `${t("labels.tool")}: ${approval.tool_name}`,
    `${t("labels.risk")}: ${approval.risk_level}`,
    `${t("labels.summary")}: ${approval.summary}`,
    `${t("labels.updatedAt")}: ${approval.updated_at}`,
  ];
  if (approval.comment) {
    summaryLines.push(`${t("labels.comment")}: ${approval.comment}`);
  }
  summaryLines.push(`${t("labels.resumable")}: ${data.resumable ? t("approvalResumable") : t("approvalNotResumable")}`);

  refs.approvalSummary.className = `approval-summary ${approval.status}`;
  refs.approvalSummary.textContent = summaryLines.join("\n");
  refs.approvalStateValue.textContent = approvalStatusLabel(approval.status, data.resumable);
  refs.approveBtn.disabled = approval.status !== "pending";
  refs.rejectBtn.disabled = approval.status !== "pending";
  refs.resumeBtn.disabled = !data.resumable;
}

function approvalStatusLabel(status, resumable) {
  if (status === "pending") return t("approvalPending");
  if (status === "approved") return resumable ? `${t("approvalApproved")} / ${t("approvalResumable")}` : t("approvalApproved");
  if (status === "rejected") return t("approvalRejected");
  return resumable ? t("approvalResumable") : t("approvalNotResumable");
}

async function submitApprovalDecision(decision) {
  const approval = state.latestApproval?.approval;
  if (!approval || approval.status !== "pending") {
    refs.approvalResult.textContent = t("errors.approvalMissing");
    return;
  }

  try {
    const response = await fetch("/v1/approvals/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: approval.thread_id,
        approval_id: approval.approval_id,
        decision,
        comment: refs.approvalComment.value.trim() || null,
      }),
    });
    if (!response.ok) {
      throw new Error(await extractError(response));
    }
    refs.approvalResult.textContent = JSON.stringify(await response.json(), null, 2);
    refs.approvalResult.dataset.loaded = "true";
    appendActivity(t("activityApprovalUpdated"));
    await refreshApprovalState();
  } catch (error) {
    refs.approvalResult.textContent = error instanceof Error ? error.message : t("errors.requestFailed");
  }
}

async function resumeApprovalThread() {
  if (!state.latestApproval?.resumable) {
    refs.approvalResult.textContent = t("errors.resumeUnavailable");
    return;
  }
  appendActivity(t("activityResumeSent"));
  await streamChat({
    model: "agent-v1",
    stream: true,
    show_thoughts: state.showThought,
    thread_id: refs.approvalThreadId.value.trim() || refs.threadId.value.trim(),
    knowledge_namespace: refs.namespaceId.value.trim() || refs.threadId.value.trim(),
    messages: [],
  });
}

async function extractError(response) {
  try {
    const data = await response.json();
    return data.detail || JSON.stringify(data);
  } catch (_error) {
    return response.statusText || t("errors.requestFailed");
  }
}

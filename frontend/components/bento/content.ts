export type Locale = "zh" | "en";

export type TranslationShape = {
  kicker: string;
  title: string;
  description: string;
  threadLabel: string;
  namespaceLabel: string;
  approvalThreadLabel: string;
  commentLabel: string;
  inputPlaceholder: string;
  threadPlaceholder: string;
  namespacePlaceholder: string;
  commentPlaceholder: string;
  newThread: string;
  clearChat: string;
  send: string;
  showThoughts: string;
  workspaceLabel: string;
  workspaceDescription: string;
  contextTitle: string;
  recentThreadsTitle: string;
  recentThreadsHint: string;
  recentThreadsEmpty: string;
  recentThreadsOpen: string;
  emptyStateTitle: string;
  emptyStateDescription: string;
  knowledgeHint: string;
  approvalHint: string;
  activityHint: string;
  uploadTitle: string;
  chooseFile: string;
  upload: string;
  uploadIdle: string;
  historyTitle: string;
  historyHint: string;
  historyEmpty: string;
  historyLoaded: string;
  historyLoadFailed: string;
  historyThreadLabel: string;
  historyCountLabel: string;
  historySyncedLabel: string;
  historyCacheLabel: string;
  historyCacheOn: string;
  historyCacheOff: string;
  approvalModalTitle: string;
  approvalModalDescription: string;
  close: string;
  knowledgeTitle: string;
  refresh: string;
  approvalTitle: string;
  approve: string;
  reject: string;
  resume: string;
  approvalEmpty: string;
  latestOutputTitle: string;
  activityTitle: string;
  service: string;
  mode: string;
  chunks: string;
  approval: string;
  online: string;
  unavailable: string;
  loading: string;
  outputEmpty: string;
  user: string;
  thought: string;
  answer: string;
  error: string;
  startChat: string;
  finishChat: string;
  uploadDone: string;
  approvalLoaded: string;
  approvalUpdated: string;
  resumeSent: string;
  knowledgeLoaded: string;
  ready: string;
  pending: string;
  approved: string;
  rejected: string;
  resumable: string;
  notResumable: string;
  errors: {
    emptyPrompt: string;
    uploadMissing: string;
    approvalMissing: string;
    resumeUnavailable: string;
    requestFailed: string;
  };
  labels: {
    approvalId: string;
    tool: string;
    risk: string;
    summary: string;
    comment: string;
    updatedAt: string;
    resumable: string;
  };
};

export const translations: Record<Locale, TranslationShape> = {
  zh: {
    kicker: "Next.js 15 智能体工作台",
    title: "把聊天、知识库、审批和系统状态放进同一张 Bento 工作画布。",
    description:
      "这个版本不再依赖旧的静态 HTML 页面，而是基于 React 19、App Router 和组件化状态流重新承载现有后端能力。",
    threadLabel: "线程 ID",
    namespaceLabel: "知识命名空间",
    approvalThreadLabel: "审批线程",
    commentLabel: "审批备注",
    inputPlaceholder: "直接向 Agent 提问，或触发需要审批的任务。",
    threadPlaceholder: "输入或自动生成 thread_id",
    namespacePlaceholder: "可选，默认跟随 thread_id",
    commentPlaceholder: "给本次审批留下说明（可选）",
    newThread: "新建线程",
    clearChat: "清空对话",
    send: "发送",
    showThoughts: "显示思考过程",
    workspaceLabel: "对话工作台",
    workspaceDescription:
      "主对话区保留流式输出，侧边工具栏负责知识、审批、历史和结果查看。",
    contextTitle: "上下文工具栏",
    recentThreadsTitle: "最近线程",
    recentThreadsHint:
      "这里保存最近 10 条线程记录，刷新页面后仍可继续回看当时的历史对话。",
    recentThreadsEmpty: "还没有可回看的线程记录。",
    recentThreadsOpen: "打开线程",
    emptyStateTitle: "从一个问题开始",
    emptyStateDescription:
      "你可以直接聊天，也可以上传私有文档、查看缓存历史、刷新审批状态，再围绕同一个线程持续推进。",
    knowledgeHint:
      "上传 PDF 或 Markdown 后，系统会把内容切分进当前知识命名空间。",
    approvalHint:
      "需要人工决策的高风险动作会先在这里等待审批，再恢复执行。",
    activityHint: "这里记录最近的刷新、上传、审批和历史加载动作。",
    uploadTitle: "上传私有文档",
    chooseFile: "选择 PDF / Markdown 文件",
    upload: "上传",
    uploadIdle: "选择 PDF 或 Markdown 文档后再上传。",
    historyTitle: "历史记录",
    historyHint: "这里展示当前线程最近的缓存消息，便于快速回看上下文。",
    historyEmpty: "当前线程暂无缓存历史记录。",
    historyLoaded: "历史记录已刷新。",
    historyLoadFailed: "历史记录加载失败。",
    historyThreadLabel: "当前线程",
    historyCountLabel: "缓存条数",
    historySyncedLabel: "最近同步",
    historyCacheLabel: "缓存状态",
    historyCacheOn: "Redis 热缓存已启用",
    historyCacheOff: "Redis 热缓存未启用",
    approvalModalTitle: "人工介入",
    approvalModalDescription:
      "当前线程命中了需要人工确认的高风险动作，请在弹窗内批准、拒绝，或在批准后恢复执行。",
    close: "关闭",
    knowledgeTitle: "知识后端",
    refresh: "刷新",
    approvalTitle: "人工介入",
    approve: "批准",
    reject: "拒绝",
    resume: "恢复执行",
    approvalEmpty: "当前线程还没有审批记录。",
    latestOutputTitle: "最新输出",
    activityTitle: "最近活动",
    service: "服务状态",
    mode: "知识模式",
    chunks: "分片数量",
    approval: "审批状态",
    online: "在线",
    unavailable: "不可用",
    loading: "加载中",
    outputEmpty: "这里会显示最近一次回答或关键结果。",
    user: "用户",
    thought: "思考",
    answer: "回答",
    error: "错误",
    startChat: "开始流式对话。",
    finishChat: "流式输出完成。",
    uploadDone: "知识文档上传完成。",
    approvalLoaded: "审批状态已刷新。",
    approvalUpdated: "审批决定已提交。",
    resumeSent: "恢复执行请求已发送。",
    knowledgeLoaded: "知识库状态已刷新。",
    ready: "已连接，准备就绪。",
    pending: "等待审批",
    approved: "已批准",
    rejected: "已拒绝",
    resumable: "可恢复",
    notResumable: "不可恢复",
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
      updatedAt: "更新时间",
      resumable: "恢复能力",
    },
  },
  en: {
    kicker: "Next.js 15 Agent Workspace",
    title: "Keep chat, knowledge, approvals, and system state on one Bento surface.",
    description:
      "This version no longer depends on the old static HTML shell. It now uses React 19, App Router, and typed component state to host the existing backend features.",
    threadLabel: "Thread ID",
    namespaceLabel: "Knowledge Namespace",
    approvalThreadLabel: "Approval Thread",
    commentLabel: "Approval Comment",
    inputPlaceholder: "Ask the agent directly, or trigger a guarded workflow.",
    threadPlaceholder: "Enter or auto-generate a thread_id",
    namespacePlaceholder: "Optional, defaults to thread_id",
    commentPlaceholder: "Optional note for this approval action",
    newThread: "New Thread",
    clearChat: "Clear Chat",
    send: "Send",
    showThoughts: "Show thought process",
    workspaceLabel: "Conversation workspace",
    workspaceDescription:
      "The main column stays focused on streaming chat while the right rail keeps knowledge, approval, history, and result controls close by.",
    contextTitle: "Context rail",
    recentThreadsTitle: "Recent threads",
    recentThreadsHint:
      "Keep the latest 10 threads on the left so you can reopen prior conversations after a refresh.",
    recentThreadsEmpty: "No recent thread history yet.",
    recentThreadsOpen: "Open thread",
    emptyStateTitle: "Start with one question",
    emptyStateDescription:
      "Chat directly, upload private documents, inspect cached history, and resume guarded runs from the same thread.",
    knowledgeHint:
      "Upload PDF or Markdown files to index them into the current knowledge namespace.",
    approvalHint:
      "High-risk actions pause here for review before the workflow resumes.",
    activityHint:
      "Recent refreshes, uploads, approval actions, and history loads appear here.",
    uploadTitle: "Upload private documents",
    chooseFile: "Choose a PDF / Markdown file",
    upload: "Upload",
    uploadIdle: "Choose a PDF or Markdown document before uploading.",
    historyTitle: "History",
    historyHint:
      "Review the latest cached messages for this thread without leaving the workspace.",
    historyEmpty: "No cached history for this thread.",
    historyLoaded: "History refreshed.",
    historyLoadFailed: "History load failed.",
    historyThreadLabel: "Current thread",
    historyCountLabel: "Cached items",
    historySyncedLabel: "Last synced",
    historyCacheLabel: "Cache status",
    historyCacheOn: "Redis hot cache enabled",
    historyCacheOff: "Redis hot cache disabled",
    approvalModalTitle: "Human in the loop",
    approvalModalDescription:
      "This thread hit a high-risk action. Review it in the modal, then approve, reject, or resume after approval.",
    close: "Close",
    knowledgeTitle: "Knowledge backend",
    refresh: "Refresh",
    approvalTitle: "Human in the loop",
    approve: "Approve",
    reject: "Reject",
    resume: "Resume",
    approvalEmpty: "No approval record for this thread yet.",
    latestOutputTitle: "Latest output",
    activityTitle: "Recent activity",
    service: "Service",
    mode: "Knowledge Mode",
    chunks: "Chunks",
    approval: "Approval",
    online: "Online",
    unavailable: "Unavailable",
    loading: "Loading",
    outputEmpty: "The latest answer or key result will appear here.",
    user: "User",
    thought: "Thought",
    answer: "Answer",
    error: "Error",
    startChat: "Streaming chat started.",
    finishChat: "Streaming output completed.",
    uploadDone: "Knowledge document uploaded.",
    approvalLoaded: "Approval state refreshed.",
    approvalUpdated: "Approval decision submitted.",
    resumeSent: "Resume request sent.",
    knowledgeLoaded: "Knowledge status refreshed.",
    ready: "Connected and ready.",
    pending: "Pending approval",
    approved: "Approved",
    rejected: "Rejected",
    resumable: "Resumable",
    notResumable: "Not resumable",
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
      updatedAt: "Updated at",
      resumable: "Resumable",
    },
  },
};

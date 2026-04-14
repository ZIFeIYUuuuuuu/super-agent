"use client";

import { useDeferredValue, useEffect, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";

import ApprovalModal from "./ApprovalModal";
import ChatWorkspace from "./ChatWorkspace";
import KnowledgePanel from "./KnowledgePanel";
import RecentThreadsPanel from "./RecentThreadsPanel";
import styles from "./BentoGrid.module.css";
import { useApprovalState } from "./useApprovalState";
import { useChatWorkspace } from "./useChatWorkspace";

const panelVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: "easeOut" as const },
  },
};

export default function BentoGrid() {
  const chatViewportRef = useRef<HTMLDivElement | null>(null);

  const chat = useChatWorkspace();
  const approval = useApprovalState(chat.t, chat.resolvedThreadId, chat.resumeThread);
  const deferredThreadId = useDeferredValue(chat.resolvedThreadId);

  useEffect(() => {
    void chat.refreshKnowledgeStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chatViewportRef.current) {
      chatViewportRef.current.scrollTop = chatViewportRef.current.scrollHeight;
    }
  }, [chat.visibleChatItems]);

  useEffect(() => {
    if (!deferredThreadId) return;
    void chat.loadThreadHistory(deferredThreadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deferredThreadId, chat.locale]);

  return (
    <motion.section
      className={styles.shell}
      initial="hidden"
      animate="visible"
      transition={{ staggerChildren: 0.05, delayChildren: 0.03 }}
      aria-label="Super Agent workspace"
    >
      <motion.aside className={styles.sidebar} variants={panelVariants}>
        <KnowledgePanel
          t={chat.t}
          namespaceId={chat.resolvedNamespace}
          selectedFileName={chat.selectedFile?.name || ""}
          fileInputResetKey={chat.fileInputResetKey}
          isUploading={chat.isUploading}
          serviceStatusText={chat.serviceStatusText}
          approvalStatusText={approval.approvalStatusText}
          uploadResult={chat.uploadResult}
          knowledgeStatus={chat.knowledgeStatus}
          onNamespaceChange={chat.setNamespaceId}
          onFileChange={chat.setSelectedFile}
          onRefresh={() => void chat.refreshKnowledgeStatus()}
          onUpload={() => void chat.handleUploadFile()}
        />

        <RecentThreadsPanel
          t={chat.t}
          locale={chat.locale}
          recentThreads={chat.recentThreads}
          resolvedThreadId={chat.resolvedThreadId}
          isRefreshingHistory={chat.isRefreshingHistory}
          onRefresh={() => void chat.loadThreadHistory(chat.resolvedThreadId)}
          onOpenThread={chat.openRecentThread}
        />
      </motion.aside>

      <motion.div variants={panelVariants}>
        <ChatWorkspace
          t={chat.t}
          locale={chat.locale}
          showThoughts={chat.showThoughts}
          prompt={chat.prompt}
          chatStatus={chat.chatStatus}
          resolvedThreadId={chat.resolvedThreadId}
          resolvedNamespace={chat.resolvedNamespace}
          activeThreadRecord={chat.activeThreadRecord}
          visibleChatItems={chat.visibleChatItems}
          historyCacheEnabled={chat.historyCacheEnabled}
          knowledgeMode={chat.knowledgeStatus?.backend_mode || "-"}
          approvalState={approval.approvalState}
          approvalStatusText={approval.approvalStatusText}
          isChatLoading={chat.isChatLoading}
          chatViewportRef={chatViewportRef}
          onToggleLocale={() => chat.setLocale((current) => (current === "zh" ? "en" : "zh"))}
          onToggleThoughts={chat.setShowThoughts}
          onNewThread={chat.handleCreateFreshThread}
          onOpenApproval={() => approval.setIsApprovalModalOpen(true)}
          onClearChat={chat.handleClearChat}
          onPromptChange={chat.setPrompt}
          onSendMessage={() => void chat.handleSendMessage(approval.refreshApprovalState)}
        />
      </motion.div>

      <ApprovalModal
        t={chat.t}
        isOpen={approval.isApprovalModalOpen}
        resolvedApprovalThread={approval.resolvedApprovalThread}
        approvalStatusText={approval.approvalStatusText}
        approvalResult={approval.approvalResult}
        approvalComment={approval.approvalComment}
        isRefreshingApproval={approval.isRefreshingApproval}
        onClose={() => approval.setIsApprovalModalOpen(false)}
        onRefresh={() => void approval.refreshApprovalState()}
        onCommentChange={approval.setApprovalComment}
        onApprove={() => void approval.handleApprovalDecision("approve")}
        onReject={() => void approval.handleApprovalDecision("reject")}
        onResume={() => void approval.handleResume()}
      />

      <AnimatePresence>
        {chat.uploadFeedback ? (
          <motion.div
            className={styles.toastStack}
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <div className={styles.toast} data-kind={chat.uploadFeedback.kind} role="status" aria-live="polite">
              {chat.uploadFeedback.message}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.section>
  );
}

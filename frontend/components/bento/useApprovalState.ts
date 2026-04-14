import { useEffect, useState, useTransition } from "react";

import type { ApprovalDecision, PendingApproval } from "@/lib/workspace-types";
import { getJson, postJson } from "@/lib/api-client";

import type { TranslationShape } from "./content";

type ResumeThread = (threadId: string, afterStream?: (threadId: string) => Promise<void> | void) => Promise<void>;

export function useApprovalState(t: TranslationShape, currentThreadId: string, resumeThread: ResumeThread) {
  const [approvalComment, setApprovalComment] = useState("");
  const [approvalResult, setApprovalResult] = useState("");
  const [approvalState, setApprovalState] = useState<PendingApproval | null>(null);
  const [isApprovalModalOpen, setIsApprovalModalOpen] = useState(false);
  const [isRefreshingApproval, startApprovalTransition] = useTransition();

  const resolvedApprovalThread = currentThreadId.trim();
  const approvalStatusText = approvalState?.approval
    ? approvalState.approval.status === "pending"
      ? t.pending
      : approvalState.approval.status === "approved"
        ? approvalState.resumable
          ? `${t.approved} / ${t.resumable}`
          : t.approved
        : t.rejected
    : t.notResumable;

  async function refreshApprovalState(targetThreadId?: string) {
    const activeThreadId = (targetThreadId || resolvedApprovalThread).trim();
    if (!activeThreadId) return;
    return new Promise<void>((resolve) => {
      startApprovalTransition(async () => {
        try {
          const data = await getJson<PendingApproval>(
            `/api/approvals/pending/${encodeURIComponent(activeThreadId)}`,
            t.errors.requestFailed,
          );
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

  async function handleApprovalDecision(decision: ApprovalDecision) {
    const approval = approvalState?.approval;
    if (!approval || approval.status !== "pending") {
      setApprovalResult(t.errors.approvalMissing);
      return;
    }

    try {
      const data = await postJson(
        "/api/approvals/decision",
        {
          thread_id: approval.thread_id,
          approval_id: approval.approval_id,
          decision,
          comment: approvalComment.trim() || null,
        },
        t.errors.requestFailed,
      );
      setApprovalResult(JSON.stringify(data, null, 2));
      await refreshApprovalState(approval.thread_id);
      if (decision === "reject") {
        setIsApprovalModalOpen(false);
      }
    } catch (error) {
      setApprovalResult(error instanceof Error ? error.message : t.errors.requestFailed);
    }
  }

  async function handleResume() {
    if (!approvalState?.resumable || !resolvedApprovalThread) {
      setApprovalResult(t.errors.resumeUnavailable);
      return;
    }

    try {
      await resumeThread(resolvedApprovalThread, async (threadId) => {
        await refreshApprovalState(threadId);
      });
      setIsApprovalModalOpen(false);
    } catch {
      // resumeThread already reports errors into chat state
    }
  }

  useEffect(() => {
    setApprovalComment("");
    setApprovalResult("");
    setApprovalState(null);
    if (!resolvedApprovalThread) return;
    void refreshApprovalState(resolvedApprovalThread);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedApprovalThread]);

  useEffect(() => {
    if (approvalState?.approval?.status === "pending" || approvalState?.resumable) {
      setIsApprovalModalOpen(true);
    }
  }, [approvalState]);

  return {
    approvalComment,
    approvalResult,
    approvalState,
    approvalStatusText,
    isApprovalModalOpen,
    isRefreshingApproval,
    resolvedApprovalThread,
    setApprovalComment,
    setIsApprovalModalOpen,
    refreshApprovalState,
    handleApprovalDecision,
    handleResume,
  };
}

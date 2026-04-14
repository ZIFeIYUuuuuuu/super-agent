import { CheckCircle2, History, LoaderCircle, RefreshCcw, ShieldAlert, XCircle } from "lucide-react";
import { motion } from "motion/react";

import type { TranslationShape } from "./content";
import styles from "./BentoGrid.module.css";

type ApprovalModalProps = {
  t: TranslationShape;
  isOpen: boolean;
  resolvedApprovalThread: string;
  approvalStatusText: string;
  approvalResult: string;
  approvalComment: string;
  isRefreshingApproval: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onCommentChange: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onResume: () => void;
};

export default function ApprovalModal({
  t,
  isOpen,
  resolvedApprovalThread,
  approvalStatusText,
  approvalResult,
  approvalComment,
  isRefreshingApproval,
  onClose,
  onRefresh,
  onCommentChange,
  onApprove,
  onReject,
  onResume,
}: ApprovalModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className={styles.modalBackdrop} onClick={onClose}>
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
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label={t.close}>
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
            onClick={onRefresh}
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
            onChange={(event) => onCommentChange(event.target.value)}
            placeholder={t.commentPlaceholder}
          />
        </label>
        <div className={styles.modalActions}>
          <button type="button" className={styles.primaryButton} onClick={onApprove}>
            <CheckCircle2 size={16} />
            <span>{t.approve}</span>
          </button>
          <button type="button" className={styles.dangerButton} onClick={onReject}>
            <ShieldAlert size={16} />
            <span>{t.reject}</span>
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onResume}>
            <LoaderCircle size={16} />
            <span>{t.resume}</span>
          </button>
        </div>
      </motion.section>
    </div>
  );
}

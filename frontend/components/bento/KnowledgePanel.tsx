import { FileUp, RefreshCcw } from "lucide-react";

import type { KnowledgeStatus } from "@/lib/workspace-types";

import type { TranslationShape } from "./content";
import styles from "./BentoGrid.module.css";

type KnowledgePanelProps = {
  t: TranslationShape;
  namespaceId: string;
  selectedFileName: string;
  fileInputResetKey: number;
  isUploading: boolean;
  serviceStatusText: string;
  approvalStatusText: string;
  uploadResult: string;
  knowledgeStatus: KnowledgeStatus | null;
  onNamespaceChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onRefresh: () => void;
  onUpload: () => void;
};

export default function KnowledgePanel({
  t,
  namespaceId,
  selectedFileName,
  fileInputResetKey,
  isUploading,
  serviceStatusText,
  approvalStatusText,
  uploadResult,
  knowledgeStatus,
  onNamespaceChange,
  onFileChange,
  onRefresh,
  onUpload,
}: KnowledgePanelProps) {
  return (
    <section className={styles.sidebarPanel}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionLabel}>{t.uploadTitle}</span>
          <h2 className={styles.sidebarTitle}>{t.knowledgeTitle}</h2>
        </div>
        <button type="button" className={styles.iconButton} onClick={onRefresh}>
          <RefreshCcw size={16} />
        </button>
      </div>
      <p className={styles.sectionHint}>{t.knowledgeHint}</p>
      <label className={styles.field}>
        <span>{t.namespaceLabel}</span>
        <input
          value={namespaceId}
          onChange={(event) => onNamespaceChange(event.target.value)}
          placeholder={t.namespacePlaceholder}
        />
      </label>
      <label className={styles.filePicker}>
        <span>{selectedFileName || t.chooseFile}</span>
        <input
          key={fileInputResetKey}
          type="file"
          accept=".pdf,.md,.markdown"
          onChange={(event) => onFileChange(event.target.files?.[0] || null)}
        />
      </label>
      <button type="button" className={styles.primaryButton} onClick={onUpload} disabled={isUploading}>
        <FileUp size={16} />
        <span>{isUploading ? t.loading : t.upload}</span>
      </button>
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
  );
}

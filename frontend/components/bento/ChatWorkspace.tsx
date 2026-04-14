import type { ChangeEvent, RefObject } from "react";

import {
  Globe2,
  History,
  LoaderCircle,
  SendHorizontal,
  ShieldAlert,
  Sparkles,
  SquarePen,
  Waves,
  XCircle,
} from "lucide-react";

import type { PendingApproval } from "@/lib/workspace-types";

import type { Locale, TranslationShape } from "./content";
import type { ChatItem, ThreadRecord } from "./types";
import { renderBadge } from "./utils";
import styles from "./BentoGrid.module.css";

type ChatWorkspaceProps = {
  t: TranslationShape;
  locale: Locale;
  showThoughts: boolean;
  prompt: string;
  chatStatus: string;
  resolvedThreadId: string;
  resolvedNamespace: string;
  activeThreadRecord: ThreadRecord | undefined;
  visibleChatItems: ChatItem[];
  historyCacheEnabled: boolean | null;
  knowledgeMode: string;
  approvalState: PendingApproval | null;
  approvalStatusText: string;
  isChatLoading: boolean;
  chatViewportRef: RefObject<HTMLDivElement | null>;
  onToggleLocale: () => void;
  onToggleThoughts: (checked: boolean) => void;
  onNewThread: () => void;
  onOpenApproval: () => void;
  onClearChat: () => void;
  onPromptChange: (value: string) => void;
  onSendMessage: () => void;
};

export default function ChatWorkspace({
  t,
  locale,
  showThoughts,
  prompt,
  chatStatus,
  resolvedThreadId,
  resolvedNamespace,
  activeThreadRecord,
  visibleChatItems,
  historyCacheEnabled,
  knowledgeMode,
  approvalState,
  approvalStatusText,
  isChatLoading,
  chatViewportRef,
  onToggleLocale,
  onToggleThoughts,
  onNewThread,
  onOpenApproval,
  onClearChat,
  onPromptChange,
  onSendMessage,
}: ChatWorkspaceProps) {
  const handleThoughtToggle = (event: ChangeEvent<HTMLInputElement>) => {
    onToggleThoughts(event.target.checked);
  };

  const handlePromptChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onPromptChange(event.target.value);
  };

  return (
    <main className={styles.mainPanel}>
      <header className={styles.mainHeader}>
        <div className={styles.mainHeaderCopy}>
          <span className={styles.kicker}>{t.kicker}</span>
          <h1 className={styles.mainTitle}>Super Agent</h1>
          <p className={styles.mainDescription}>{t.description}</p>
        </div>
        <div className={styles.mainHeaderActions}>
          <button type="button" className={styles.localeToggle} onClick={onToggleLocale}>
            {locale === "zh" ? "EN" : "中"}
          </button>
          <label className={styles.thoughtToggle}>
            <input type="checkbox" checked={showThoughts} onChange={handleThoughtToggle} />
            <span>{t.showThoughts}</span>
          </label>
          <button type="button" className={styles.secondaryButton} onClick={onNewThread}>
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
          <span>{knowledgeMode}</span>
        </div>
        <div className={styles.metaPill}>
          <Sparkles size={14} />
          <span>{historyCacheEnabled == null ? t.loading : historyCacheEnabled ? t.historyCacheOn : t.historyCacheOff}</span>
        </div>
        {(approvalState?.approval || approvalState?.resumable) && (
          <button type="button" className={styles.warningPill} onClick={onOpenApproval}>
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
          <button type="button" className={styles.secondaryButton} onClick={onClearChat}>
            <XCircle size={16} />
            <span>{t.clearChat}</span>
          </button>
        </div>
        <div className={styles.composer}>
          <textarea value={prompt} onChange={handlePromptChange} placeholder={t.inputPlaceholder} rows={3} />
          <button type="button" className={styles.sendButton} onClick={onSendMessage}>
            {isChatLoading ? <LoaderCircle className={styles.spin} size={18} /> : <SendHorizontal size={18} />}
          </button>
        </div>
      </footer>
    </main>
  );
}

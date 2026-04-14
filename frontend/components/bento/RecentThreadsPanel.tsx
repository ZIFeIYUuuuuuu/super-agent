import { LoaderCircle, RefreshCcw } from "lucide-react";

import type { Locale, TranslationShape } from "./content";
import type { ThreadRecord } from "./types";
import { formatHistoryClock } from "./utils";
import styles from "./BentoGrid.module.css";

type RecentThreadsPanelProps = {
  t: TranslationShape;
  locale: Locale;
  recentThreads: ThreadRecord[];
  resolvedThreadId: string;
  isRefreshingHistory: boolean;
  onRefresh: () => void;
  onOpenThread: (threadId: string) => void;
};

export default function RecentThreadsPanel({
  t,
  locale,
  recentThreads,
  resolvedThreadId,
  isRefreshingHistory,
  onRefresh,
  onOpenThread,
}: RecentThreadsPanelProps) {
  return (
    <section className={`${styles.sidebarPanel} ${styles.threadPanel}`}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionLabel}>{t.recentThreadsTitle}</span>
          <h2 className={styles.sidebarTitle}>{t.historyTitle}</h2>
        </div>
        <button type="button" className={styles.iconButton} onClick={onRefresh} disabled={isRefreshingHistory}>
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
              onClick={() => onOpenThread(item.threadId)}
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
  );
}

import BentoGrid from "@/components/bento/BentoGrid";

import styles from "./page.module.css";

export default function HomePage() {
  return (
    <main className={styles.page}>
      <section className={styles.intro}>
        <span className={styles.kicker}>Super Agent Frontend</span>
        <h1 className={styles.title}>React + Next.js workbench, replacing the old static shell.</h1>
        <p className={styles.description}>
          The new application layer now hosts the real chat, approval, knowledge, and
          system-status surfaces with typed React state and App Router routing, so we
          can evolve the front-end without staying trapped in a single static script.
        </p>
      </section>
      <BentoGrid />
    </main>
  );
}

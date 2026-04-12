import BentoGrid from "@/components/bento/BentoGrid";

import styles from "./page.module.css";

export default function HomePage() {
  return (
    <main className={styles.page}>
      <BentoGrid />
    </main>
  );
}

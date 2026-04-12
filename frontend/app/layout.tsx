import type { Metadata } from "next";
import type { ReactNode } from "react";

import SmoothScrollProvider from "@/components/SmoothScrollProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Super Agent Frontend",
  description: "Next.js 15 front-end refactor for the Super Agent workspace.",
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>
        <SmoothScrollProvider>{children}</SmoothScrollProvider>
      </body>
    </html>
  );
}

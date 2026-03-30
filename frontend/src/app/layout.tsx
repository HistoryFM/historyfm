import type { Metadata } from "next";
import { Lora, Playfair_Display } from "next/font/google";
import Link from "next/link";
import ThemeProvider from "./ThemeProvider";
import ThemeToggle from "./ThemeToggle";

import "./globals.css";

const lora = Lora({
  variable: "--font-lora",
  subsets: ["latin"],
  display: "swap",
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "HistoryFM — Historical Fiction",
  description:
    "Immerse yourself in meticulously researched historical fiction that brings pivotal moments in American history to life.",
};

function Header() {
  return (
    <header className="border-b border-rule-light">
      <nav className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
        <Link
          href="/"
          className="font-display text-xl tracking-tight text-ink"
        >
          HistoryFM
        </Link>
        <div className="flex items-center gap-6 text-sm font-serif tracking-wide uppercase text-ink-muted">
          <Link href="/" className="hover:text-ink transition-colors">
            Home
          </Link>
          <Link href="/polls" className="hover:text-ink transition-colors">
            Polls
          </Link>
          <ThemeToggle />
        </div>
      </nav>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t border-rule-light mt-auto">
      <div className="mx-auto max-w-4xl px-6 py-8 text-center text-sm text-ink-muted tracking-wide">
        <p className="uppercase text-xs tracking-widest">
          HistoryFM
        </p>
        <p className="mt-2">Where history finds its voice.</p>
      </div>
    </footer>
  );
}

const themeScript = `(function(){try{var t=localStorage.getItem("theme");var d=t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme:dark)").matches);if(d)document.documentElement.classList.add("dark");var f=localStorage.getItem("font-size");var s=f==="small"?0.9:f==="large"?1.15:1;document.documentElement.style.setProperty("--theme-font-scale",s)}catch(e){}})()`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${lora.variable} ${playfair.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col font-serif bg-parchment text-ink">
        <ThemeProvider>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </ThemeProvider>
      </body>
    </html>
  );
}

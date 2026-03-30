"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface Chapter {
  slug: string;
  title: string;
}

interface Props {
  novelSlug: string;
  chapters: Chapter[];
}

export default function ChapterList({ novelSlug, chapters }: Props) {
  const [lastChapter, setLastChapter] = useState<string | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(`reading-progress-${novelSlug}`);
      if (stored) {
        const data = JSON.parse(stored);
        setLastChapter(data.chapterSlug);
      }
    } catch {
      // ignore
    }
  }, [novelSlug]);

  return (
    <ol className="space-y-1">
      {chapters.map((ch, i) => {
        const isLastRead = ch.slug === lastChapter;
        return (
          <li key={ch.slug}>
            <Link
              href={`/novels/${novelSlug}/${ch.slug}`}
              className={`group flex items-baseline gap-3 py-3 border-b border-rule-light hover:bg-accent-light transition-colors px-3 -mx-3 rounded-sm ${
                isLastRead
                  ? "bg-accent-light border-l-2 border-l-accent"
                  : ""
              }`}
            >
              <span className="text-xs text-ink-muted font-mono w-6 shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-base text-ink group-hover:text-accent-dark transition-colors">
                {ch.title}
              </span>
              {isLastRead && (
                <span className="ml-auto text-xs text-accent whitespace-nowrap">
                  Last read
                </span>
              )}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

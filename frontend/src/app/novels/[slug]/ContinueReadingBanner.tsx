"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface Props {
  novelSlug: string;
}

export default function ContinueReadingBanner({ novelSlug }: Props) {
  const [bookmark, setBookmark] = useState<{
    chapterSlug: string;
    chapterNumber: string;
    chapterTitle: string;
  } | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(`reading-progress-${novelSlug}`);
      if (stored) setBookmark(JSON.parse(stored));
    } catch {
      // ignore
    }
  }, [novelSlug]);

  if (!bookmark) return null;

  return (
    <div className="mb-8 rounded-sm border border-accent bg-accent-light p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div>
        <p className="text-xs uppercase tracking-widest text-accent-dark mb-1">
          Continue Reading
        </p>
        <p className="text-sm text-ink">
          Chapter {bookmark.chapterNumber}: {bookmark.chapterTitle}
        </p>
      </div>
      <Link
        href={`/novels/${novelSlug}/${bookmark.chapterSlug}`}
        className="text-sm font-medium bg-accent text-parchment px-4 py-2 rounded-sm hover:bg-accent-dark transition-colors text-center"
      >
        Resume
      </Link>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { BookmarkData } from "@/lib/useBookmark";

interface Props {
  slug: string;
  title: string;
  description: string;
  chapterCount: number;
}

export default function NovelCard({
  slug,
  title,
  description,
  chapterCount,
}: Props) {
  const [bookmark, setBookmark] = useState<BookmarkData | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(`reading-progress-${slug}`);
      if (stored) setBookmark(JSON.parse(stored));
    } catch {
      // ignore
    }
  }, [slug]);

  return (
    <Link
      href={bookmark ? `/novels/${slug}/${bookmark.chapterSlug}` : `/novels/${slug}`}
      className="group block rounded-sm border border-rule-light bg-parchment-dark p-6 transition-colors hover:border-accent hover:bg-accent-light"
    >
      <h3 className="font-display text-xl text-ink group-hover:text-accent-dark transition-colors">
        {title}
      </h3>
      <p className="mt-3 text-sm leading-relaxed text-ink-light">
        {description}
      </p>
      <p className="mt-4 text-xs uppercase tracking-widest text-ink-muted">
        {chapterCount} chapters
      </p>
      {bookmark && (
        <p className="mt-3 text-xs text-accent font-medium">
          Continue reading &mdash; Chapter {bookmark.chapterNumber}
        </p>
      )}
    </Link>
  );
}

"use client";

import { useState, useEffect, useCallback } from "react";

export interface BookmarkData {
  chapterSlug: string;
  chapterNumber: string;
  chapterTitle: string;
  scrollPercent: number;
  timestamp: number;
}

function getStorageKey(novelSlug: string) {
  return `reading-progress-${novelSlug}`;
}

export function useBookmark(novelSlug: string) {
  const [bookmark, setBookmark] = useState<BookmarkData | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(getStorageKey(novelSlug));
      if (stored) setBookmark(JSON.parse(stored));
    } catch {
      // ignore malformed data
    }
  }, [novelSlug]);

  const saveBookmark = useCallback(
    (data: BookmarkData) => {
      localStorage.setItem(getStorageKey(novelSlug), JSON.stringify(data));
      setBookmark(data);
    },
    [novelSlug]
  );

  return { bookmark, saveBookmark };
}

export function useAllBookmarks(novelSlugs: string[]) {
  const [bookmarks, setBookmarks] = useState<Record<string, BookmarkData>>({});

  useEffect(() => {
    const result: Record<string, BookmarkData> = {};
    for (const slug of novelSlugs) {
      try {
        const stored = localStorage.getItem(getStorageKey(slug));
        if (stored) result[slug] = JSON.parse(stored);
      } catch {
        // ignore
      }
    }
    setBookmarks(result);
  }, [novelSlugs]);

  return bookmarks;
}

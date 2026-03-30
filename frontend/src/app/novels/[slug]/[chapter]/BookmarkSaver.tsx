"use client";

import { useEffect } from "react";

interface Props {
  novelSlug: string;
  chapterSlug: string;
  chapterNumber: string;
  chapterTitle: string;
}

export default function BookmarkSaver({
  novelSlug,
  chapterSlug,
  chapterNumber,
  chapterTitle,
}: Props) {
  useEffect(() => {
    const key = `reading-progress-${novelSlug}`;

    // Save immediately on mount
    const data = {
      chapterSlug,
      chapterNumber,
      chapterTitle,
      scrollPercent: 0,
      timestamp: Date.now(),
    };
    localStorage.setItem(key, JSON.stringify(data));

    // Debounced scroll tracking
    let timer: ReturnType<typeof setTimeout>;
    function onScroll() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const docHeight =
          document.documentElement.scrollHeight - window.innerHeight;
        const percent =
          docHeight > 0
            ? Math.round((window.scrollY / docHeight) * 100)
            : 100;
        const updated = {
          chapterSlug,
          chapterNumber,
          chapterTitle,
          scrollPercent: percent,
          timestamp: Date.now(),
        };
        localStorage.setItem(key, JSON.stringify(updated));
      }, 500);
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      clearTimeout(timer);
      window.removeEventListener("scroll", onScroll);
    };
  }, [novelSlug, chapterSlug, chapterNumber, chapterTitle]);

  return null;
}

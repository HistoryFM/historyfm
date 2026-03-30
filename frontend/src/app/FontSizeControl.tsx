"use client";

import { useTheme } from "./ThemeProvider";

const SIZES = ["small", "default", "large"] as const;

export default function FontSizeControl() {
  const { fontSize, setFontSize } = useTheme();

  const currentIndex = SIZES.indexOf(fontSize);
  const canDecrease = currentIndex > 0;
  const canIncrease = currentIndex < SIZES.length - 1;

  const decrease = () => {
    if (canDecrease) setFontSize(SIZES[currentIndex - 1]);
  };

  const increase = () => {
    if (canIncrease) setFontSize(SIZES[currentIndex + 1]);
  };

  return (
    <span className="inline-flex items-center border border-rule-light rounded-sm normal-case tracking-normal">
      <button
        onClick={decrease}
        disabled={!canDecrease}
        className="px-2 py-1 text-xs text-ink-muted hover:text-ink hover:bg-parchment-dark transition-colors disabled:opacity-25 disabled:cursor-default"
        aria-label="Decrease font size"
        title="Smaller text"
      >
        A&minus;
      </button>
      <span className="w-px h-4 bg-rule-light" />
      <button
        onClick={increase}
        disabled={!canIncrease}
        className="px-2 py-1 text-xs text-ink-muted hover:text-ink hover:bg-parchment-dark transition-colors disabled:opacity-25 disabled:cursor-default"
        aria-label="Increase font size"
        title="Larger text"
      >
        A+
      </button>
    </span>
  );
}

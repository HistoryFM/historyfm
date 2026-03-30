"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";

type Theme = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";
type FontSize = "small" | "default" | "large";

const FONT_SCALE: Record<FontSize, number> = {
  small: 0.9,
  default: 1,
  large: 1.15,
};

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (t: Theme) => void;
  fontSize: FontSize;
  setFontSize: (s: FontSize) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}

export default function ThemeProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");
  const [fontSize, setFontSizeState] = useState<FontSize>("default");

  const applyTheme = useCallback((t: Theme) => {
    const isDark =
      t === "dark" ||
      (t === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", isDark);
    setResolvedTheme(isDark ? "dark" : "light");
  }, []);

  const applyFontSize = useCallback((s: FontSize) => {
    document.documentElement.style.setProperty(
      "--theme-font-scale",
      String(FONT_SCALE[s])
    );
  }, []);

  const setTheme = useCallback(
    (t: Theme) => {
      setThemeState(t);
      localStorage.setItem("theme", t);
      applyTheme(t);
    },
    [applyTheme]
  );

  const setFontSize = useCallback(
    (s: FontSize) => {
      setFontSizeState(s);
      localStorage.setItem("font-size", s);
      applyFontSize(s);
    },
    [applyFontSize]
  );

  useEffect(() => {
    // Theme
    const storedTheme = localStorage.getItem("theme") as Theme | null;
    const initialTheme = storedTheme ?? "system";
    setThemeState(initialTheme);
    applyTheme(initialTheme);

    // Font size
    const storedFont = localStorage.getItem("font-size") as FontSize | null;
    const initialFont = storedFont ?? "default";
    setFontSizeState(initialFont);
    applyFontSize(initialFont);

    // System theme listener
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const current = localStorage.getItem("theme") as Theme | null;
      if (!current || current === "system") applyTheme("system");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [applyTheme, applyFontSize]);

  return (
    <ThemeContext.Provider
      value={{ theme, resolvedTheme, setTheme, fontSize, setFontSize }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

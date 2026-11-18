import { useEffect, useState } from "react";

// The theme lives on <html data-theme="light|dark">. An inline script in index.html sets it before
// the first paint (saved choice, else the system setting), so the page never flashes the wrong theme.
const KEY = "sf_theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage can be blocked (private mode, strict settings)
  }
}

function apply(theme) {
  document.documentElement.dataset.theme = theme;
}

export function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "light");

  // Until the user picks a theme, follow the system setting live.
  useEffect(() => {
    const mq = media();
    const onChange = () => {
      if (savedTheme()) return;
      const next = mq.matches ? "dark" : "light";
      apply(next);
      setTheme(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // not saved; the choice still applies for this visit
    }
    setTheme(next);
  };

  return { theme, toggle };
}

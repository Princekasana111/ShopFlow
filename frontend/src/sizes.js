import { useEffect, useState } from "react";
import { api } from "./api.js";

// Mirrors backend/store/sizes.py: the size system is read from the size values themselves.
const TOP = ["XS", "S", "M", "L", "XL", "XXL"];

export function productSizes(product) {
  if (Array.isArray(product?.sizes)) return product.sizes;
  return String(product?.attributes?.sizes || "").split(",").map((s) => s.trim()).filter(Boolean);
}

export function sizeSystem(sizes) {
  if (!sizes.length) return null;
  if (sizes.every((s) => /^UK \d{1,2}$/.test(s))) return "shoe";
  if (sizes.every((s) => /^UK \d{1,2}-\d{1,2}$/.test(s))) return "shoe_range";
  if (sizes.every((s) => TOP.includes(s))) return "top";
  if (sizes.every((s) => /^\d+$/.test(s))) return "waist";
  if (sizes.every((s) => /^age/i.test(s))) return "age";
  return "other";
}

/** The size this shopper would pick from `sizes`, or null. */
export function preferredSize(prefs, sizes) {
  if (!prefs) return null;
  const system = sizeSystem(sizes);
  if (system === "shoe" && prefs.shoe_size_uk) return `UK ${prefs.shoe_size_uk}`;
  if (system === "shoe_range" && prefs.shoe_size_uk) {
    return sizes.find((s) => {
      const [low, high] = s.match(/\d+/g).map(Number);
      return low <= prefs.shoe_size_uk && prefs.shoe_size_uk <= high;
    }) || null;
  }
  if (system === "top" && prefs.clothing_size) return prefs.clothing_size;
  if (system === "waist" && prefs.waist_in) return String(prefs.waist_in);
  return null;
}

// Cached per user id, so logging out and in as someone else never shows the previous person's sizes.
let cached = { userId: null, prefs: null };

/** The signed-in shopper's saved sizes and needs (fetched once per user per page load). */
export function usePreferences(user) {
  const mine = user && cached.userId === user.id ? cached.prefs : null;
  const [prefs, setPrefs] = useState(mine);
  useEffect(() => {
    if (!user) {
      cached = { userId: null, prefs: null };
      return setPrefs(null);
    }
    if (cached.userId === user.id && cached.prefs) return setPrefs(cached.prefs);
    setPrefs(null);
    api("/api/auth/me/preferences/").then((p) => { cached = { userId: user.id, prefs: p }; setPrefs(p); }).catch(() => setPrefs(null));
  }, [user?.id]);
  const save = async (next) => {
    const saved = await api("/api/auth/me/preferences/", { method: "PUT", body: next });
    cached = { userId: user?.id ?? null, prefs: saved };
    setPrefs(saved);
    return saved;
  };
  return { prefs, save };
}

// Small fetch wrapper: attaches the JWT, refreshes it once on 401, and parses errors.
const ACCESS = "sf_access";
const REFRESH = "sf_refresh";

export const tokens = {
  get access() { return localStorage.getItem(ACCESS); },
  get refresh() { return localStorage.getItem(REFRESH); },
  set({ access, refresh }) {
    if (access) localStorage.setItem(ACCESS, access);
    if (refresh) localStorage.setItem(REFRESH, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
};

export class ApiError extends Error {
  constructor(status, data) {
    super(errorMessage(data) || `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

function errorMessage(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (data.detail) return data.detail;
  const [field, value] = Object.entries(data)[0] || [];
  if (!field) return "";
  const text = Array.isArray(value) ? value[0] : String(value);
  return field === "non_field_errors" ? text : `${field.replaceAll("_", " ")}: ${text}`;
}

async function refreshAccess() {
  if (!tokens.refresh) return false;
  const res = await fetch("/api/auth/refresh/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh: tokens.refresh }),
  });
  if (!res.ok) {
    tokens.clear();
    return false;
  }
  tokens.set(await res.json());
  return true;
}

export async function rawFetch(path, options = {}, retry = true) {
  const headers = { ...(options.headers || {}) };
  if (typeof options.body === "string" && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && retry && tokens.refresh && (await refreshAccess())) {
    return rawFetch(path, options, false);
  }
  return res;
}

export async function api(path, { method = "GET", body, query } = {}) {
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "")) : "";
  const res = await rawFetch(path + qs, { method, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export async function upload(path, formData) {
  const res = await rawFetch(path, { method: "POST", body: formData });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

// Server-Sent Events over POST (EventSource only supports GET without auth headers).
export async function streamChat({ message, sessionId, onEvent, signal }) {
  const res = await rawFetch("/api/ai/assistant/chat/", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId || null }),
    signal,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(event, JSON.parse(data));
    }
  }
}

export const rupees = (value) => {
  const n = Number(value);
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
};

export const notifyCartChanged = () => window.dispatchEvent(new Event("cart-changed"));

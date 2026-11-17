import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, Minus, Plus, Star } from "lucide-react";

export function Stars({ value = 0, size = 14 }) {
  return (
    <span className="stars" aria-label={`${Number(value).toFixed(1)} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} size={size} className={value >= i - 0.25 ? "" : "empty"} fill={value >= i - 0.25 ? "currentColor" : "none"} strokeWidth={value >= i - 0.25 ? 0 : 1.8} />
      ))}
    </span>
  );
}

export function Rating({ value, count }) {
  if (!value) return <span className="muted small">No reviews yet</span>;
  return (
    <span className="rating"><Stars value={value} size={13} /> {Number(value).toFixed(1)} <span className="muted">({count})</span></span>
  );
}

export function Stepper({ value, min = 1, max = 10, onChange, size }) {
  return (
    <span className={`stepper ${size === "sm" ? "sm" : ""}`}>
      <button type="button" onClick={() => onChange(value - 1)} disabled={value <= min} aria-label="Decrease quantity"><Minus size={15} /></button>
      <span aria-live="polite">{value}</span>
      <button type="button" onClick={() => onChange(value + 1)} disabled={value >= max} aria-label="Increase quantity"><Plus size={15} /></button>
    </span>
  );
}

const STATUS = {
  PENDING: ["info", "Placed"],
  SHIPPED: ["warning", "Shipped"],
  DELIVERED: ["good", "Delivered"],
  CANCELLED: ["critical", "Cancelled"],
};
export function StatusBadge({ status }) {
  const [cls, label] = STATUS[status] || ["", status];
  return <span className={`status-badge ${cls}`}><span className="dot" />{label}</span>;
}

export function SkeletonGrid({ count = 8 }) {
  return (
    <div className="grid">
      {Array.from({ length: count }, (_, i) => <div key={i} className="skeleton" style={{ height: 290 }} />)}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="card empty-state">
      <div className="icon-tile">{Icon && <Icon size={26} />}</div>
      <h2>{title}</h2>
      <div className="muted">{children}</div>
    </div>
  );
}

// Tiny toast system: toast("Added to cart") from anywhere.
export function toast(message, kind = "success") {
  window.dispatchEvent(new CustomEvent("toast", { detail: { message, kind, id: Date.now() + Math.random() } }));
}

export function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const add = (e) => {
      setItems((list) => [...list, e.detail].slice(-3));
      setTimeout(() => setItems((list) => list.filter((t) => t.id !== e.detail.id)), 3200);
    };
    window.addEventListener("toast", add);
    return () => window.removeEventListener("toast", add);
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.kind === "error" ? <CircleAlert size={18} /> : <CircleCheck size={18} />}
          {t.message}
        </div>
      ))}
    </div>
  );
}

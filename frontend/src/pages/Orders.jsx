import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CircleCheck, CircleX, Clock, MapPin, Package, PackageCheck, Truck } from "lucide-react";
import { api, rupees } from "../api.js";
import ProductArt from "../components/ProductArt.jsx";
import { EmptyState, StatusBadge, toast } from "../components/ui.jsx";

const STAGES = [
  ["PENDING", "Order placed", Clock],
  ["SHIPPED", "Shipped", Truck],
  ["DELIVERED", "Delivered", PackageCheck],
];

export function OrderCard({ order, onChange, admin }) {
  const [busy, setBusy] = useState(false);
  const reachedIndex = Math.max(...STAGES.map(([s], i) => (order.events.some((e) => e.status === s) ? i : -1)));
  const act = async (path, body, message) => {
    setBusy(true);
    try {
      onChange(await api(`/api/orders/${order.id}/${path}/`, { method: "POST", body }));
      toast(message);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card">
      <div className="order-head">
        <div>
          <h3 style={{ margin: 0 }}>Order #{order.id}{admin ? ` · ${order.username}` : ""}</h3>
          <span className="muted small icon-text"><Clock size={13} />{new Date(order.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}<MapPin size={13} style={{ marginLeft: 8 }} />{order.shipping_city} {order.shipping_pincode}</span>
        </div>
        <StatusBadge status={order.status} />
      </div>

      {order.status === "CANCELLED" ? (
        <p className="notice" style={{ marginTop: 16 }}><CircleX size={18} />This order was cancelled and any payment refunded.</p>
      ) : (
        <div className="tracker">
          <div className="rail"><div style={{ width: `${(reachedIndex / (STAGES.length - 1)) * 100}%` }} /></div>
          {STAGES.map(([status, label, Icon], i) => {
            const event = order.events.find((e) => e.status === status);
            return (
              <div key={status} className={`stage ${i <= reachedIndex ? "done" : ""}`}>
                <span className="bubble"><Icon size={17} /></span>
                {label}
                <span className="muted small" style={{ fontWeight: 500 }}>{event ? new Date(event.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="order-items">
        {order.items.map((i) => (
          <div key={i.id} className="order-item">
            <ProductArt product={{ name: i.product_name, category: i.category }} size="sm" />
            <span>{i.product ? <Link to={`/products/${i.product}`}>{i.product_name}</Link> : i.product_name} <span className="muted">{i.size ? ` · ${i.size}` : ""} × {i.quantity}</span></span>
            <strong>{rupees(i.line_total)}</strong>
          </div>
        ))}
      </div>

      <div className="row spread" style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
        <span><span className="muted">Total</span> <strong style={{ fontSize: "1.1rem" }}>{rupees(order.total)}</strong></span>
        <div className="row" style={{ gap: 8 }}>
          {order.status === "PENDING" && <button className="btn sm" disabled={busy} onClick={() => act("cancel", undefined, `Order #${order.id} cancelled`)}><CircleX size={15} />Cancel order</button>}
          {admin && order.status === "PENDING" && <button className="btn sm primary" disabled={busy} onClick={() => act("status", { status: "SHIPPED", note: "Handed to courier" }, `Order #${order.id} marked shipped`)}><Truck size={15} />Mark shipped</button>}
          {admin && order.status === "SHIPPED" && <button className="btn sm primary" disabled={busy} onClick={() => act("status", { status: "DELIVERED", note: "Delivered" }, `Order #${order.id} marked delivered`)}><CircleCheck size={15} />Mark delivered</button>}
        </div>
      </div>
    </div>
  );
}

export default function Orders() {
  const [orders, setOrders] = useState(null);
  const [params] = useSearchParams();
  const placed = params.get("placed");

  useEffect(() => { api("/api/orders/", { query: { scope: "mine" } }).then((r) => setOrders(r.results)).catch(() => setOrders([])); }, []);
  const replace = (updated) => setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)));

  if (!orders) return <div className="skeleton" style={{ height: 300 }} />;
  return (
    <>
      <div className="page-head">
        <h1>My orders</h1>
        <p>Track deliveries and manage recent purchases.</p>
      </div>
      {placed && <p className="notice" style={{ marginBottom: 18 }}><CircleCheck size={18} />Order #{placed} placed successfully. You can track it here.</p>}
      {orders.length === 0 ? (
        <EmptyState icon={Package} title="No orders yet"><Link to="/">Start shopping</Link></EmptyState>
      ) : (
        <div className="stack">{orders.map((o) => <OrderCard key={o.id} order={o} onChange={replace} />)}</div>
      )}
    </>
  );
}

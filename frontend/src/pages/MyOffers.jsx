import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, CircleAlert, CircleCheck, Clock, Handshake, MessageCircle, PackageCheck, RefreshCw, ShoppingCart, Trash2, X } from "lucide-react";
import { getOfferRules } from "../ai.js";
import { api, notifyCartChanged, rupees } from "../api.js";
import OfferThread from "../components/OfferThread.jsx";
import ProductArt from "../components/ProductArt.jsx";
import { EmptyState, toast } from "../components/ui.jsx";

const time = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
const day = (iso) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

// Status is always an icon plus words, never colour alone.
const STATE = {
  negotiating: [MessageCircle, "Bargaining", "info"],
  deal: [Handshake, "Deal held", "pass"],
  expired: [Clock, "Deal expired", "warn"],
  ordered: [PackageCheck, "Ordered", "pass"],
  ended: [X, "Ended", "skip"],
};

function OfferRow({ offer, onChange }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [Icon, label, tone] = STATE[offer.state];

  const act = async (path, body, done) => {
    setBusy(true);
    try {
      const r = await api(`/api/ai/offers/${offer.id}/${path}/`, { method: "POST", body });
      notifyCartChanged();
      toast(done(r.offer));
      onChange();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const price = offer.deal_price || offer.counter_price;
  return (
    <li className="card offer-row">
      <div className="offer-row-main">
        <Link to={`/products/${offer.product_id}`} aria-label={`Open ${offer.product.name}`}><ProductArt product={offer.product} size="sm" /></Link>
        <div style={{ minWidth: 0 }}>
          <Link to={`/products/${offer.product_id}`} className="title">{offer.product.name}</Link>
          <div className="muted small">
            List {rupees(offer.list_price)}
            {offer.state === "negotiating" && offer.your_offer && <> · your offer {rupees(offer.your_offer)}</>}
            {price && offer.state !== "ended" && <> · {offer.state === "negotiating" ? "counter-offer" : "deal"} <strong style={{ color: "var(--ink)" }}>{rupees(price)}</strong></>}
            {Number(offer.saving) > 0 && <> · you save {rupees(offer.saving)}</>}
            {" · started "}{day(offer.created_at)}
          </div>
          <p className="small offer-last"><strong>ShopFlow Sales:</strong> “{offer.last_message}”</p>
        </div>
        <span className={`pc-pill ${tone}`}><Icon size={14} aria-hidden="true" />{label}{offer.state === "deal" && ` until ${time(offer.expires_at)}`}</span>
      </div>
      <div className="row" style={{ gap: 8, marginTop: 12 }}>
        {offer.can_continue && <Link className="btn primary sm" to={`/products/${offer.product_id}?offer=1`}><MessageCircle size={15} />Continue bargaining</Link>}
        {offer.state === "deal" && (offer.in_cart
          ? <Link className="btn primary sm" to="/cart"><ShoppingCart size={15} />In your cart</Link>
          : <Link className="btn primary sm" to={`/products/${offer.product_id}?offer=1`}><ShoppingCart size={15} />Add to cart at {rupees(offer.deal_price)}</Link>)}
        {offer.can_reopen && (
          <button className="btn sm" disabled={busy} onClick={() => act("reopen", undefined, () => "Back to bargaining. The deal was taken out of your cart.")}>
            <RefreshCw size={15} />Change my offer
          </button>
        )}
        {offer.can_drop && (
          <button className="btn sm ghost danger" disabled={busy} onClick={() => act("drop", undefined, () => (offer.state === "negotiating" ? "Chat ended" : "Deal dropped"))}>
            <Trash2 size={15} />{offer.state === "negotiating" ? "End chat" : "Drop deal"}
          </button>
        )}
        {offer.state === "ordered" && offer.order_id && <Link className="btn sm" to="/orders">Order #{offer.order_id}</Link>}
        {["ended", "expired"].includes(offer.state) && !offer.can_reopen && <Link className="btn sm" to={`/products/${offer.product_id}?offer=1`}><Handshake size={15} />Start a new offer</Link>}
        <button className="btn sm ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <ChevronDown size={15} style={{ transform: open ? "rotate(180deg)" : "none" }} />{open ? "Hide chat" : "Show chat"}
        </button>
      </div>
      {open && (
        <OfferThread messages={offer.messages} maxHeight={320} />
      )}
    </li>
  );
}

/** My offers: every "Make an offer" chat and deal, with what you can do next. */
export default function MyOffers() {
  const [data, setData] = useState(null);
  const [rules, setRules] = useState({ min_price: 500, deal_minutes: 30 });
  useEffect(() => { getOfferRules().then(setRules); }, []);
  const [error, setError] = useState("");
  const load = () => api("/api/ai/offers/").then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (error) return <p className="error"><CircleAlert size={18} />{error}</p>;
  if (!data) return <div className="skeleton" style={{ height: 320 }} />;
  const s = data.summary;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>My offers</h1>
        <p>Your bargaining chats with the AI seller and the deals they ended in. A deal is for one unit and is held for {rules.deal_minutes} minutes.</p>
      </div>
      {data.offers.length === 0 ? (
        <EmptyState icon={Handshake} title="No offers yet">
          <p>Open any product from {rupees(rules.min_price)} up and press “Make an offer” to bargain.</p>
          <Link to="/" className="btn primary">Start shopping</Link>
        </EmptyState>
      ) : (
        <>
          <div className="kpis offer-kpis">
            <div className="card kpi"><div className="head">Deals held</div><div className="value">{s.deals_held}</div></div>
            <div className="card kpi"><div className="head">Still bargaining</div><div className="value">{s.negotiating}</div></div>
            <div className="card kpi"><div className="head">Deals ordered</div><div className="value">{s.ordered}</div></div>
            <div className="card kpi"><div className="head">Saved on orders</div><div className="value">{rupees(s.saved)}</div></div>
          </div>
          <ul className="offer-list">{data.offers.map((o) => <OfferRow key={o.id} offer={o} onChange={load} />)}</ul>
          <p className="muted small icon-text"><CircleCheck size={14} />Prices are set by the store's rules; the AI seller only does the talking.</p>
        </>
      )}
    </div>
  );
}

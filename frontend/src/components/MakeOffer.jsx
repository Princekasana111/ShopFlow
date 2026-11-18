import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BadgeIndianRupee, CircleAlert, Handshake, RefreshCw, Send, ShoppingCart, Trash2, X } from "lucide-react";
import { api, notifyCartChanged, rupees } from "../api.js";
import OfferThread from "./OfferThread.jsx";
import { toast } from "./ui.jsx";

const time = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });

/** "Make an offer": bargain with the AI seller. Code sets every price; the AI only writes the words. */
export default function MakeOffer({ product, size, needsSize, onClose }) {
  const [offer, setOffer] = useState(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef(null);

  useEffect(() => {
    setOffer(null);
    setNotice("");
    setError("");
    api("/api/ai/offers/", { method: "POST", body: { product_id: product.id } })
      .then((r) => (r.negotiable ? setOffer(r.offer) : setNotice(r.message)))
      .catch((e) => setError(e.message));
  }, [product.id]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [offer?.messages.length]);

  const send = async (message) => {
    const body = (message ?? text).trim();
    if (!body || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await api(`/api/ai/offers/${offer.id}/messages/`, { method: "POST", body: { message: body } });
      setOffer(r.offer);
      setText("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const change = async (path, done) => {
    setBusy(true);
    setError("");
    try {
      const r = await api(`/api/ai/offers/${offer.id}/${path}/`, { method: "POST" });
      setOffer(r.offer);
      notifyCartChanged();
      toast(done);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const accept = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api(`/api/ai/offers/${offer.id}/accept/`, { method: "POST", body: { size: size || "", add_to_cart: true } });
      setOffer({ ...r.offer, in_cart: true });
      notifyCartChanged();
      toast(`Added to your cart at ${rupees(r.offer.deal_price)}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const counter = offer?.counter_price;
  const yourLast = [...(offer?.messages || [])].reverse().find((m) => m.role === "shopper" && m.price)?.price;
  const suggestion = Math.round((Number(product.price) * 0.9) / 10) * 10;
  return (
    <section className="card offer-panel" aria-label="Make an offer">
      <div className="row spread">
        <div className="card-title" style={{ margin: 0 }}>
          <span className="icon-tile"><Handshake size={19} /></span>
          <div>
            <h2>Make an offer</h2>
            <span className="muted small">Bargain with our AI seller. Prices come from the store's rules; the AI only does the talking.</span>
          </div>
        </div>
        <button className="btn sm ghost" onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>

      {notice && <p className="notice" style={{ marginTop: 14 }}><BadgeIndianRupee size={18} />{notice}</p>}
      {!offer && !notice && !error && <div className="skeleton" style={{ height: 120, marginTop: 14 }} />}

      {offer && (
        <>
          <OfferThread messages={offer.messages} listRef={listRef} />

          {offer.deal_valid ? (
            <div className="offer-deal">
              <div>
                <strong>Deal agreed: {rupees(offer.deal_price)}</strong>
                <span className="muted small"> · was {rupees(offer.list_price)} · held until {time(offer.expires_at)}</span>
              </div>
              {offer.in_cart
                ? <Link to="/cart" className="btn primary"><ShoppingCart size={16} />In your cart</Link>
                : <button className="btn primary" onClick={accept} disabled={busy || needsSize}>{needsSize ? "Choose a size first" : <><ShoppingCart size={16} />Add to cart at {rupees(offer.deal_price)}</>}</button>}
              <div className="row" style={{ gap: 6, flexBasis: "100%" }}>
                <button className="btn sm ghost" disabled={busy} onClick={() => change("reopen", "Back to bargaining. The deal was taken out of your cart.")}><RefreshCw size={14} />Change my offer</button>
                <button className="btn sm ghost danger" disabled={busy} onClick={() => change("drop", "Deal dropped")}><Trash2 size={14} />Drop deal</button>
                <Link className="btn sm ghost" to="/my-offers">All my offers</Link>
              </div>
            </div>
          ) : offer.status === "OPEN" ? (
            <>
              {counter && (
                <div className="offer-deal">
                  <span>
                    Counter-offer from ShopFlow Sales: <strong>{rupees(counter)}</strong>
                    <span className="muted small"> · {yourLast ? `your last offer ${rupees(yourLast)} · ` : ""}list {rupees(offer.list_price)}</span>
                  </span>
                  <button className="btn primary" onClick={accept} disabled={busy || needsSize}>{needsSize ? "Choose a size first" : <><Handshake size={16} />Accept {rupees(counter)}</>}</button>
                </div>
              )}
              <form className="offer-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
                <input className="input" value={text} onChange={(e) => setText(e.target.value)} maxLength={500} disabled={busy}
                  placeholder={`Name your price, e.g. ${rupees(suggestion)}`} aria-label="Your offer" />
                <button className="btn primary" disabled={busy || !text.trim()}><Send size={16} />{busy ? "…" : "Send"}</button>
              </form>
              <div className="row" style={{ gap: 8, marginTop: 10 }}>
                <button className="chip" disabled={busy} onClick={() => send(`How about ${rupees(suggestion)}?`)}>How about {rupees(suggestion)}?</button>
                <button className="chip" disabled={busy} onClick={() => send("Can you do any better?")}>Can you do any better?</button>
                <button className="chip" disabled={busy} onClick={() => send("That's too expensive for me.")}>Too expensive</button>
              </div>
              <p className="muted small" style={{ margin: "10px 0 0" }}>{offer.turns_left} message{offer.turns_left === 1 ? "" : "s"} left · a deal is for one unit and is held for {offer.deal_minutes ?? 30} minutes</p>
            </>
          ) : (
            <p className="muted small" style={{ marginTop: 12 }}>{offer.status === "USED" ? "You used this deal in an order." : "This chat has ended. You can start a new one later."}</p>
          )}
        </>
      )}
      {error && <p className="error" style={{ marginTop: 12 }}><CircleAlert size={18} />{error}</p>}
    </section>
  );
}

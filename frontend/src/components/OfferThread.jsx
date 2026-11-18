import { Store } from "lucide-react";
import { rupees } from "../api.js";
import { useAuth } from "../auth.jsx";

// What a price in a message means, by who sent it and what they did.
const PRICE_LABEL = {
  shopper: { offer: "Your offer", accept: "You accepted" },
  seller: {
    open: "List price", counter: "Counter-offer", final: "Final offer", hold_final: "Final offer", deal: "Deal agreed",
    lowball: "Current price", answer: "Current price", blocked: "Price unchanged",
  },
};
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }) : "");

/** A "Make an offer" conversation: every message says who sent it, when, and what its price means. */
export default function OfferThread({ messages, listRef, maxHeight }) {
  const { user } = useAuth();
  const initials = (user?.username || "you").slice(0, 2).toUpperCase();
  return (
    <div className="offer-chat" ref={listRef} aria-live="polite" style={maxHeight ? { maxHeight } : undefined}>
      {messages.map((m, i) => {
        const seller = m.role === "seller";
        const label = m.price && PRICE_LABEL[m.role]?.[m.action];
        return (
          <div key={i} className={`offer-msg ${m.role}`}>
            <span className={`who-avatar ${m.role}`} aria-hidden="true">{seller ? <Store size={15} /> : initials}</span>
            <div className="offer-body">
              <div className="offer-meta">
                <strong>{seller ? "ShopFlow Sales" : "You"}</strong>
                {seller && <span className="role-badge">AI seller</span>}
                {m.at && <span className="muted">{clock(m.at)}</span>}
              </div>
              <div className="bubble">{m.text}</div>
              {label && <span className={`offer-price ${m.role} ${m.action}`}>{label}: {rupees(m.price)}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

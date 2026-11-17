import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bot, Check, FileText, LifeBuoy, LoaderCircle, Package, RotateCcw, Search, Send, ShoppingCart, Sparkles,
  TriangleAlert, X,
} from "lucide-react";
import { notifyCartChanged, rupees, streamChat } from "../api.js";
import { useAuth } from "../auth.jsx";
import Markdown from "./Markdown.jsx";
import ProductArt from "./ProductArt.jsx";
import { toast } from "./ui.jsx";

const SUGGESTIONS = [
  { icon: Search, text: "Waterproof running shoes under ₹5,000" },
  { icon: ShoppingCart, text: "Add the cheapest yoga mat to my cart" },
  { icon: Package, text: "Where is my order?" },
  { icon: LifeBuoy, text: "Can I return earbuds after a week?" },
];

const TOOLS = {
  search_products: [Search, "Searching the catalog"],
  get_product_details: [FileText, "Reading product details"],
  add_to_cart: [ShoppingCart, "Updating your cart"],
  view_cart: [ShoppingCart, "Checking your cart"],
  list_my_orders: [Package, "Looking up your orders"],
  get_order_status: [Package, "Tracking your order"],
  search_store_policies: [LifeBuoy, "Searching the help center"],
};

function StepPill({ step }) {
  const [Icon, label] = TOOLS[step.name] || [Sparkles, step.name];
  return (
    <span className={`step-pill ${step.done ? (step.error ? "fail" : "done") : ""}`} title={step.summary || label}>
      <Icon size={13} />
      {step.done && step.summary ? step.summary : label}
      <span className="state">
        {!step.done ? <LoaderCircle size={13} className="spin" /> : step.error ? <TriangleAlert size={13} /> : <Check size={13} />}
      </span>
    </span>
  );
}

export default function AssistantPanel({ llm }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [degraded, setDegraded] = useState(false);
  const scroller = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [messages, open]);
  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => { if (llm?.degraded) setDegraded(true); }, [llm]);

  const update = (fn) => setMessages((prev) => {
    const copy = [...prev];
    copy[copy.length - 1] = fn({ ...copy[copy.length - 1] });
    return copy;
  });

  const send = async (text) => {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", text: message }, { role: "assistant", text: "", steps: [], products: [], sources: [], pending: true }]);
    abortRef.current = new AbortController();
    try {
      await streamChat({
        message,
        sessionId,
        signal: abortRef.current.signal,
        onEvent: (event, data) => {
          if (event === "session") {
            setSessionId(data.session_id);
            if (data.degraded) setDegraded(true);
          } else if (event === "text") update((m) => ({ ...m, text: m.text + data.delta }));
          else if (event === "tool_start") update((m) => ({ ...m, steps: [...m.steps, { id: data.id, name: data.name, done: false }] }));
          else if (event === "tool_result") {
            update((m) => ({ ...m, steps: m.steps.map((s) => (s.id === data.id ? { ...s, done: true, summary: data.summary, error: data.is_error } : s)) }));
            if (data.cart_updated) {
              notifyCartChanged();
              toast("Cart updated");
            }
          } else if (event === "refusal" || event === "error") update((m) => ({ ...m, text: m.text ? `${m.text}\n\n${data.message}` : data.message, error: true }));
          else if (event === "done") {
            if (llm?.is_live && data.answered_by === "offline") setDegraded(true);
            update((m) => ({ ...m, pending: false, products: data.products || [], sources: data.sources || [], grounding: data.grounding }));
          }
        },
      });
    } catch (err) {
      if (err.name !== "AbortError") update((m) => ({ ...m, text: err.message || "Something went wrong.", error: true }));
    } finally {
      update((m) => ({ ...m, pending: false }));
      setBusy(false);
    }
  };

  const reset = () => {
    abortRef.current?.abort();
    setMessages([]);
    setSessionId(null);
  };

  if (!open) {
    return <button className="fab" onClick={() => setOpen(true)}><Sparkles size={18} /> Ask AI</button>;
  }

  const live = llm?.is_live && !degraded;
  return (
    <section className="assistant-panel" aria-label="Shopping assistant">
      <header className="ap-head">
        <span className="bot"><Bot size={20} /></span>
        <div className="title">
          <strong>ShopFlow Assistant</strong>
          <span>
            <span className={`dot ${degraded ? "warn" : live ? "" : "off"}`} />
            {degraded ? "Claude unavailable · offline mode" : live ? `Claude · ${llm.model}` : "Offline demo mode"}
          </span>
        </div>
        <button onClick={reset} title="New chat" aria-label="Start a new chat"><RotateCcw size={16} /></button>
        <button onClick={() => setOpen(false)} title="Close" aria-label="Close assistant"><X size={17} /></button>
      </header>

      {!user ? (
        <div className="messages">
          <div className="welcome">
            <h3>Sign in to chat</h3>
            <p className="muted" style={{ margin: 0 }}>The assistant can search products, manage your cart and track your orders.</p>
            <Link className="btn primary" to="/login" onClick={() => setOpen(false)}>Sign in</Link>
            <p className="muted small" style={{ margin: 0 }}>Demo login: demo / demo12345</p>
          </div>
        </div>
      ) : (
        <>
          <div className="messages" ref={scroller}>
            {messages.length === 0 && (
              <div className="welcome">
                <div>
                  <h3>Hi {user.username}, what are you shopping for?</h3>
                  <p className="muted small" style={{ margin: "6px 0 0" }}>I can find products, add them to your cart, track orders and answer policy questions. You stay in control of checkout.</p>
                </div>
                <div className="suggest-grid">
                  {SUGGESTIONS.map(({ icon: Icon, text }) => (
                    <button key={text} className="suggest" onClick={() => send(text)}><Icon size={18} />{text}</button>
                  ))}
                </div>
                {!live && (
                  <p className="notice small">
                    {degraded ? "Claude couldn't be reached, so answers come from the offline rule-based mode." : "Offline demo mode: answers come from a rule-based stand-in. Add ANTHROPIC_API_KEY on the server to use Claude."}
                  </p>
                )}
              </div>
            )}
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="msg-user">{m.text}</div>
              ) : (
                <div key={i} className="msg-bot">
                  <span className="bot-avatar"><Sparkles size={15} /></span>
                  <div className="content">
                    {m.steps?.length > 0 && <div className="steps">{m.steps.map((s) => <StepPill key={s.id} step={s} />)}</div>}
                    {(m.text || m.pending) && (
                      <div className={`bubble ${m.error ? "err" : ""}`}>
                        {m.text ? <Markdown text={m.text} /> : <span className="typing" aria-label="Thinking"><span /><span /><span /></span>}
                      </div>
                    )}
                    {m.products?.length > 0 && (
                      <div className="mini-products">
                        {m.products.map((p) => (
                          <Link key={p.id} to={`/products/${p.id}`} className="mini">
                            <ProductArt product={p} size="sm" />
                            <span>
                              <span className="mn">{p.name}</span>
                              <span className="mp">{rupees(p.price)}{p.stock === 0 ? " · sold out" : ""}</span>
                            </span>
                          </Link>
                        ))}
                      </div>
                    )}
                    {m.sources?.length > 0 && (
                      <div className="sources">{m.sources.map((s, j) => <span key={j} className="source-chip" title={s.excerpt}><FileText size={12} />{s.doc_title} › {s.section}</span>)}</div>
                    )}
                    {m.grounding?.ungrounded_prices?.length > 0 && (
                      <p className="warn-note"><TriangleAlert size={15} />Some prices in this answer could not be verified against the catalog.</p>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
          <div className="composer">
            <form onSubmit={(e) => { e.preventDefault(); send(); }}>
              <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about products, your cart or orders…" maxLength={1000} disabled={busy} aria-label="Message" />
              <button className="send" disabled={busy || !input.trim()} aria-label="Send"><Send size={17} /></button>
            </form>
            <div className="hint">The assistant can't place orders or take payments.</div>
          </div>
        </>
      )}
    </section>
  );
}

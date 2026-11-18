import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  AlignLeft, Archive, ChevronRight, CircleAlert, CircleCheck, CircleHelp, Handshake, ListChecks, MessageSquareQuote, Minus, PackageCheck,
  PackageX, Puzzle, RotateCcw, ScanSearch, Send, ShieldCheck, ShoppingCart, Sparkles, Star, ThumbsDown, ThumbsUp, Truck, X,
} from "lucide-react";
import { aiBadge, aiBy, getOfferRules } from "../ai.js";
import { api, notifyCartChanged, rupees } from "../api.js";
import { useAuth } from "../auth.jsx";
import ProductArt, { categoryOf } from "../components/ProductArt.jsx";
import ProductCard from "../components/ProductCard.jsx";
import MakeOffer from "../components/MakeOffer.jsx";
import PurchaseCheck from "../components/PurchaseCheck.jsx";
import { FitAdvice, ListingCheck } from "../components/ReviewSignals.jsx";
import { Rating, Stars, Stepper, toast } from "../components/ui.jsx";
import { preferredSize, productSizes, usePreferences } from "../sizes.js";

const SENTIMENT = {
  positive: [ThumbsUp, "Mostly positive"],
  mixed: [Minus, "Mixed"],
  negative: [ThumbsDown, "Mostly negative"],
};

function ReviewInsights({ productId, reloadKey }) {
  const [insights, setInsights] = useState(null);
  useEffect(() => {
    setInsights(null);
    api(`/api/ai/products/${productId}/review-insights/`).then(setInsights).catch(() => setInsights({ available: false }));
  }, [productId, reloadKey]);
  if (!insights) return <div className="skeleton" style={{ height: 180 }} />;
  if (!insights.available) return null;
  const [SentIcon, sentLabel] = SENTIMENT[insights.sentiment] || SENTIMENT.mixed;
  return (
    <section className="card insights">
      <div className="row spread">
        <div className="card-title" style={{ margin: 0 }}>
          <span className="icon-tile"><Sparkles size={19} /></span>
          <div>
            <h2>What customers say</h2>
            <span className="muted small">AI summary of {insights.review_count} reviews</span>
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <span className="badge"><SentIcon size={13} />{sentLabel}</span>
          <span className="badge brand" title={insights.model}>{aiBadge(insights.provider)}{insights.cached ? " · cached" : ""}</span>
        </div>
      </div>
      <p style={{ marginTop: 14 }}>{insights.summary}</p>
      <div className="pros-cons">
        <div className="col pro">
          <h3><ThumbsUp size={16} />Liked</h3>
          <ul>{insights.pros.map((p, i) => <li key={i}><CircleCheck size={15} />{p}</li>)}</ul>
        </div>
        <div className="col con">
          <h3><ThumbsDown size={16} />Disliked</h3>
          {insights.cons.length ? <ul>{insights.cons.map((c, i) => <li key={i}><X size={15} />{c}</li>)}</ul> : <p className="muted small" style={{ margin: "8px 0 0" }}>Nothing notable.</p>}
        </div>
      </div>
    </section>
  );
}

const QUESTIONS = {
  electronics: ["How long does the battery last?", "Is it good for calls?", "Is it waterproof?"],
  footwear: ["Do these run small?", "Are they comfortable for long walks?", "Are they waterproof?"],
  clothing: ["Is it warm enough for winter?", "How does it fit?", "Is it waterproof?"],
  "home-kitchen": ["Is it easy to clean?", "Is it durable?", "Does it work on induction?"],
  books: ["Is it good for beginners?", "Who is this book for?", "Does it have exercises?"],
  "sports-fitness": ["Is it good for beginners?", "Is it durable?", "Does it slip?"],
};
const CITE_ICON = { spec: ListChecks, description: AlignLeft, review: MessageSquareQuote };
const FIT_LABEL = { small: "Runs small", true: "True to size", large: "Runs large" };
const EMPTY_REVIEW = { rating: 5, title: "", body: "", size_bought: "", fit: "" };

function AskProduct({ product }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => { setResult(null); setQuestion(""); }, [product.id]);
  const ask = async (q) => {
    const text = (q ?? question).trim();
    if (text.length < 3) return;
    setQuestion(text);
    setLoading(true);
    try {
      setResult(await api(`/api/ai/products/${product.id}/ask/`, { method: "POST", body: { question: text } }));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  };
  return (
    <section className="card qa-box">
      <div className="card-title">
        <span className="icon-tile"><CircleHelp size={19} /></span>
        <div><h2>Ask about this product</h2><span className="muted small">Answered only from this product's specs and customer reviews, with sources.</span></div>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="row" style={{ gap: 8 }}>
        <input className="input" style={{ flex: "1 1 260px" }} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Is it good for long flights?" maxLength={300} aria-label="Question about this product" />
        <button className="btn primary" disabled={loading || question.trim().length < 3}><Send size={16} />{loading ? "Checking…" : "Ask"}</button>
      </form>
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        {(QUESTIONS[categoryOf(product)] || []).map((q) => <button key={q} className="chip" onClick={() => ask(q)}>{q}</button>)}
      </div>
      {result && !loading && (
        <div className={`answer ${result.answerable ? "" : "unanswered"}`}>
          <div className="row spread" style={{ marginBottom: 6 }}>
            <strong className="icon-text">{result.answerable ? <Sparkles size={16} /> : <CircleHelp size={16} />}{result.answerable ? "Answer" : "Not covered"}</strong>
            {!result.blocked && <span className="badge brand" title={result.model}>{aiBadge(result.provider)}</span>}
          </div>
          <p style={{ margin: 0 }}>{result.answer}</p>
          {result.citations.length > 0 && (
            <div className="cite-list">
              {result.citations.map((c) => {
                const Icon = CITE_ICON[c.kind] || AlignLeft;
                return <div key={c.n} className="cite"><span className="n">{c.n}</span><span><strong className="icon-text"><Icon size={13} />{c.label}</strong> · {c.text}</span></div>;
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function CompleteTheKit({ productId }) {
  const [kit, setKit] = useState(null);
  useEffect(() => {
    setKit(null);
    api(`/api/ai/products/${productId}/complete-the-kit/`).then(setKit).catch(() => setKit({ items: [] }));
  }, [productId]);
  if (!kit || kit.items.length === 0) return null;
  return (
    <section>
      <div className="toolbar">
        <h2 className="icon-text"><Puzzle size={20} />Complete the kit</h2>
        <span className="muted small">Things that go with it, planned by {aiBy(kit.provider)}</span>
      </div>
      <div className="kit">
        {kit.items.map((item) => (
          <Link key={item.product.id} to={`/products/${item.product.id}`} className="card kit-card">
            <span className="badge brand" style={{ alignSelf: "flex-start" }}>{item.label}</span>
            <div className="row-top">
              <ProductArt product={item.product} size="sm" />
              <span><strong>{item.product.name}</strong><br /><span className="price" style={{ fontSize: "1rem" }}>{rupees(item.product.price)}</span></span>
            </div>
            <span className="muted small">{item.reason}</span>
            {item.owned && <span className="badge" style={{ alignSelf: "flex-start" }}><Archive size={12} />You have {item.owned.name}</span>}
          </Link>
        ))}
      </div>
    </section>
  );
}

function StarPicker({ value, onChange }) {
  return (
    <span className="star-picker" role="radiogroup" aria-label="Rating">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" className={n <= value ? "on" : ""} onClick={() => onChange(n)} role="radio" aria-checked={n === value} aria-label={`${n} star${n > 1 ? "s" : ""}`}>
          <Star size={24} fill={n <= value ? "currentColor" : "none"} />
        </button>
      ))}
    </span>
  );
}

function StockLine({ stock }) {
  if (stock === 0) return <span className="stock out"><PackageX size={16} />Out of stock</span>;
  if (stock <= 12) return <span className="stock low"><CircleAlert size={16} />Only {stock} left</span>;
  return <span className="stock in"><PackageCheck size={16} />In stock</span>;
}

export default function ProductDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const { user } = useAuth();
  const [product, setProduct] = useState(null);
  const [similar, setSimilar] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [qty, setQty] = useState(1);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [review, setReview] = useState(EMPTY_REVIEW);
  const [reloadKey, setReloadKey] = useState(0);
  const [size, setSize] = useState("");
  const [checking, setChecking] = useState(false);
  const [bargaining, setBargaining] = useState(false);
  const [offerMin, setOfferMin] = useState(null);
  useEffect(() => { getOfferRules().then((r) => setOfferMin(r.min_price)); }, []);
  const { prefs } = usePreferences(user);
  const sizes = productSizes(product);
  const mySize = preferredSize(prefs, sizes);

  useEffect(() => {
    setSize(mySize && sizes.includes(mySize) ? mySize : "");
    setChecking(false);
    setBargaining(params.get("offer") === "1"); // "Continue bargaining" from My offers
  }, [product?.id, mySize]);

  useEffect(() => {
    setError("");
    setQty(1);
    api(`/api/products/${id}/`).then(setProduct).catch((e) => setError(e.message));
    api(`/api/ai/products/${id}/similar/`).then(setSimilar).catch(() => setSimilar([]));
    api(`/api/products/${id}/reviews/`).then(setReviews).catch(() => setReviews([]));
    window.scrollTo({ top: 0 });
  }, [id, reloadKey]);

  const addToCart = async () => {
    setAdding(true);
    try {
      await api("/api/cart/", { method: "POST", body: { product_id: Number(id), quantity: qty, ...(size ? { size } : {}) } });
      notifyCartChanged();
      toast(`Added ${qty} × ${product.name}${size ? ` (${size})` : ""} to your cart`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAdding(false);
    }
  };

  const submitReview = async (e) => {
    e.preventDefault();
    try {
      const saved = await api(`/api/products/${id}/reviews/`, { method: "POST", body: review });
      setReview(EMPTY_REVIEW);
      toast(saved.is_flagged ? "Your review was held for moderation" : "Thanks for your review!", saved.is_flagged ? "error" : "success");
      setReloadKey((k) => k + 1);
    } catch (err) {
      toast(err.message, "error");
    }
  };

  if (error && !product) return <p className="error"><CircleAlert size={18} />{error}</p>;
  if (!product) return <div className="detail"><div className="skeleton" style={{ aspectRatio: "4 / 3" }} /><div className="skeleton" style={{ height: 380 }} /></div>;

  const electronics = categoryOf(product) === "electronics";
  // Mirrors knowledge/returns.md: socks and innerwear cannot be returned.
  const returnable = !/socks|innerwear/i.test(product.name);
  const dist = [5, 4, 3, 2, 1].map((n) => ({ n, count: reviews.filter((r) => r.rating === n).length }));
  const maxDist = Math.max(1, ...dist.map((d) => d.count));

  return (
    <div className="stack">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Shop</Link><ChevronRight size={14} />
        <Link to={`/?category=${product.category.slug}`}>{product.category.name}</Link><ChevronRight size={14} />
        <span>{product.name}</span>
      </nav>

      <div className="detail">
        <ProductArt product={product} />
        <div>
          <span className="badge brand">{product.brand}</span>
          <h1>{product.name}</h1>
          <Rating value={product.avg_rating} count={product.review_count} />
          <div className="price-block">
            <span className="price">{rupees(product.price)}</span>
            <StockLine stock={product.stock} />
          </div>
          <p style={{ color: "var(--ink-2)" }}>{product.description}</p>

          {Object.keys(product.attributes || {}).some((k) => k !== "sizes") && (
            <div className="specs">
              {Object.entries(product.attributes).filter(([k]) => k !== "sizes").map(([k, v]) => (
                <div key={k} className="spec"><div className="k">{k.replaceAll("_", " ")}</div><div className="v">{v}</div></div>
              ))}
            </div>
          )}

          {sizes.length > 0 && (
            <div className="size-picker">
              <div className="row spread">
                <strong className="small">Size{size ? `: ${size}` : ""}</strong>
                {user && (mySize
                  ? <span className="muted small">{sizes.includes(mySize) ? `Your saved size is ${mySize}` : `Not made in your size (${mySize})`}</span>
                  : <Link to="/my-stuff" className="small">Save your sizes</Link>)}
              </div>
              <div className="size-options" role="radiogroup" aria-label="Size">
                {sizes.map((s) => (
                  <button key={s} type="button" role="radio" aria-checked={size === s} className={`size-option ${size === s ? "active" : ""} ${s === mySize ? "mine" : ""}`} onClick={() => setSize(s)}>{s}</button>
                ))}
              </div>
              <FitAdvice productId={product.id} size={size} onChoose={setSize} reloadKey={reloadKey} />
            </div>
          )}

          {product.stock > 0 ? (
            <div className="buy-row">
              <Stepper value={qty} max={Math.min(product.stock, 10)} onChange={setQty} />
              {user ? (
                <>
                  <button className="btn primary lg" onClick={addToCart} disabled={adding || (sizes.length > 0 && !size)} title={sizes.length > 0 && !size ? "Choose a size first" : undefined}>
                    <ShoppingCart size={18} />{adding ? "Adding…" : sizes.length > 0 && !size ? "Choose a size" : "Add to cart"}
                  </button>
                  <button className="btn lg" onClick={() => setChecking(true)}><ScanSearch size={18} />Check before buying</button>
                  {offerMin != null && Number(product.price) >= offerMin && <button className="btn lg" onClick={() => setBargaining(true)}><Handshake size={18} />Make an offer</button>}
                </>
              ) : (
                <>
                  <Link className="btn primary lg" to="/login" state={{ from: `/products/${product.id}` }}><ShoppingCart size={18} />Log in to buy</Link>
                  <span className="muted small">Log in to make an offer or check it before you buy.</span>
                </>
              )}
            </div>
          ) : (
            <p className="muted">This product is currently unavailable.</p>
          )}

          <div className="perks">
            <div className="perk"><Truck size={18} />Free delivery on orders of ₹999+</div>
            <div className="perk"><RotateCcw size={18} />{!returnable ? "Not returnable (hygiene)" : electronics ? "7-day replacement" : "10-day easy returns"}</div>
            {electronics && <div className="perk"><ShieldCheck size={18} />Manufacturer warranty</div>}
          </div>
        </div>
      </div>

      {bargaining && user && <MakeOffer product={product} size={size} needsSize={sizes.length > 0 && !size} onClose={() => setBargaining(false)} />}

      {checking && user && <PurchaseCheck auto productId={product.id} size={size} title="Before you buy this" onSize={(_, s) => setSize(s)} />}

      <ListingCheck productId={product.id} reloadKey={reloadKey} />

      <AskProduct product={product} />

      <ReviewInsights productId={id} reloadKey={reloadKey} />

      <CompleteTheKit productId={id} />

      {similar.length > 0 && (
        <section>
          <div className="toolbar">
            <h2>You might also like</h2>
            <span className="muted small">Similar products, matched by what they're for</span>
          </div>
          <div className="grid">{similar.map((p) => <ProductCard key={p.id} product={p} />)}</div>
        </section>
      )}

      <section className="card">
        <h2>Customer reviews</h2>
        <div className="reviews-layout" style={{ marginTop: 14 }}>
          <div>
            <div className="row" style={{ alignItems: "flex-end", gap: 10 }}>
              <span className="rating-big">{product.avg_rating ? Number(product.avg_rating).toFixed(1) : "–"}</span>
              <span className="muted small">out of 5</span>
            </div>
            <div style={{ marginTop: 6 }}><Stars value={product.avg_rating || 0} size={18} /></div>
            <div className="dist">
              {dist.map((d) => (
                <div key={d.n} className="dist-row">
                  <span>{d.n} ★</span>
                  <div className="meter" role="img" aria-label={`${d.count} reviews with ${d.n} stars`}><div style={{ width: `${(d.count / maxDist) * 100}%` }} /></div>
                  <span>{d.count}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            {reviews.length === 0 && <p className="muted">No reviews yet. Be the first to share your thoughts.</p>}
            {reviews.map((r) => (
              <div key={r.id} className="review">
                <span className="avatar">{r.username.slice(0, 2).toUpperCase()}</span>
                <div>
                  <div className="row" style={{ gap: 8 }}><Stars value={r.rating} size={13} /><strong>{r.title}</strong></div>
                  <p style={{ margin: "6px 0 4px" }}>{r.body}</p>
                  {(r.size_bought || r.fit) && (
                    <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                      {r.size_bought && <span className="badge">Bought {r.size_bought}</span>}
                      {r.fit && <span className="badge">{FIT_LABEL[r.fit]}</span>}
                    </div>
                  )}
                  <span className="muted small">{r.username} · {new Date(r.created_at).toLocaleDateString("en-IN")}</span>
                </div>
              </div>
            ))}
            {user && (
              <form onSubmit={submitReview} className="card flat" style={{ marginTop: 16, background: "var(--surface-2)" }}>
                <h3>Write a review</h3>
                <StarPicker value={review.rating} onChange={(rating) => setReview({ ...review, rating })} />
                <label className="field" style={{ marginTop: 10 }}>Title (optional)
                  <input className="input" placeholder="Sum it up in a few words" maxLength={120} value={review.title} onChange={(e) => setReview({ ...review, title: e.target.value })} />
                </label>
                <label className="field">Your review
                  <textarea className="input" rows={3} required placeholder="What did you like or dislike?" value={review.body} onChange={(e) => setReview({ ...review, body: e.target.value })} />
                </label>
                {sizes.length > 0 && (
                  <div className="review-fit">
                    <span className="small" style={{ fontWeight: 600, color: "var(--ink-2)" }}>Size and fit (optional)</span>
                    <select className="input size-select" value={review.size_bought} onChange={(e) => setReview({ ...review, size_bought: e.target.value })} aria-label="Size you bought">
                      <option value="">Size you bought</option>
                      {sizes.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <div className="segmented" role="radiogroup" aria-label="How did it fit?">
                      {Object.entries(FIT_LABEL).map(([k, label]) => (
                        <button key={k} type="button" role="radio" aria-checked={review.fit === k} className={review.fit === k ? "active" : ""}
                          onClick={() => setReview({ ...review, fit: review.fit === k ? "" : k })}>{label}</button>
                      ))}
                    </div>
                  </div>
                )}
                <button className="btn primary" style={{ marginTop: 10 }}>Submit review</button>
              </form>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

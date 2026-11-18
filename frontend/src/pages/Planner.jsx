import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Archive, CircleAlert, IndianRupee, ListChecks, Scale, Search, ShoppingCart, Sparkles, TriangleAlert, WandSparkles } from "lucide-react";
import { aiBy } from "../ai.js";
import { api, notifyCartChanged, rupees } from "../api.js";
import { useAuth } from "../auth.jsx";
import ProductArt from "../components/ProductArt.jsx";
import { Rating, toast } from "../components/ui.jsx";

const EXAMPLES = [
  "Monsoon trek in Himachal, budget ₹8,000",
  "Home office setup under 20k",
  "I just moved into a new flat and want to start cooking, under 4000",
  "Gift for my 7 year old nephew who loves space, max 1500",
];

export default function Planner() {
  const { user } = useAuth();
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState("");
  const [result, setResult] = useState(null);
  const [picks, setPicks] = useState({});
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [skipOwned, setSkipOwned] = useState(true);

  const plan = async (text) => {
    const g = (text ?? goal).trim();
    if (g.length < 3) return;
    setGoal(g);
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/ai/planner/", { method: "POST", body: { goal: g, budget: budget ? Number(budget) : null, skip_owned: skipOwned } });
      setResult(data);
      setPicks(Object.fromEntries(data.items.map((item, i) => [i, item.product])));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const total = useMemo(() => Object.values(picks).reduce((sum, p) => sum + Number(p.price), 0), [picks]);
  const budgetValue = result?.budget ? Number(result.budget) : null;
  const over = budgetValue != null && total > budgetValue;

  const addAll = async () => {
    setAdding(true);
    try {
      for (const product of Object.values(picks)) {
        await api("/api/cart/", { method: "POST", body: { product_id: product.id, quantity: 1 } });
      }
      notifyCartChanged();
      toast(`Added ${Object.keys(picks).length} items to your cart`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAdding(false);
    }
  };

  return (
    <>
      <section className="planner-head">
        <div>
          <span className="badge ai" style={{ marginBottom: 12 }}><WandSparkles size={13} />AI Shopping Planner</span>
          <h1 style={{ fontSize: "clamp(1.7rem, 3.4vw, 2.4rem)" }}>Tell us the plan. We'll build the cart.</h1>
          <p className="muted" style={{ fontSize: "1.02rem" }}>Describe what you're getting ready for and your budget. AI works out what you need, then an optimizer picks the best products that fit, without ever going over budget.</p>
        </div>
        <div className="card how">
          <div className="step"><span className="icon-tile"><ListChecks size={18} /></span><span><strong>1. Plan</strong>AI lists what the goal needs, most important first.</span></div>
          <div className="step"><span className="icon-tile"><Search size={18} /></span><span><strong>2. Find</strong>Hybrid search finds in-stock products that truly fit each need.</span></div>
          <div className="step"><span className="icon-tile"><Scale size={18} /></span><span><strong>3. Optimise</strong>An exact algorithm picks the best combination within your budget.</span></div>
        </div>
      </section>

      <form className="card" onSubmit={(e) => { e.preventDefault(); plan(); }}>
        <label className="field">What are you planning?
          <textarea className="input" rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. Monsoon trek in Himachal next month" maxLength={500} />
        </label>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field" style={{ margin: 0, flex: "0 1 220px" }}>Budget (optional)
            <div className="input-icon"><IndianRupee size={16} /><input className="input" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9]/g, ""))} placeholder="or mention it above" /></div>
          </label>
          <button className="btn primary lg" disabled={loading || goal.trim().length < 3}><Sparkles size={17} />{loading ? "Planning…" : "Plan my cart"}</button>
          {user && (
            <label className="check-inline">
              <input type="checkbox" checked={skipOwned} onChange={(e) => setSkipOwned(e.target.checked)} />
              Skip what I already own
            </label>
          )}
        </div>
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          {EXAMPLES.map((e) => <button type="button" key={e} className="chip" onClick={() => plan(e)}>{e}</button>)}
        </div>
      </form>

      {error && <p className="error" style={{ marginTop: 18 }}><CircleAlert size={18} />{error}</p>}
      {loading && <div className="skeleton" style={{ height: 260, marginTop: 20 }} />}

      {result && !loading && (
        <div className="stack" style={{ marginTop: 22 }}>
          <section className="card insights">
            <div className="row spread">
              <div>
                <h2 style={{ margin: 0 }}>Your plan</h2>
                <span className="muted small">{result.summary}</span>
              </div>
              <span className="badge brand" title={result.planner.model}>Planned by {aiBy(result.planner.provider)} · {result.latency_ms} ms</span>
            </div>
            <div className="budget-bar" style={{ marginTop: 16 }}>
              {budgetValue != null ? (
                <div className="meter" role="img" aria-label={`${rupees(total)} of ${rupees(budgetValue)} budget`}>
                  <div style={{ width: `${Math.min(100, (total / budgetValue) * 100)}%`, background: over ? "var(--critical)" : undefined }} />
                </div>
              ) : <span className="muted small">No budget given: showing the best match for every need.</span>}
              <span><strong className="price">{rupees(total)}</strong>{budgetValue != null && <span className="muted"> of {rupees(budgetValue)}</span>}</span>
            </div>
            {over && <p className="warn-note" style={{ marginTop: 10 }}><TriangleAlert size={15} />Your swaps take the cart over budget.</p>}
          </section>

          {result.items.length > 0 && (
            <div className="bundle">
              {result.items.map((item, i) => {
                const p = picks[i];
                const options = [item.product, ...item.alternatives];
                return (
                  <div key={i} className="card need-card">
                    <div className="row spread">
                      <strong>{item.need.label}</strong>
                      <span className={`badge ${item.need.priority === "must" ? "must" : ""}`}>{item.need.priority === "must" ? "Must-have" : "Nice to have"}</span>
                    </div>
                    <Link to={`/products/${p.id}`} className="pick">
                      <ProductArt product={p} size="sm" />
                      <span>
                        <span className="nm">{p.name}</span><br />
                        <span className="price" style={{ fontSize: "1rem" }}>{rupees(p.price)}</span> <Rating value={p.avg_rating} count={p.review_count} />
                      </span>
                    </Link>
                    <span className="muted small">{item.need.reason}</span>
                    {options.length > 1 && (
                      <select className="input" value={p.id} onChange={(e) => setPicks({ ...picks, [i]: options.find((o) => o.id === Number(e.target.value)) })} aria-label={`Swap ${item.need.label}`}>
                        {options.map((o) => <option key={o.id} value={o.id}>{o.name} · {rupees(o.price)}</option>)}
                      </select>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {result.owned?.length > 0 && (
            <section className="card">
              <h3 className="icon-text"><Archive size={18} />Already covered by what you own</h3>
              <div className="skipped-list">
                {result.owned.map((o, i) => (
                  <div key={i} className="skipped-item">
                    <span><strong>{o.need.label}</strong> <span className="muted">· you have {o.owned.name} ({o.owned.status === "DELIVERED" ? `since ${new Date(o.owned.since).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : "on the way"})</span></span>
                    <Link to="/my-stuff" className="btn sm">My stuff</Link>
                  </div>
                ))}
              </div>
            </section>
          )}

          {result.skipped.length > 0 && (
            <section className="card">
              <h3>Left out</h3>
              <div className="skipped-list">
                {result.skipped.map((s, i) => (
                  <div key={i} className="skipped-item">
                    <span><strong>{s.need.label}</strong> <span className="muted">· {s.reason}</span></span>
                    <Link to={`/?q=${encodeURIComponent(s.need.search_query)}`} className="btn sm"><Search size={14} />Browse</Link>
                  </div>
                ))}
              </div>
            </section>
          )}

          {result.items.length > 0 && (
            <div className="row" style={{ justifyContent: "flex-end" }}>
              {user ? (
                <button className="btn primary lg" onClick={addAll} disabled={adding}><ShoppingCart size={18} />{adding ? "Adding…" : `Add all ${result.items.length} to cart · ${rupees(total)}`}</button>
              ) : (
                <Link className="btn primary lg" to="/login" state={{ from: "/planner" }}><ShoppingCart size={18} />Log in to add these to your cart</Link>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

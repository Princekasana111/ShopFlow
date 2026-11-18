import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CircleAlert, CircleCheck, Filter, IndianRupee, PackageX, SearchCheck, SearchX, Tag, TextSearch, TrendingDown, Wand } from "lucide-react";
import { api, rupees } from "../api.js";
import { CATEGORIES } from "./ProductArt.jsx";

const REASON_ICON = {
  over_budget: IndianRupee, under_minimum: IndianRupee, out_of_stock: PackageX, category: Tag, still_low: TrendingDown,
  ranked_low: TrendingDown, no_match: SearchX, meaning: TextSearch, words: TextSearch, inactive: PackageX,
};

let catalogCache = null;

/** "Why isn't this in my results?": explains, from the search's own numbers, why a product is missing. */
export default function WhyNotHere({ search, onApply }) {
  const [catalog, setCatalog] = useState(catalogCache || []);
  const [name, setName] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (catalogCache) return;
    api("/api/products/", { query: { page_size: 100, ordering: "name" } })
      .then((r) => { catalogCache = r.results.map((p) => ({ id: p.id, name: p.name })); setCatalog(catalogCache); })
      .catch(() => setCatalog([]));
  }, []);
  useEffect(() => setResult(null), [search.q, search.mode, search.category, search.ignore, search.limit]);

  const byName = useMemo(() => Object.fromEntries(catalog.map((p) => [p.name.toLowerCase(), p])), [catalog]);
  const ask = async (e) => {
    e.preventDefault();
    const product = byName[name.trim().toLowerCase()];
    if (!product) {
      setError("Pick a product from the list.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      setResult(await api("/api/ai/search/explain/", { query: { ...search, product_id: product.id } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="card insights why-panel" aria-label="Why isn't it in my results?">
      <div className="card-title">
        <span className="icon-tile"><SearchCheck size={19} /></span>
        <div>
          <h2>Why isn't it here?</h2>
          <span className="muted small">Pick a product you expected. The answer comes from this search's own filters and scores, not from a chatbot.</span>
        </div>
      </div>
      <form className="row" style={{ gap: 8 }} onSubmit={ask}>
        <input className="input" style={{ flex: "1 1 260px" }} list="why-products" value={name} onChange={(e) => setName(e.target.value)}
          placeholder="Start typing a product name" aria-label="Product you expected" />
        <datalist id="why-products">{catalog.map((p) => <option key={p.id} value={p.name} />)}</datalist>
        <button className="btn primary" disabled={loading || !name.trim()}><TextSearch size={16} />{loading ? "Checking…" : "Explain"}</button>
      </form>
      {error && <p className="error" style={{ marginTop: 12 }}><CircleAlert size={18} />{error}</p>}
      {result && (
        <div className="why-result">
          <div className={`pc-verdict ${result.status === "shown" ? "ready" : "review"}`}>
            {result.status === "shown" ? <CircleCheck size={20} /> : <Filter size={20} />}
            <div>
              <strong>{result.headline}</strong>
              <div className="small">Searched for “{result.semantic_query}”{result.filters.category ? ` in ${CATEGORIES[result.filters.category]?.name || result.filters.category}` : ""}{result.filters.max_price ? `, up to ${rupees(result.filters.max_price)}` : ""}{result.filters.min_price ? `, from ${rupees(result.filters.min_price)}` : ""}{result.filters.in_stock_only ? ", in stock only" : ""} · top {result.shown_limit} shown</div>
            </div>
          </div>
          {result.reasons.length > 0 && (
            <ul className="why-reasons">
              {result.reasons.map((r) => {
                const Icon = REASON_ICON[r.code] || CircleAlert;
                return <li key={r.code}><Icon size={16} aria-hidden="true" /><span><strong>{r.title}.</strong> {r.detail}</span></li>;
              })}
            </ul>
          )}
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            {result.fix && (
              <button className="btn primary" onClick={() => onApply(result.fix.params)}>
                <Wand size={16} />{result.fix.label}{result.fix.rank_after ? ` (it would be #${result.fix.rank_after})` : ""}
              </button>
            )}
            <Link className="btn" to={`/products/${result.product_id}`}>Open {result.product}<ArrowRight size={16} /></Link>
          </div>
        </div>
      )}
    </section>
  );
}

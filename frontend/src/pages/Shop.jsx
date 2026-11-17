import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, Camera, CircleAlert, IndianRupee, LayoutGrid, PackageCheck, Search, SearchX, Sparkles, Tag, TriangleAlert, WandSparkles, X } from "lucide-react";
import { api, rupees, upload } from "../api.js";
import ProductArt, { CATEGORIES } from "../components/ProductArt.jsx";
import ProductCard from "../components/ProductCard.jsx";
import { EmptyState, SkeletonGrid } from "../components/ui.jsx";

const EXAMPLES = [
  "something to keep my coffee hot for hours",
  "shoes for rainy season running under 5000",
  "gift for someone learning to code",
  "in stock earbuds under 3k",
];

function SearchForm({ draft, setDraft, mode, onMode, onSubmit, onPhoto }) {
  return (
    <form className="search-box" onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
      <div className="input-icon">
        <Sparkles size={18} />
        <input className="input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Describe what you need, e.g. waterproof shoes for monsoon runs under 5000" aria-label="Search products" />
      </div>
      <select className="input" value={mode} onChange={(e) => onMode(e.target.value)} aria-label="Search mode">
        <option value="hybrid">Hybrid AI</option>
        <option value="vector">Semantic</option>
        <option value="keyword">Keyword</option>
      </select>
      <label className="btn icon-only" title="Search by photo" aria-label="Search by photo">
        <Camera size={18} />
        <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onPhoto(f); }} />
      </label>
      <button className="btn primary"><Search size={17} />Search</button>
    </form>
  );
}

export default function Shop() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const mode = params.get("mode") || "hybrid";
  const category = params.get("category") || "";
  const ordering = params.get("ordering") || "rating";
  const [draft, setDraft] = useState(q);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [photo, setPhoto] = useState(null);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => () => photo?.preview && URL.revokeObjectURL(photo.preview), [photo]);

  const searchByPhoto = async (file) => {
    if (file.size > 5 * 1024 * 1024) {
      setPhoto({ error: "Please choose a photo under 5 MB." });
      return;
    }
    const preview = URL.createObjectURL(file);
    setPhoto({ preview, loading: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
    const form = new FormData();
    form.append("image", file);
    try {
      setPhoto({ preview, ...(await upload("/api/ai/visual-search/", form)) });
    } catch (e) {
      setPhoto({ preview, error: e.message });
    }
  };
  useEffect(() => {
    setLoading(true);
    setError("");
    const request = q
      ? api("/api/ai/search/", { query: { q, mode, category } })
      : api("/api/products/", { query: { category, ordering, page_size: 60 } }).then((r) => ({ results: r.results, count: r.count }));
    request.then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [q, mode, category, ordering]);

  const update = (next) => {
    const merged = { q, mode, category, ordering, ...next };
    if (merged.mode === "hybrid") delete merged.mode;
    if (merged.ordering === "rating") delete merged.ordering;
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v)));
  };

  // Three products from different categories for the hero illustration.
  const showcase = useMemo(() => {
    const seen = new Set();
    return (data?.results || []).filter((p) => !seen.has(p.category.slug) && seen.add(p.category.slug)).slice(0, 3);
  }, [data]);
  const [heroItems, setHeroItems] = useState([]);
  useEffect(() => { if (!q && !category && showcase.length === 3 && heroItems.length === 0) setHeroItems(showcase); }, [showcase, q, category, heroItems.length]);

  const intent = data?.intent;
  const parser = data?.parser;
  return (
    <>
      {!q && !photo ? (
        <section className="hero">
          <div className="hero-grid">
            <div>
              <span className="eyebrow"><Sparkles size={14} />AI-powered shopping</span>
              <h1>Shop the way you talk.</h1>
              <p className="lead">Describe what you need in your own words. ShopFlow understands meaning, budgets and categories, and its assistant can fill your cart for you.</p>
              <SearchForm draft={draft} setDraft={setDraft} mode={mode} onMode={(m) => update({ mode: m })} onSubmit={() => { setPhoto(null); update({ q: draft.trim() }); }} onPhoto={searchByPhoto} />
              <div className="row" style={{ marginTop: 14, gap: 8 }}>
                {EXAMPLES.map((e) => <button key={e} className="chip" onClick={() => update({ q: e })}>{e}</button>)}
              </div>
            </div>
            <div className="hero-art" aria-hidden="true">
              {heroItems.map((p, i) => (
                <div key={p.id} className={`float f${i + 1}`}>
                  <ProductArt product={p} />
                  <div className="cap">{p.name}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : (
        <div className="search-compact">
          <SearchForm draft={draft} setDraft={setDraft} mode={mode} onMode={(m) => update({ mode: m })} onSubmit={() => { setPhoto(null); update({ q: draft.trim() }); }} onPhoto={searchByPhoto} />
        </div>
      )}

      {photo && (
        <section className="card photo-panel">
          {photo.preview ? <img src={photo.preview} alt="Your photo" /> : <span />}
          <div>
            <div className="row spread">
              <h2 style={{ margin: 0 }} className="icon-text"><Camera size={20} />Snap &amp; Search</h2>
              <button className="btn sm" onClick={() => setPhoto(null)}><X size={15} />Clear photo</button>
            </div>
            {photo.loading && <p className="muted" style={{ marginTop: 10 }}>Looking at your photo…</p>}
            {photo.error && <p className="error" style={{ marginTop: 10 }}><CircleAlert size={18} />{photo.error}</p>}
            {photo.results && (
              <div className="stack" style={{ marginTop: 10 }}>
                <p className="muted" style={{ margin: 0 }}>
                  {photo.understood ? <>Claude sees: <strong style={{ color: "var(--ink)" }}>{photo.understood.description}</strong> Searching for “{photo.understood.search_query}” and matching the image with CLIP.</>
                    : <>Matched with CLIP, a vision model that places photos and product descriptions in the same vector space. Runs locally, free.</>}
                </p>
                <div className="row" style={{ gap: 6 }}>
                  <span className="badge brand">{photo.method === "claude+clip" ? "Claude vision + CLIP" : "CLIP (offline)"}</span>
                  <span className="badge">{photo.latency_ms} ms</span>
                </div>
                {photo.low_confidence && <p className="warn-note"><TriangleAlert size={15} />Not sure this photo shows something we sell, so these matches may be loose.</p>}
              </div>
            )}
          </div>
        </section>
      )}

      {photo?.results && (
        <div className="grid" style={{ marginBottom: 28 }}>
          {photo.results.map((p) => <ProductCard key={p.id} product={p} match={p.match} />)}
        </div>
      )}

      {!q && !photo && (
        <div className="features">
          <Link to="/planner" className="card feature"><span className="icon-tile"><WandSparkles size={19} /></span><div><strong>AI Shopping Planner</strong><span>Describe a goal and budget; get an optimised cart.</span></div></Link>
          <label className="card feature" style={{ cursor: "pointer" }}><span className="icon-tile"><Camera size={19} /></span><div><strong>Snap &amp; Search</strong><span>Upload a photo to find matching products.</span></div>
            <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) searchByPhoto(f); }} />
          </label>
          <div className="card feature"><span className="icon-tile"><Bot size={19} /></span><div><strong>AI shopping assistant</strong><span>Compares products, fills your cart and tracks orders.</span></div></div>
        </div>
      )}

      {intent && (
        <div className="intent">
          <span className="label"><Sparkles size={15} />Understood as</span>
          <span className="chip static"><Search size={13} />{intent.semantic_query}</span>
          {intent.category_slug && <span className="chip static"><Tag size={13} />{CATEGORIES[intent.category_slug]?.name || intent.category_slug}</span>}
          {intent.min_price != null && <span className="chip static"><IndianRupee size={13} />from {rupees(intent.min_price)}</span>}
          {intent.max_price != null && <span className="chip static"><IndianRupee size={13} />up to {rupees(intent.max_price)}</span>}
          {intent.in_stock_only && <span className="chip static"><PackageCheck size={13} />in stock</span>}
          <span className="meta">
            {parser?.provider === "anthropic" ? `Claude (${parser.model})` : "rule-based parser"}{parser?.cached ? " · cached" : ""} · {data.latency_ms} ms
          </span>
        </div>
      )}

      {!photo && (
        <>
      <div className="cats">
        <button className={`cat ${!category ? "active" : ""}`} onClick={() => update({ category: "" })}>
          <span className="cat-icon"><LayoutGrid size={20} /></span>All
        </button>
        {Object.entries(CATEGORIES).map(([slug, c]) => (
          <button key={slug} className={`cat ${category === slug ? "active" : ""}`} style={{ "--c": c.color }} onClick={() => update({ category: slug })}>
            <span className="cat-icon"><c.icon size={20} /></span>{c.name}
          </button>
        ))}
      </div>

      <div className="toolbar">
        <h2>
          {q ? <>Results for “{q}”</> : category ? CATEGORIES[category]?.name : "All products"}
          {data && <span className="muted small" style={{ fontWeight: 600, marginLeft: 8 }}>{data.results.length} items</span>}
        </h2>
        <div className="row" style={{ gap: 8 }}>
          {q ? (
            <button className="btn sm" onClick={() => update({ q: "" })}><X size={15} />Clear search</button>
          ) : (
            <select className="input" value={ordering} onChange={(e) => update({ ordering: e.target.value })} aria-label="Sort by">
              <option value="rating">Top rated</option>
              <option value="price">Price: low to high</option>
              <option value="-price">Price: high to low</option>
              <option value="name">Name</option>
            </select>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !data ? (
        <SkeletonGrid />
      ) : data && data.results.length === 0 ? (
        <EmptyState icon={SearchX} title="No products matched">Try different words, or remove the category or price filter.</EmptyState>
      ) : (
        <div className="grid" style={{ opacity: loading ? 0.55 : 1, transition: "opacity 0.15s" }}>
          {data?.results.map((p) => <ProductCard key={p.id} product={p} match={p.match} />)}
        </div>
      )}
        </>
      )}
    </>
  );
}

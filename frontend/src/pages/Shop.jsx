import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, Camera, CircleAlert, IndianRupee, LayoutGrid, PackageCheck, RotateCcw, Search, SearchCheck, SearchX, Sparkles, Tag, TriangleAlert, WandSparkles, X } from "lucide-react";
import { aiBy } from "../ai.js";
import { api, rupees, upload } from "../api.js";
import ProductArt, { CATEGORIES } from "../components/ProductArt.jsx";
import ProductCard from "../components/ProductCard.jsx";
import { EmptyState, SkeletonGrid } from "../components/ui.jsx";
import WhyNotHere from "../components/WhyNotHere.jsx";

const EXAMPLES = [
  "something to keep my coffee hot for hours",
  "shoes for rainy season running under 5000",
  "gift for someone learning to code",
  "in stock earbuds under 3k",
];

/** A filter the search read from your words. Click to drop it (or to put it back). */
function FilterChip({ kind, ignored, onToggle, icon: Icon, children }) {
  const off = ignored.includes(kind);
  const what = { category: "category", budget: "price limit", stock: "in-stock filter" }[kind];
  return (
    <button type="button" className={`chip filter-chip ${off ? "ignored" : ""}`} onClick={() => onToggle(kind)}
      title={off ? `Use the ${what} again` : `Search without the ${what}`} aria-pressed={!off}>
      <Icon size={13} />{children}{off ? <RotateCcw size={13} aria-label={`Use the ${what} again`} /> : <X size={13} aria-label={`Remove the ${what}`} />}
    </button>
  );
}

function SearchForm({ draft, setDraft, mode, onMode, onSubmit, onPhoto }) {
  return (
    <form className="search-box" onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
      <div className="input-icon">
        <Sparkles size={18} />
        <input className="input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Describe what you need, e.g. waterproof shoes for monsoon runs under 5000" aria-label="Search products" />
      </div>
      <select className="input" value={mode} onChange={(e) => onMode(e.target.value)} aria-label="Search mode">
        <option value="hybrid">Hybrid AI</option>
        <option value="vector">By meaning</option>
        <option value="keyword">Exact words</option>
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
  // Set by a "Why isn't it here?" fix: parsed constraints to drop, and a longer result list.
  const ignore = params.get("ignore") || "";
  const limit = params.get("limit") || "";
  const [explaining, setExplaining] = useState(false);
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
      ? api("/api/ai/search/", { query: { q, mode, category, ignore, limit } })
      : api("/api/products/", { query: { category, ordering, page_size: 60 } }).then((r) => ({ results: r.results, count: r.count }));
    request.then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [q, mode, category, ordering, ignore, limit]);

  const ignored = ignore ? ignore.split(",") : [];
  const toggleIgnore = (kind) => update({ ignore: (ignored.includes(kind) ? ignored.filter((k) => k !== kind) : [...ignored, kind]).join(",") });

  const update = (next) => {
    const fresh = next.q !== undefined && next.q !== q; // a new search starts without earlier fixes
    const merged = { q, mode, category, ordering, ...(fresh ? {} : { ignore, limit }), ...next };
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
              <h1>Shop the way you <span className="grad-text">talk.</span></h1>
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
          {intent.category_slug && <FilterChip kind="category" ignored={ignored} onToggle={toggleIgnore} icon={Tag}>{CATEGORIES[intent.category_slug]?.name || intent.category_slug}</FilterChip>}
          {(intent.min_price != null || intent.max_price != null) && (
            <FilterChip kind="budget" ignored={ignored} onToggle={toggleIgnore} icon={IndianRupee}>
              {[intent.min_price != null && `from ${rupees(intent.min_price)}`, intent.max_price != null && `up to ${rupees(intent.max_price)}`].filter(Boolean).join(" ")}
            </FilterChip>
          )}
          {intent.in_stock_only && <FilterChip kind="stock" ignored={ignored} onToggle={toggleIgnore} icon={PackageCheck}>in stock</FilterChip>}
          {limit && <button className="chip" onClick={() => update({ limit: "" })}><RotateCcw size={13} />Back to the top 12</button>}
          <span className="meta">
            {`read by ${aiBy(parser?.provider, parser?.model)}`}{parser?.cached ? " · cached" : ""} · {data.latency_ms} ms
          </span>
        </div>
      )}

      {!photo && (
        <>
      <div className="cats">
        <button className={`cat ${!category ? "active" : ""}`} onClick={() => update({ category: "" })}>
          <span className="cat-media"><LayoutGrid size={26} strokeWidth={1.8} /></span>All
        </button>
        {Object.entries(CATEGORIES).map(([slug, c]) => (
          <button key={slug} className={`cat ${category === slug ? "active" : ""}`} onClick={() => update({ category: slug })}>
            <span className="cat-media"><img src={c.image} alt="" width="640" height="480" loading="lazy" decoding="async" /></span>{c.name}
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
            <>
              <button className={`btn sm ${explaining ? "active" : ""}`} onClick={() => setExplaining((v) => !v)} aria-expanded={explaining}><SearchCheck size={15} />Why isn't it here?</button>
              <button className="btn sm" onClick={() => update({ q: "" })}><X size={15} />Clear search</button>
            </>
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

      {q && explaining && (
        <WhyNotHere
          search={{ q, mode, category, ignore, limit }}
          onApply={(fix) => update({
            ignore: fix.ignore ?? ignore, limit: fix.limit ? String(fix.limit) : limit, mode: fix.mode ?? mode,
            category: "category" in fix ? fix.category : category,
          })}
        />
      )}

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

import { useEffect, useState } from "react";
import {
  Activity, CircleAlert, CircleCheck, CircleX, Coins, Database, ExternalLink, FlaskConical, Gauge, Package,
  ShieldAlert, Sparkles, TriangleAlert, WandSparkles, Zap,
} from "lucide-react";
import { api } from "../api.js";
import { EmptyState, toast } from "../components/ui.jsx";
import { OrderCard } from "./Orders.jsx";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN"));
const pct = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);
const usd = (n) => (n == null ? "—" : `$${Number(n).toFixed(n < 1 ? 4 : 2)}`);

// Status always shows an icon + label, never colour alone.
const STATUS = { ok: ["good-ink", CircleCheck, "OK"], refusal: ["", TriangleAlert, "Refused"], error: ["critical-ink", CircleX, "Error"] };

function Kpi({ icon: Icon, label, value, sub }) {
  return (
    <div className="card kpi">
      <div className="head">{label}<span className="icon-tile"><Icon size={16} /></span></div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function EvalSummary({ suite, run }) {
  const metrics = run.metrics;
  const nested = Object.values(metrics).every((v) => v && typeof v === "object");
  return (
    <div className="card">
      <div className="row spread" style={{ marginBottom: 12 }}>
        <div className="card-title" style={{ margin: 0 }}><span className="icon-tile"><FlaskConical size={17} /></span><h3>{suite}</h3></div>
        <span className="muted small">{new Date(run.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
      </div>
      <div className="table-wrap">
        {nested ? (
          <table className="data">
            <thead><tr><th>System</th>{Object.keys(Object.values(metrics)[0]).map((k) => <th key={k} className="num">{k}</th>)}</tr></thead>
            <tbody>{Object.entries(metrics).map(([system, row]) => (
              <tr key={system}><td><strong>{system}</strong></td>{Object.values(row).map((v, i) => <td key={i} className="num">{v ?? "—"}</td>)}</tr>
            ))}</tbody>
          </table>
        ) : (
          <table className="data"><tbody>{Object.entries(metrics).map(([k, v]) => <tr key={k}><td>{k.replaceAll("_", " ")}</td><td className="num"><strong>{String(v)}</strong></td></tr>)}</tbody></table>
        )}
      </div>
      <p className="muted small" style={{ margin: "10px 0 0" }}>{run.config.llm_provider} · {run.config.embedding_model}</p>
    </div>
  );
}

function Observability() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/ai/metrics/", { query: { days } }).then(setData).catch((e) => setError(e.message));
  }, [days]);
  if (error) return <p className="error"><CircleAlert size={18} />{error}</p>;
  if (!data) return <div className="kpis">{[1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton" style={{ height: 120 }} />)}</div>;
  const t = data.totals;
  const maxCalls = Math.max(1, ...data.by_feature.map((f) => f.calls));
  return (
    <div className="stack">
      <div className="segmented" role="tablist" aria-label="Time window">
        {[1, 7, 30].map((d) => <button key={d} className={days === d ? "active" : ""} onClick={() => setDays(d)}>Last {d} day{d > 1 ? "s" : ""}</button>)}
      </div>
      <div className="kpis">
        <Kpi icon={Activity} label="LLM calls" value={fmt(t.calls)} sub={`${fmt(t.fallbacks)} served by a fallback model`} />
        <Kpi icon={Database} label="Tokens" value={fmt(t.input_tokens + t.output_tokens)} sub={`${fmt(t.input_tokens)} in · ${fmt(t.output_tokens)} out`} />
        <Kpi icon={Coins} label="Estimated cost" value={usd(t.cost_usd)} sub="from list prices" />
        <Kpi icon={Zap} label="Prompt-cache hit rate" value={pct(t.cache_hit_rate)} sub={`${fmt(t.cache_read_tokens)} tokens from cache`} />
        <Kpi icon={ShieldAlert} label="Errors / refusals" value={`${pct(t.error_rate)} / ${pct(t.refusal_rate)}`} sub="share of calls" />
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-title"><span className="icon-tile"><Gauge size={18} /></span><h2>Calls by feature</h2></div>
          {data.by_feature.length === 0 && <p className="muted">No LLM calls in this window yet. Try the assistant or AI search.</p>}
          <div className="meters">
            {data.by_feature.map((f) => (
              <div key={f.feature} className="meter-row">
                <span>{f.feature}</span>
                <div className="meter" role="img" aria-label={`${f.feature}: ${f.calls} calls`}><div style={{ width: `${(f.calls / maxCalls) * 100}%` }} /></div>
                <span className="figure">{fmt(f.calls)}</span>
              </div>
            ))}
          </div>
          {data.by_feature.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 18 }}>
              <table className="data">
                <thead><tr><th>Feature</th><th className="num">p50 ms</th><th className="num">p95 ms</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
                <tbody>{data.by_feature.map((f) => (
                  <tr key={f.feature}><td>{f.feature}</td><td className="num">{fmt(f.p50_latency_ms)}</td><td className="num">{fmt(f.p95_latency_ms)}</td><td className="num">{fmt(f.input_tokens + f.output_tokens)}</td><td className="num">{usd(f.cost_usd)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card">
          <div className="card-title"><span className="icon-tile"><ShieldAlert size={18} /></span><h2>Guardrail events</h2></div>
          {Object.keys(data.guardrail_events).length === 0 ? <p className="muted">None in this window.</p> : (
            <table className="data"><tbody>{Object.entries(data.guardrail_events).map(([kind, n]) => (
              <tr key={kind}><td>{kind.replaceAll("_", " ")}</td><td className="num"><strong>{fmt(n)}</strong></td></tr>
            ))}</tbody></table>
          )}
          <p className="muted small" style={{ margin: "14px 0 0" }}>Blocked prompt injections, flagged reviews, prices the model wrote that were not in tool results, invalid tool inputs and runaway tool loops.</p>
        </section>
      </div>

      <section>
        <h2 style={{ marginBottom: 12 }}>Latest eval runs</h2>
        {Object.keys(data.latest_evals).length === 0 ? <p className="muted">Run <code>python manage.py run_evals</code> to record results here.</p> : (
          <div className="two-col">{Object.entries(data.latest_evals).map(([suite, run]) => <EvalSummary key={suite} suite={suite} run={run} />)}</div>
        )}
      </section>

      <section className="card">
        <div className="card-title"><span className="icon-tile"><Activity size={18} /></span><h2>Recent calls</h2></div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>When</th><th>Feature</th><th>Model</th><th>Status</th><th className="num">In</th><th className="num">Out</th><th className="num">Cached</th><th className="num">ms</th><th className="num">Cost</th></tr></thead>
            <tbody>{data.recent_calls.map((c) => {
              const [cls, Icon, label] = STATUS[c.status] || ["", CircleAlert, c.status];
              return (
                <tr key={c.id}>
                  <td>{new Date(c.created_at).toLocaleTimeString("en-IN", { timeStyle: "short" })}</td><td>{c.feature}</td><td className="muted">{c.model}</td>
                  <td><span className="icon-text" style={{ color: cls ? `var(--${cls})` : "inherit", fontWeight: 650 }}><Icon size={15} />{label}</span></td>
                  <td className="num">{fmt(c.input_tokens)}</td><td className="num">{fmt(c.output_tokens)}</td><td className="num">{fmt(c.cache_read_tokens)}</td>
                  <td className="num">{fmt(c.latency_ms)}</td><td className="num">{usd(c.cost_usd)}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Copywriter() {
  const [products, setProducts] = useState([]);
  const [productId, setProductId] = useState("");
  const [tone, setTone] = useState("friendly");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/products/", { query: { page_size: 100, ordering: "name" } }).then((r) => {
      setProducts(r.results);
      if (r.results[0]) setProductId(String(r.results[0].id));
    });
  }, []);

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await api("/api/ai/copywriter/", { method: "POST", body: { product_id: Number(productId), tone } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    try {
      await api(`/api/products/${productId}/`, { method: "PATCH", body: { description: result.copy.description } });
      toast("Description saved and re-embedded for search");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="two-col" style={{ alignItems: "start" }}>
      <section className="card">
        <div className="card-title"><span className="icon-tile"><WandSparkles size={18} /></span><h2>AI product copywriter</h2></div>
        <p className="muted small">Structured output: headline, description, highlights, tags and SEO text, written only from the product's facts. Numbers that are not in the facts are flagged before you publish.</p>
        <label className="field">Product
          <select className="input" value={productId} onChange={(e) => { setProductId(e.target.value); setResult(null); }}>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="field">Tone
          <select className="input" value={tone} onChange={(e) => setTone(e.target.value)}>
            <option value="friendly">Friendly</option><option value="premium">Premium</option><option value="concise">Concise</option>
          </select>
        </label>
        <button className="btn primary" onClick={generate} disabled={busy || !productId}><Sparkles size={16} />{busy ? "Generating…" : "Generate copy"}</button>
        {error && <p className="error" style={{ marginTop: 12 }}><CircleAlert size={18} />{error}</p>}
      </section>
      {busy && <div className="skeleton" style={{ height: 380 }} />}
      {result && !busy && (
        <section className="card insights copy-out">
          <div className="row spread"><h2 style={{ margin: 0 }}>{result.copy.headline}</h2><span className="badge brand">{result.provider === "anthropic" ? `Claude · ${result.model}` : "Offline template"}</span></div>
          {result.warnings.map((w, i) => <p key={i} className="warn-note" style={{ marginTop: 10 }}><TriangleAlert size={15} />{w}</p>)}
          <p style={{ marginTop: 12 }}>{result.copy.description}</p>
          <h3>Highlights</h3>
          <ul>{result.copy.highlights.map((h, i) => <li key={i}>{h}</li>)}</ul>
          <h3>Tags</h3>
          <div className="row" style={{ gap: 6 }}>{result.copy.tags.map((t) => <span key={t} className="chip static">{t}</span>)}</div>
          <h3>SEO meta description</h3>
          <p className="small">{result.copy.seo_meta_description} <span className="muted">({result.copy.seo_meta_description.length}/160)</span></p>
          <button className="btn" onClick={apply}><CircleCheck size={16} />Use this description</button>
        </section>
      )}
    </div>
  );
}

function AllOrders() {
  const [orders, setOrders] = useState(null);
  useEffect(() => { api("/api/orders/").then((r) => setOrders(r.results)); }, []);
  if (!orders) return <div className="skeleton" style={{ height: 300 }} />;
  if (orders.length === 0) return <EmptyState icon={Package} title="No orders yet" />;
  const replace = (updated) => setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)));
  return <div className="stack">{orders.map((o) => <OrderCard key={o.id} order={o} onChange={replace} admin />)}</div>;
}

const TABS = [["observability", "LLM observability", Gauge], ["copywriter", "AI copywriter", WandSparkles], ["orders", "Orders", Package]];

export default function AdminAI() {
  const [tab, setTab] = useState("observability");
  return (
    <>
      <div className="page-head row spread">
        <div>
          <h1>AI admin</h1>
          <p>Monitor LLM usage and quality, draft product copy and manage orders.</p>
        </div>
        <div className="segmented" role="tablist">
          {TABS.map(([key, label, Icon]) => (
            <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={16} />{label}</button>
          ))}
          <a href="/admin/" target="_blank" rel="noreferrer"><ExternalLink size={15} />Django admin</a>
        </div>
      </div>
      {tab === "observability" && <Observability />}
      {tab === "copywriter" && <Copywriter />}
      {tab === "orders" && <AllOrders />}
    </>
  );
}

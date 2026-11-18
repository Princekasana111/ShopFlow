import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive, ArrowRight, CircleAlert, CircleCheck, CircleX, Info, ListChecks, Minus, Plug, Ruler, ScanSearch, Shuffle, Sparkles, TriangleAlert,
} from "lucide-react";
import { aiBy } from "../ai.js";
import { api, rupees } from "../api.js";
import ProductArt from "./ProductArt.jsx";

// Status is always shown as an icon plus a word, never colour alone.
const STATUS = {
  pass: [CircleCheck, "Looks good"],
  info: [Info, "Note"],
  warn: [TriangleAlert, "Review"],
  fail: [CircleX, "Problem"],
  skip: [Minus, "Nothing to check"],
};
const CHECK_ICON = { sizes: Ruler, compatibility: Plug, requirements: ListChecks, duplicates: Archive, alternatives: Shuffle };
const VERDICT = { ready: [CircleCheck, "ready"], review: [TriangleAlert, "review"], stop: [CircleX, "stop"] };

function Finding({ finding, showProduct, onSize }) {
  const [Icon] = STATUS[finding.severity];
  return (
    <div className={`pc-finding ${finding.severity}`}>
      <Icon size={16} aria-hidden="true" />
      <div>
        <span>{showProduct && finding.product && <strong>{finding.product}: </strong>}{finding.message}</span>
        {finding.evidence && <span className="pc-evidence">Evidence: {finding.evidence}</span>}
        {finding.owned?.order_id && <Link to="/orders" className="small">Order #{finding.owned.order_id}</Link>}
        {onSize && finding.suggested_size && finding.product_id && (
          <button type="button" className="btn sm pc-size-btn" onClick={() => onSize(finding.product_id, finding.suggested_size)}>Use {finding.suggested_size}</button>
        )}
        {finding.alternative && (
          <Link to={`/products/${finding.alternative.id}`} className="pc-alt">
            <ProductArt product={finding.alternative} size="sm" />
            <span><strong>{finding.alternative.name}</strong><span className="muted small">{rupees(finding.alternative.price)}{finding.alternative.avg_rating ? ` · ${finding.alternative.avg_rating}★` : ""}</span></span>
            <ArrowRight size={16} />
          </Link>
        )}
      </div>
    </div>
  );
}

export function CheckReport({ report, onSize }) {
  const [VerdictIcon, tone] = VERDICT[report.verdict.status];
  const several = report.items.length > 1;
  const judge = aiBy(report.judge?.provider, report.judge?.model);
  return (
    <div className="pc-report">
      <div className={`pc-verdict ${tone}`} role="status">
        <VerdictIcon size={22} aria-hidden="true" />
        <div>
          <strong>{report.verdict.headline}</strong>
          {report.verdict.possible_saving && <span> · skipping what you already have would save {rupees(report.verdict.possible_saving)}</span>}
          <div className="small">
            {report.requirements.length ? <>Checked against: {report.requirements.map((r) => r.label).join(", ")}</> : "Tell us what you need it for to check your requirements too."}
            {" · "}Judged by {judge} · {report.latency_ms} ms
          </div>
        </div>
      </div>
      <ul className="pc-checks">
        {report.checks.map((check) => {
          const Icon = CHECK_ICON[check.key];
          const [StatusIcon, label] = STATUS[check.status];
          return (
            <li key={check.key} className={`pc-check ${check.status}`}>
              <div className="pc-head">
                <span className="icon-tile"><Icon size={17} /></span>
                <div className="pc-title"><strong>{check.title}</strong><span className="muted small">{check.summary}</span></div>
                <span className={`pc-pill ${check.status}`}><StatusIcon size={14} aria-hidden="true" />{label}</span>
              </div>
              {check.findings.length > 0 && (
                <div className="pc-findings">
                  {check.findings.map((f, i) => <Finding key={i} finding={f} showProduct={several} onSize={onSize} />)}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** "Before you buy": runs the five checks on the cart, or on one product (with the chosen size). */
export default function PurchaseCheck({ productId, size, auto = false, refreshKey = 0, title = "Before you buy", onSize }) {
  const [text, setText] = useState("");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const run = async (requirements = text) => {
    setLoading(true);
    setError("");
    try {
      const body = { requirements, ...(productId ? { product_id: productId } : {}), ...(size ? { size } : {}) };
      setReport(await api("/api/ai/purchase-check/", { method: "POST", body }));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (auto) run();
    // re-run when the cart or the chosen size changes
  }, [auto, productId, size, refreshKey]);

  return (
    <section className="card insights pc-panel" aria-label={title}>
      <div className="card-title">
        <span className="icon-tile"><ScanSearch size={19} /></span>
        <div>
          <h2>{title}</h2>
          <span className="muted small">Sizes, compatibility, your needs, things you already own, and better alternatives.</span>
        </div>
      </div>
      <form className="pc-form" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <input
          className="input" value={text} maxLength={500} onChange={(e) => setText(e.target.value)}
          placeholder="What do you need it for? e.g. running in the rain, under ₹4,000" aria-label="What do you need it for?"
        />
        <button className="btn primary" disabled={loading}><Sparkles size={16} />{loading ? "Checking…" : report ? "Check again" : "Run check"}</button>
      </form>
      <p className="muted small" style={{ margin: "8px 0 0" }}>Uses your <Link to="/my-stuff">saved sizes and needs</Link> and your past orders.</p>
      {error && <p className="error" style={{ marginTop: 12 }}><CircleAlert size={18} />{error}</p>}
      {loading && !report && <div className="skeleton" style={{ height: 220, marginTop: 14 }} />}
      {report && <CheckReport report={report} onSize={onSize} />}
    </section>
  );
}

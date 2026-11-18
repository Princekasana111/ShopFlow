import { useEffect, useState } from "react";
import { CircleCheck, Ruler, Scale, TriangleAlert } from "lucide-react";
import { aiBy } from "../ai.js";
import { api } from "../api.js";

const VERDICT = {
  contradicted: [TriangleAlert, "Reviews disagree", "warn"],
  disputed: [Scale, "Mixed reports", "info"],
  supported: [CircleCheck, "Reviews back it up", "pass"],
};

/** Listing vs reviews: where reviewers back up or contradict what the listing claims. */
export function ListingCheck({ productId, reloadKey }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    setData(null);
    api(`/api/ai/products/${productId}/listing-check/`).then(setData).catch(() => setData({ findings: [] }));
  }, [productId, reloadKey]);
  if (!data || data.findings.length === 0) return null;
  const judge = aiBy(data.provider, data.model);
  return (
    <section className="card insights listing-check">
      <div className="card-title">
        <span className="icon-tile"><Scale size={19} /></span>
        <div>
          <h2>Listing vs reviews</h2>
          <span className="muted small">What the listing claims, checked against {data.review_count} customer reviews · {judge}</span>
        </div>
      </div>
      <ul className="lc-list">
        {data.findings.map((f) => {
          const [Icon, label, tone] = VERDICT[f.verdict];
          const quotes = f.verdict === "supported" ? f.supporting : f.contradicting;
          const n = f.counts.contradicting;
          return (
            <li key={f.topic + f.label} className={`lc-item ${tone}`}>
              <div className="row spread">
                <strong>{f.label}</strong>
                <span className={`pc-pill ${tone}`}><Icon size={14} aria-hidden="true" />{label}</span>
              </div>
              <p className="small" style={{ margin: "6px 0" }}>
                <span className="muted">Listing says:</span> “{f.listing_quote}”
                {f.verdict !== "supported"
                  ? <> · <strong>{n} reviewer{n > 1 ? "s" : ""}</strong> report{n > 1 ? "" : "s"} otherwise{f.counts.supporting ? `, ${f.counts.supporting} agree${f.counts.supporting > 1 ? "" : "s"}` : ""}.</>
                  : <> · {f.counts.supporting} reviewer{f.counts.supporting > 1 ? "s" : ""} agree{f.counts.supporting > 1 ? "" : "s"}.</>}
              </p>
              {quotes.slice(0, 2).map((q) => <blockquote key={q.review_id} className="lc-quote">“{q.quote}” <span className="muted">· {q.username}, {q.rating}★</span></blockquote>)}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Fit advisor: how the product fits according to its reviews, with a one-click size suggestion. */
export function FitAdvice({ productId, size, onChoose, reloadKey }) {
  const [fit, setFit] = useState(null);
  useEffect(() => {
    api(`/api/ai/products/${productId}/fit/`, { query: { size } }).then(setFit).catch(() => setFit(null));
  }, [productId, size, reloadKey]);
  if (!fit || !fit.available || fit.verdict === "not_enough") return null;
  const s = fit.suggestion;
  return (
    <div className={`fit-advice ${fit.verdict}`}>
      <Ruler size={16} aria-hidden="true" />
      <div>
        <strong>Fit: {fit.label.toLowerCase()}</strong>
        <span className="muted"> · {fit.votes.small} small, {fit.votes.true} true to size, {fit.votes.large} large</span>
        {s && <div className="small">{s.message}</div>}
        {fit.size_pairs[0] && <div className="small muted">{fit.size_pairs[0].username} usually wears {fit.size_pairs[0].usual} and bought {fit.size_pairs[0].bought}.</div>}
      </div>
      {s && s.suggested && s.suggested !== size && <button type="button" className="btn sm" onClick={() => onChoose(s.suggested)}>Choose {s.suggested}</button>}
    </div>
  );
}

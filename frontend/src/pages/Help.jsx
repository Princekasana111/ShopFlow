import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CircleAlert, FileText, LifeBuoy, RotateCcw, Search, ShieldCheck, Sparkles, Truck, Wallet } from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";

const TOPICS = [
  { icon: Truck, title: "Shipping", questions: ["Is shipping free?", "How long does delivery take to Pune?"] },
  { icon: RotateCcw, title: "Returns & refunds", questions: ["How long do refunds take for COD orders?", "Can I return socks?"] },
  { icon: Wallet, title: "Payments", questions: ["Is there a fee for cash on delivery?", "Money was debited but my order failed"] },
  { icon: ShieldCheck, title: "Warranty", questions: ["Does warranty cover water damage?", "How do I claim warranty?"] },
];

export default function Help() {
  const { user } = useAuth();
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const ask = async (q) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    setLoading(true);
    setError("");
    try {
      setResult(await api("/api/ai/ask/", { method: "POST", body: { question: text } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // /help?q=... asks that question straight away (used by the footer's help links).
  const [params] = useSearchParams();
  const linked = params.get("q");
  useEffect(() => {
    if (linked) ask(linked);
  }, [linked]);

  return (
    <>
      <section className="help-hero">
        <span className="icon-tile" style={{ margin: "0 auto 14px", background: "rgba(255,255,255,0.16)", color: "#fff", width: 48, height: 48 }}><LifeBuoy size={24} /></span>
        <h1>How can we help?</h1>
        <p>Answers come only from our policy documents, with sources you can check.</p>
        <form className="search-box" onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <div className="input-icon">
            <Search size={18} />
            <input className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about shipping, returns, payments, warranty…" aria-label="Question" />
          </div>
          <button className="btn primary" disabled={loading}><Sparkles size={16} />{loading ? "Searching…" : "Ask"}</button>
        </form>
      </section>

      {error && <p className="error" style={{ marginBottom: 18 }}><CircleAlert size={18} />{error}</p>}

      {loading && <div className="skeleton" style={{ height: 200, marginBottom: 24 }} />}
      {result && !loading && (
        <section className="card insights" style={{ marginBottom: 24 }}>
          <div className="row spread">
            <div className="card-title" style={{ margin: 0 }}>
              <span className="icon-tile"><Sparkles size={19} /></span>
              <div><h2>Answer</h2><span className="muted small">{result.question}</span></div>
            </div>
            <span className="badge brand" title={result.model}>{result.provider === "anthropic" ? `Claude · ${result.model}` : result.provider === "local" ? `Local AI · ${result.model}` : "Quoted from our policies (offline)"}</span>
          </div>
          <p className="answer-text" style={{ marginTop: 14 }}>{result.answer}</p>
          {result.citations.length > 0 && (
            <div className="stack" style={{ marginTop: 6 }}>
              <h3 style={{ margin: 0 }}>Sources</h3>
              {result.citations.map((c) => (
                <div key={c.n} className="source">
                  <span className="n">{c.n}</span>
                  <div>
                    <strong className="icon-text"><FileText size={14} />{c.doc_title} › {c.section}</strong>
                    <div className="muted small" style={{ marginTop: 4 }}>{c.excerpt}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {/* Staff only: shoppers get the answer and its sources; staff can see what the search retrieved. */}
          {user?.is_staff && <details className="small passages" style={{ marginTop: 16 }}>
            <summary className="muted">Staff view: how this answer was found</summary>
            <p className="muted" style={{ margin: "10px 0 8px" }}>
              We searched our policy documents for the passages closest to your question, by meaning and by exact words.
              The answer may only use these passages; the ones it quotes are marked.
            </p>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Policy</th><th>Section</th><th title="How close each passage is in meaning to your question (cosine similarity, 0 to 1)">Match</th></tr></thead>
                <tbody>{result.retrieved.map((r, i) => (
                  <tr key={i}>
                    <td>{r.doc_title || r.doc_slug}</td>
                    <td>{r.section}{r.cited && <span className="badge brand" style={{ marginLeft: 8 }}>Used in the answer</span>}</td>
                    <td title={`Similarity ${Number(r.similarity).toFixed(2)} (0 to 1)`}>
                      <span className="match-bar" aria-label={`Match ${Math.round(Math.max(0, r.similarity) * 100)} out of 100`}><span style={{ width: `${Math.round(Math.max(0, r.similarity) * 100)}%` }} /></span>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </details>}
        </section>
      )}

      <div className="topics">
        {TOPICS.map(({ icon: Icon, title, questions }) => (
          <div key={title} className="card topic">
            <span className="icon-tile"><Icon size={19} /></span>
            <h3 style={{ margin: "4px 0 2px" }}>{title}</h3>
            {questions.map((q) => <button key={q} onClick={() => ask(q)}>{q}</button>)}
          </div>
        ))}
      </div>
    </>
  );
}

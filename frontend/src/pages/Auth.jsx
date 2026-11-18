import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bot, CircleAlert, LifeBuoy, ShoppingBag, Sparkles, UserRound } from "lucide-react";
import { useAuth } from "../auth.jsx";

function SidePanel({ title }) {
  return (
    <aside className="auth-side">
      <span className="brand" style={{ color: "#fff" }}><span className="logo-mark" style={{ background: "rgba(255,255,255,0.18)", color: "#fff" }}><ShoppingBag size={18} /></span>ShopFlow</span>
      <h2>{title}</h2>
      <ul>
        <li><span className="icon-tile"><Sparkles size={17} /></span><span><strong>AI search</strong><br />Describe what you need, budget included.</span></li>
        <li><span className="icon-tile"><Bot size={17} /></span><span><strong>Shopping assistant</strong><br />Finds products, fills your cart, tracks orders.</span></li>
        <li><span className="icon-tile"><LifeBuoy size={17} /></span><span><strong>Help center</strong><br />Policy answers with sources.</span></li>
      </ul>
    </aside>
  );
}

// Where a shopper was going when we asked them to log in, in words ("your cart").
function destination(from) {
  if (!from) return "";
  const names = { "/cart": "your cart", "/orders": "your orders", "/my-stuff": "My stuff", "/my-offers": "My offers", "/planner": "your plan", "/ai-admin": "AI admin" };
  return names[from.split("?")[0]] || (from.startsWith("/products/") ? "this product" : "that page");
}

/** After logging in (or signing up), go back to where the shopper was going. */
function useReturnTo() {
  const location = useLocation();
  const navigate = useNavigate();
  const from = location.state?.from;
  return { from, state: location.state, done: () => navigate(from && from.startsWith("/") && !from.startsWith("//") ? from : "/", { replace: true }) };
}

export function Login() {
  const { login } = useAuth();
  const back = useReturnTo();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (creds = form) => {
    setError("");
    setBusy(true);
    try {
      await login(creds.username, creds.password);
      back.done();
    } catch {
      setError("Wrong username or password.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card auth">
      <SidePanel title="Welcome back" />
      <form className="auth-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h1>Log in</h1>
        {back.from ? <p className="notice small">Log in to continue to {destination(back.from)}.</p> : <p className="muted">Good to see you again.</p>}
        <label className="field">Username<input className="input" autoComplete="username" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label className="field">Password<input className="input" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        {error && <p className="error" style={{ marginBottom: 14 }}><CircleAlert size={18} />{error}</p>}
        <button className="btn primary lg block" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
        <div className="divider">or try a demo account</div>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" style={{ flex: 1 }} onClick={() => submit({ username: "demo", password: "demo12345" })}><UserRound size={16} />Customer demo</button>
          <button type="button" className="btn" style={{ flex: 1 }} onClick={() => submit({ username: "admin", password: "admin12345" })}><UserRound size={16} />Staff demo</button>
        </div>
        <p className="small" style={{ marginTop: 18 }}>New here? <Link to="/register" state={back.state}>Create an account</Link></p>
      </form>
    </div>
  );
}

export function Register() {
  const { register } = useAuth();
  const back = useReturnTo();
  const [form, setForm] = useState({ username: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await register(form);
      back.done();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card auth">
      <SidePanel title="Shop smarter with AI" />
      <form className="auth-form" onSubmit={submit}>
        <h1>Create an account</h1>
        <p className="muted">It takes less than a minute.</p>
        <label className="field">Username<input className="input" autoComplete="username" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label className="field">Email<input className="input" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label className="field">Password<input className="input" type="password" autoComplete="new-password" minLength={8} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        {error && <p className="error" style={{ marginBottom: 14 }}><CircleAlert size={18} />{error}</p>}
        <button className="btn primary lg block" disabled={busy}>{busy ? "Creating account…" : "Sign up"}</button>
        <p className="small" style={{ marginTop: 18 }}>Already have an account? <Link to="/login" state={back.state}>Log in</Link></p>
      </form>
    </div>
  );
}

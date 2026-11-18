import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Archive, CircleAlert, PackageOpen, RefreshCw, Ruler, Save, ScanSearch, Truck } from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import ProductArt from "../components/ProductArt.jsx";
import { EmptyState, toast } from "../components/ui.jsx";
import { usePreferences } from "../sizes.js";

const SHOE_SIZES = Array.from({ length: 11 }, (_, i) => i + 3);
const CLOTHING = ["XS", "S", "M", "L", "XL", "XXL"];
const WAISTS = Array.from({ length: 9 }, (_, i) => 26 + i * 2);

function Preferences() {
  const { user } = useAuth();
  const { prefs, save } = usePreferences(user);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (prefs) setForm({ shoe_size_uk: prefs.shoe_size_uk ?? "", clothing_size: prefs.clothing_size || "", waist_in: prefs.waist_in ?? "", needs: prefs.needs || "" });
  }, [prefs]);
  if (!form) return <div className="skeleton" style={{ height: 320 }} />;

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await save({
        shoe_size_uk: form.shoe_size_uk === "" ? null : Number(form.shoe_size_uk),
        clothing_size: form.clothing_size,
        waist_in: form.waist_in === "" ? null : Number(form.waist_in),
        needs: form.needs,
      });
      toast("Saved. The purchase check will use these.");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const select = (name, label, options, format = (o) => o) => (
    <label className="field">{label}
      <select className="input" value={form[name]} onChange={(e) => setForm({ ...form, [name]: e.target.value })}>
        <option value="">Not set</option>
        {options.map((o) => <option key={o} value={o}>{format(o)}</option>)}
      </select>
    </label>
  );
  return (
    <form className="card sticky" onSubmit={submit}>
      <div className="card-title">
        <span className="icon-tile"><Ruler size={18} /></span>
        <div><h2>My sizes & needs</h2><span className="muted small">Used to pre-select sizes and in every purchase check.</span></div>
      </div>
      <div className="form-grid three">
        {select("shoe_size_uk", "Shoe size", SHOE_SIZES, (n) => `UK ${n}`)}
        {select("clothing_size", "Clothing size", CLOTHING)}
        {select("waist_in", "Waist", WAISTS, (n) => `${n} in`)}
      </div>
      <label className="field">Things to check every purchase against
        <textarea
          className="input" rows={4} maxLength={500} value={form.needs} onChange={(e) => setForm({ ...form, needs: e.target.value })}
          placeholder="e.g. I run outdoors, often in the rain. I cook on an induction stove. My laptop only has USB-C ports."
        />
      </label>
      <button className="btn primary block" disabled={saving}><Save size={16} />{saving ? "Saving…" : "Save"}</button>
    </form>
  );
}

export default function MyStuff() {
  const [inv, setInv] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/api/ai/owned/").then(setInv).catch((e) => setError(e.message)); }, []);

  return (
    <>
      <div className="page-head row spread">
        <div>
          <h1>What I already own</h1>
          <p>Everything from your orders, grouped by what it does, so you don't buy what you already have.</p>
        </div>
        <Link to="/cart" className="btn"><ScanSearch size={17} />Check my cart</Link>
      </div>
      {error && <p className="error"><CircleAlert size={18} />{error}</p>}
      <div className="mystuff">
        <div className="stack">
          {inv && (
            <div className="kpis">
              <div className="card kpi"><div className="head">Items owned<span className="icon-tile"><Archive size={16} /></span></div><div className="value">{inv.count}</div></div>
              <div className="card kpi"><div className="head">On the way<span className="icon-tile"><Truck size={16} /></span></div><div className="value">{inv.on_the_way}</div></div>
              <div className="card kpi"><div className="head">Due for replacement<span className="icon-tile"><RefreshCw size={16} /></span></div><div className="value">{inv.replacement_due}</div></div>
            </div>
          )}
          {!inv && !error && <div className="skeleton" style={{ height: 300 }} />}
          {inv && inv.count === 0 && (
            <EmptyState icon={PackageOpen} title="Nothing here yet">Things you order show up here, and the purchase check uses them to spot duplicates.</EmptyState>
          )}
          {inv?.groups.map((group) => (
            <section key={group.label} className="card">
              <h2 style={{ fontSize: "1.05rem" }}>{group.label}</h2>
              <div className="owned-list">
                {group.items.map((row, i) => (
                  <div key={`${row.order_id}-${i}`} className="owned-row">
                    <ProductArt product={row.product} size="sm" />
                    <div style={{ minWidth: 0 }}>
                      {row.product.id ? <Link to={`/products/${row.product.id}`} className="title">{row.product.name}</Link> : <strong>{row.product.name}</strong>}
                      <div className="muted small">
                        {row.status === "DELIVERED" ? `Delivered ${row.age}` : "On the way"} · Order #{row.order_id}{row.size ? ` · Size ${row.size}` : ""}{row.quantity > 1 ? ` · ×${row.quantity}` : ""}
                      </div>
                      {row.replacement.due && <div className="warn-note" style={{ marginTop: 6 }}><RefreshCw size={14} />{row.replacement.message} Time for a new one?</div>}
                    </div>
                    <span className={`badge ${row.status === "DELIVERED" ? "" : "brand"}`}>{row.status === "DELIVERED" ? "Owned" : "On the way"}</span>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
        <Preferences />
      </div>
    </>
  );
}

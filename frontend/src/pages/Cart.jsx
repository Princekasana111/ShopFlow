import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CircleAlert, Handshake, Lock, MapPin, ShoppingBag, ShoppingCart, Trash2 } from "lucide-react";
import { api, notifyCartChanged, rupees } from "../api.js";
import ProductArt from "../components/ProductArt.jsx";
import PurchaseCheck from "../components/PurchaseCheck.jsx";
import { EmptyState, Stepper, toast } from "../components/ui.jsx";
import { productSizes } from "../sizes.js";

const EMPTY_SHIPPING = { shipping_name: "", shipping_phone: "", shipping_address: "", shipping_city: "", shipping_pincode: "" };

export default function Cart() {
  const [cart, setCart] = useState(null);
  const [shipping, setShipping] = useState(EMPTY_SHIPPING);
  const [error, setError] = useState("");
  const [placing, setPlacing] = useState(false);
  const navigate = useNavigate();

  const load = () => api("/api/cart/").then(setCart).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    window.addEventListener("cart-changed", load);
    return () => window.removeEventListener("cart-changed", load);
  }, []);

  const updateLine = async (productId, body) => {
    try {
      setCart(await api(`/api/cart/items/${productId}/`, { method: "PATCH", body }));
      notifyCartChanged();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const setQty = (productId, quantity) => updateLine(productId, { quantity });

  const checkout = async (e) => {
    e.preventDefault();
    setError("");
    setPlacing(true);
    try {
      const order = await api("/api/orders/checkout/", { method: "POST", body: shipping });
      notifyCartChanged();
      toast(`Order #${order.id} placed`);
      navigate(`/orders?placed=${order.id}`);
    } catch (err) {
      setError(err.message);
      load(); // an expired deal is removed by the server: show the new total
    } finally {
      setPlacing(false);
    }
  };

  if (!cart) return <div className="skeleton" style={{ height: 320 }} />;
  if (cart.items.length === 0) {
    return (
      <EmptyState icon={ShoppingCart} title="Your cart is empty">
        <p>Find something you love, or ask the AI assistant for ideas.</p>
        <Link to="/" className="btn primary"><ShoppingBag size={17} />Start shopping</Link>
      </EmptyState>
    );
  }

  const field = (name, label, { full, ...props } = {}) => (
    <label className={`field ${full ? "full" : ""}`}>{label}
      <input className="input" required value={shipping[name]} onChange={(e) => setShipping({ ...shipping, [name]: e.target.value })} {...props} />
    </label>
  );

  return (
    <>
      <div className="page-head">
        <h1>Your cart</h1>
        <p>{cart.item_count} item{cart.item_count === 1 ? "" : "s"} ready for checkout</p>
      </div>
      <div className="checkout">
        <div className="stack">
        <section className="card">
          {cart.items.map((item) => (
            <div key={item.id} className="line">
              <ProductArt product={item.product} size="sm" />
              <div style={{ minWidth: 0 }}>
                <Link to={`/products/${item.product.id}`} className="title">{item.product.name}</Link>
                <div className="muted small">{item.product.brand} · {rupees(item.product.price)} each</div>
                {item.deal && (item.deal.expired
                  ? <div className="deal-tag expired"><Handshake size={13} />Your deal expired; back to the list price</div>
                  : item.deal.beaten
                  ? <Link to="/my-offers" className="deal-tag"><Handshake size={13} />The price dropped below your deal, so you pay the lower price</Link>
                  : <Link to="/my-offers" className="deal-tag"><Handshake size={13} />Deal price {rupees(item.deal.price)} for one, held until {new Date(item.deal.expires_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}</Link>)}
                <div className="controls">
                  <Stepper size="sm" value={item.quantity} min={1} max={item.deal && !item.deal.expired ? 1 : Math.min(10, item.product.stock)} onChange={(n) => setQty(item.product.id, n)} />
                  {productSizes(item.product).length > 0 && (
                    <select
                      className={`input size-select ${item.size ? "" : "missing"}`} value={item.size}
                      onChange={(e) => updateLine(item.product.id, { size: e.target.value })} aria-label={`Size for ${item.product.name}`}
                    >
                      <option value="">Choose size</option>
                      {productSizes(item.product).map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  )}
                  <button className="btn sm ghost danger" onClick={() => setQty(item.product.id, 0)}><Trash2 size={15} />Remove</button>
                </div>
              </div>
              <div className="total">
                {rupees(item.line_total)}
                {item.deal && !item.deal.expired && !item.deal.beaten && <div className="muted small"><s>{rupees(item.product.price)}</s></div>}
              </div>
            </div>
          ))}
        </section>
        <PurchaseCheck auto refreshKey={cart.items.map((i) => `${i.id}:${i.quantity}:${i.size}`).join("|")} onSize={(productId, s) => updateLine(productId, { size: s })} />
        </div>

        <form className="card sticky" onSubmit={checkout}>
          <h2>Order summary</h2>
          <div className="summary-row"><span>Items ({cart.item_count})</span><span>{rupees(cart.total)}</span></div>
          <div className="summary-row"><span>Delivery</span><span>Free in this demo</span></div>
          <div className="summary-row total"><span>Total</span><span>{rupees(cart.total)}</span></div>

          <div className="card-title" style={{ marginTop: 22 }}>
            <span className="icon-tile"><MapPin size={18} /></span>
            <h3>Shipping address</h3>
          </div>
          <div className="form-grid">
            {field("shipping_name", "Full name", { full: true, autoComplete: "name" })}
            {field("shipping_phone", "Mobile number", { full: true, inputMode: "numeric", pattern: "[6-9][0-9]{9}", title: "10-digit Indian mobile number", autoComplete: "tel" })}
            {field("shipping_address", "Address", { full: true, autoComplete: "street-address" })}
            {field("shipping_city", "City", { autoComplete: "address-level2" })}
            {field("shipping_pincode", "PIN code", { inputMode: "numeric", pattern: "[1-9][0-9]{5}", title: "6-digit PIN code", autoComplete: "postal-code" })}
          </div>
          {error && <p className="error" style={{ marginBottom: 12 }}><CircleAlert size={18} />{error}</p>}
          <button className="btn primary lg block" disabled={placing}><Lock size={17} />{placing ? "Placing order…" : `Place order · ${rupees(cart.total)}`}</button>
          <p className="muted small" style={{ margin: "10px 0 0", textAlign: "center" }}>Demo store: no payment is taken.</p>
        </form>
      </div>
    </>
  );
}

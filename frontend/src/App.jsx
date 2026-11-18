import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Archive, ArrowUpRight, CodeXml, Gauge, Handshake, LifeBuoy, LogOut, Moon, Package, ShoppingBag, ShoppingCart, Store, Sun, WandSparkles } from "lucide-react";
import { aiBadge, featureList } from "./ai.js";
import { api } from "./api.js";
import { useAuth } from "./auth.jsx";
import AssistantPanel from "./components/AssistantPanel.jsx";
import { CATEGORIES } from "./components/ProductArt.jsx";
import { EmptyState, Toaster } from "./components/ui.jsx";
import AdminAI from "./pages/AdminAI.jsx";
import { Login, Register } from "./pages/Auth.jsx";
import Cart from "./pages/Cart.jsx";
import Help from "./pages/Help.jsx";
import MyOffers from "./pages/MyOffers.jsx";
import MyStuff from "./pages/MyStuff.jsx";
import Orders from "./pages/Orders.jsx";
import Planner from "./pages/Planner.jsx";
import ProductDetail from "./pages/ProductDetail.jsx";
import Shop from "./pages/Shop.jsx";
import { useTheme } from "./theme.js";

function useCartCount(user) {
  const [count, setCount] = useState(0);
  const refresh = useCallback(() => {
    if (!user) return setCount(0);
    api("/api/cart/").then((c) => setCount(c.item_count)).catch(() => setCount(0));
  }, [user]);
  useEffect(() => {
    refresh();
    window.addEventListener("cart-changed", refresh);
    return () => window.removeEventListener("cart-changed", refresh);
  }, [refresh]);
  return count;
}

function RequireAuth({ children, staff }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (staff && !user.is_staff) return <EmptyState icon={Gauge} title="Staff only">This page is for staff accounts.</EmptyState>;
  return children;
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <button className="icon-btn" onClick={toggle} aria-label={label} title={label}>
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

const HELP_LINKS = [
  ["Shipping", "Is shipping free?"],
  ["Returns & refunds", "What is the return policy?"],
  ["Payments", "Is there a fee for cash on delivery?"],
  ["Warranty", "How do I claim warranty?"],
];

function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <Link to="/" className="brand"><span className="logo-mark"><ShoppingBag size={18} /></span>ShopFlow</Link>
          <p>Shop the way you talk. Describe what you need, plan a cart within a budget, search with a photo, or let the assistant fill your cart.</p>
          <div className="stack-pills"><span>Django</span><span>PostgreSQL + pgvector</span><span>Claude</span><span>React</span></div>
        </div>
        <nav className="footer-col" aria-label="Shop by category">
          <h3>Shop</h3>
          {Object.entries(CATEGORIES).map(([slug, c]) => <Link key={slug} to={`/?category=${slug}`}>{c.name}</Link>)}
        </nav>
        <nav className="footer-col" aria-label="AI features">
          <h3>AI features</h3>
          <Link to="/?q=gift+for+someone+learning+to+code">AI search</Link>
          <Link to="/planner">Shopping planner</Link>
          <Link to="/help">Help center answers</Link>
        </nav>
        <nav className="footer-col" aria-label="Help">
          <h3>Help</h3>
          {HELP_LINKS.map(([label, q]) => <Link key={label} to={`/help?q=${encodeURIComponent(q)}`}>{label}</Link>)}
        </nav>
      </div>
      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} ShopFlow · A portfolio demo: no real orders, payments or deliveries.</span>
        <a href="https://github.com/Princekasana111/ShopFlow" target="_blank" rel="noreferrer"><CodeXml size={16} />Source on GitHub<ArrowUpRight size={14} /></a>
      </div>
    </footer>
  );
}

function AiStatus({ llm, local }) {
  if (!llm) return null;
  const name = aiBadge(llm.provider);
  const state = llm.degraded ? "degraded" : llm.is_live ? "live" : "";
  const text = llm.degraded ? `${name} unavailable · offline` : llm.is_live ? name : "Offline AI";
  const title = llm.degraded
    ? `${name} could not be reached right now; AI features use the offline rules until it's back.`
    : llm.provider === "local"
      ? `A free AI model running on this server (${llm.model}) writes ${local?.features?.length ? featureList(local.features) : "some answers"}; everything else uses the offline rules.`
      : llm.is_live ? llm.model
      : local?.enabled && !local?.on ? "The local AI model is turned off (staff can turn it on in AI admin): AI features use the free offline mode."
      : "No API key: AI features use the free offline mode.";
  return <span className={`ai-status ${state}`} title={title}><span className="dot" /><span className="label">{text}</span></span>;
}

export default function App() {
  const { user, logout } = useAuth();
  const location = useLocation();
  // "Log in" from any page comes back to that page (the login and sign-up pages keep where you were going).
  const here = ["/login", "/register"].includes(location.pathname) ? location.state : { from: location.pathname + location.search };
  const cartCount = useCartCount(user);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const load = () => api("/api/ai/status/").then(setStatus).catch(() => setStatus(null));
    load();
    window.addEventListener("ai-status-changed", load); // e.g. staff turned the local model on or off
    return () => window.removeEventListener("ai-status-changed", load);
  }, []);

  return (
    <>
      <nav className="nav">
        <div className="container nav-inner">
          <Link to="/" className="brand"><span className="logo-mark"><ShoppingBag size={18} /></span>ShopFlow</Link>
          <div className="nav-links">
            <NavLink to="/" end><Store size={17} />Shop</NavLink>
            <NavLink to="/planner"><WandSparkles size={17} />AI Planner</NavLink>
            <NavLink to="/help"><LifeBuoy size={17} />Help center</NavLink>
            {user && <NavLink to="/orders"><Package size={17} />Orders</NavLink>}
            {user && <NavLink to="/my-stuff"><Archive size={17} />My stuff</NavLink>}
            {user && <NavLink to="/my-offers"><Handshake size={17} />My offers</NavLink>}
            {user?.is_staff && <NavLink to="/ai-admin"><Gauge size={17} />AI admin</NavLink>}
          </div>
          <div className="nav-right">
            <AiStatus llm={status?.llm} local={status?.local_model} />
            <ThemeToggle />
            {user ? (
              <>
                <Link to="/cart" className="icon-btn" aria-label={`Cart, ${cartCount} items`}>
                  <ShoppingCart size={19} />
                  {cartCount > 0 && <span className="count">{cartCount}</span>}
                </Link>
                <span className="user-chip">
                  <span className="avatar">{user.username.slice(0, 2).toUpperCase()}</span>
                  <span className="name">{user.username}</span>
                  <button className="icon-btn" style={{ width: 30, height: 30, border: 0 }} onClick={logout} aria-label="Log out" title="Log out"><LogOut size={16} /></button>
                </span>
              </>
            ) : (
              <>
                <Link to="/login" state={here} className="btn sm">Log in</Link>
                <Link to="/register" state={here} className="btn sm primary">Sign up</Link>
              </>
            )}
          </div>
        </div>
      </nav>

      <main className="container">
        <Routes>
          <Route path="/" element={<Shop />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/help" element={<Help />} />
          <Route path="/planner" element={<Planner />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/cart" element={<RequireAuth><Cart /></RequireAuth>} />
          <Route path="/orders" element={<RequireAuth><Orders /></RequireAuth>} />
          <Route path="/my-stuff" element={<RequireAuth><MyStuff /></RequireAuth>} />
          <Route path="/my-offers" element={<RequireAuth><MyOffers /></RequireAuth>} />
          <Route path="/ai-admin" element={<RequireAuth staff><AdminAI /></RequireAuth>} />
          <Route path="*" element={<EmptyState icon={Store} title="Page not found"><Link to="/">Back to the shop</Link></EmptyState>} />
        </Routes>
      </main>

      <Footer />

      <AssistantPanel llm={status?.assistant || status?.llm} />
      <Toaster />
    </>
  );
}

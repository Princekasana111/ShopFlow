import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Gauge, LifeBuoy, LogOut, Package, ShoppingBag, ShoppingCart, Store, WandSparkles } from "lucide-react";
import { api } from "./api.js";
import { useAuth } from "./auth.jsx";
import AssistantPanel from "./components/AssistantPanel.jsx";
import { EmptyState, Toaster } from "./components/ui.jsx";
import AdminAI from "./pages/AdminAI.jsx";
import { Login, Register } from "./pages/Auth.jsx";
import Cart from "./pages/Cart.jsx";
import Help from "./pages/Help.jsx";
import Orders from "./pages/Orders.jsx";
import Planner from "./pages/Planner.jsx";
import ProductDetail from "./pages/ProductDetail.jsx";
import Shop from "./pages/Shop.jsx";

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
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (staff && !user.is_staff) return <EmptyState icon={Gauge} title="Staff only">This page is for staff accounts.</EmptyState>;
  return children;
}

function AiStatus({ llm }) {
  if (!llm) return null;
  const state = llm.degraded ? "degraded" : llm.is_live ? "live" : "";
  const text = llm.degraded ? "Claude unavailable · offline" : llm.is_live ? "Claude" : "Offline AI";
  const title = llm.degraded ? "Claude could not be reached; AI features are running in offline mode." : llm.is_live ? llm.model : "No API key: AI features use the free offline mode.";
  return <span className={`ai-status ${state}`} title={title}><span className="dot" /><span className="label">{text}</span></span>;
}

export default function App() {
  const { user, logout } = useAuth();
  const cartCount = useCartCount(user);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    api("/api/ai/status/").then(setStatus).catch(() => setStatus(null));
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
            {user?.is_staff && <NavLink to="/ai-admin"><Gauge size={17} />AI admin</NavLink>}
          </div>
          <div className="nav-right">
            <AiStatus llm={status?.llm} />
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
                <Link to="/login" className="btn sm">Log in</Link>
                <Link to="/register" className="btn sm primary">Sign up</Link>
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
          <Route path="/ai-admin" element={<RequireAuth staff><AdminAI /></RequireAuth>} />
          <Route path="*" element={<EmptyState icon={Store} title="Page not found"><Link to="/">Back to the shop</Link></EmptyState>} />
        </Routes>
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <div>
            <Link to="/" className="brand"><span className="logo-mark" style={{ width: 28, height: 28 }}><ShoppingBag size={15} /></span>ShopFlow</Link>
            <p style={{ margin: "8px 0 0" }}>A demo store with hybrid AI search, a RAG help center and a Claude shopping assistant.</p>
          </div>
          <div className="links">
            <Link to="/help">Help center</Link>
            <a href="/api/docs/" target="_blank" rel="noreferrer">API docs</a>
            <span>Django · pgvector · Claude · React</span>
          </div>
        </div>
      </footer>

      <AssistantPanel llm={status?.llm} />
      <Toaster />
    </>
  );
}

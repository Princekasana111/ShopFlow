import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, tokens } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  const loadMe = useCallback(async () => {
    if (!tokens.access) {
      setUser(null);
      setReady(true);
      return;
    }
    try {
      setUser(await api("/api/auth/me/"));
    } catch {
      tokens.clear();
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const login = async (username, password) => {
    tokens.set(await api("/api/auth/login/", { method: "POST", body: { username, password } }));
    await loadMe();
  };

  const register = async (form) => {
    await api("/api/auth/register/", { method: "POST", body: form });
    await login(form.username, form.password);
  };

  const logout = () => {
    tokens.clear();
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, ready, login, register, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

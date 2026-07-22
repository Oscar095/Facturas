import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [usuario, setUsuario] = useState(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    if (getToken()) {
      api.get("/api/auth/yo").then(setUsuario).catch(() => setToken(null)).finally(() =>
        setCargando(false)
      );
    } else {
      setCargando(false);
    }
  }, []);

  async function login(email, password) {
    const r = await api.login(email, password);
    setToken(r.access_token);
    const yo = await api.get("/api/auth/yo");
    setUsuario(yo);
    return yo;
  }

  function logout() {
    setToken(null);
    setUsuario(null);
  }

  return (
    <AuthCtx.Provider value={{ usuario, cargando, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  return useContext(AuthCtx);
}

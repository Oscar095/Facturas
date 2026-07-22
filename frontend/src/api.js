// Cliente HTTP mínimo con manejo del token JWT.
const TOKEN_KEY = "facturas_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request(method, url, { body, form, headers = {} } = {}) {
  const opts = { method, headers: { ...headers } };
  const token = getToken();
  if (token) opts.headers["Authorization"] = `Bearer ${token}`;

  if (form) {
    opts.body = form; // FormData; el navegador pone el content-type
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  const resp = await fetch(url, opts);
  if (resp.status === 401) {
    setToken(null);
    if (!url.endsWith("/login")) window.location.href = "/login";
  }
  if (!resp.ok) {
    let detalle = resp.statusText;
    try {
      const j = await resp.json();
      detalle = j.detail || JSON.stringify(j);
    } catch {}
    throw new Error(detalle);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : resp;
}

export const api = {
  get: (u) => request("GET", u),
  post: (u, body) => request("POST", u, { body }),
  patch: (u, body) => request("PATCH", u, { body }),
  del: (u) => request("DELETE", u),
  postForm: (u, form) => request("POST", u, { form }),

  async login(email, password) {
    const form = new URLSearchParams({ username: email, password });
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!resp.ok) {
      const j = await resp.json().catch(() => ({}));
      throw new Error(j.detail || "Error de acceso");
    }
    return resp.json();
  },
};

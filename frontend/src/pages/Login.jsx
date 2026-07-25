import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { useAuth } from "../auth.jsx";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      await login(email, clave);
      navigate("/");
    } catch (err) {
      setError(err.message || "No se pudo iniciar sesión");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="login-pagina">
      <aside className="login-panel">
        <div className="login-marca">
          <span className="marca-insignia">
            <img src="/logo-kos.png" alt="KOS" />
          </span>
          <span>Portal de Facturas</span>
        </div>
        <motion.p
          className="login-tagline"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        >
          Cada factura, con su historia clara: quién la recibió, qué falta
          y cuándo queda lista para contabilizar.
        </motion.p>
        <div className="login-pie">Recepción de facturas electrónicas · KOS</div>
      </aside>
      <div className="login-lado">
        <form className="login-caja" onSubmit={enviar}>
          <img src="/logo-kos.png" alt="KOS" className="login-logo" />
          <h1>Bienvenido</h1>
          <p className="sub">Ingresa con tu correo y contraseña</p>
          <label>Correo</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
            required
          />
          <label>Contraseña</label>
          <input
            type="password"
            value={clave}
            onChange={(e) => setClave(e.target.value)}
            required
          />
          {error && <div className="error">{error}</div>}
          <button className="btn" disabled={cargando}>
            {cargando ? "Ingresando…" : "Ingresar"}
          </button>
        </form>
      </div>
    </div>
  );
}

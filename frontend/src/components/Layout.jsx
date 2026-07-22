import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";

export default function Layout() {
  const { usuario, logout } = useAuth();
  const navigate = useNavigate();

  function salir() {
    logout();
    navigate("/login");
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="marca">📄 Portal de Facturas</div>
        <nav className="nav">
          <NavLink to="/facturas">Facturas</NavLink>
          {usuario?.rol === "admin" && <NavLink to="/admin">Administración</NavLink>}
        </nav>
        <div className="usuario">
          <span>
            {usuario?.nombre} · <em>{usuario?.rol}</em>
          </span>
          <button className="btn-sec" onClick={salir}>
            Salir
          </button>
        </div>
      </header>
      <main className="contenido">
        <Outlet />
      </main>
    </div>
  );
}

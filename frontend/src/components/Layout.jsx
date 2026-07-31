import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { tienePermiso } from "../util";

export default function Layout() {
  const { usuario, logout } = useAuth();
  const navigate = useNavigate();

  function salir() {
    logout();
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="marca">
          <span className="marca-insignia">
            <img src="/logo-kos.png" alt="KOS" />
          </span>
          <span>Portal de Facturas</span>
        </div>
        <nav className="sidenav">
          <div className="nav-grupo">
            <div className="nav-titulo">General</div>
            <NavLink to="/" end>
              <span className="nav-icono">📊</span> Dashboard
            </NavLink>
            <NavLink to="/facturas">
              <span className="nav-icono">🧾</span> Facturas
            </NavLink>
            {tienePermiso(usuario, "ver_todas_areas") && (
              <NavLink to="/notas-credito">
                <span className="nav-icono">↩️</span> Notas Crédito
              </NavLink>
            )}
            <NavLink to="/firmas">
              <span className="nav-icono">✍️</span> Mis Firmas
            </NavLink>
          </div>
          {tienePermiso(usuario, "administrar") && (
            <div className="nav-grupo">
              <div className="nav-titulo">Administración</div>
              <NavLink to="/admin">
                <span className="nav-icono">⚙️</span> Administración
              </NavLink>
            </div>
          )}
        </nav>
        <div className="sidebar-pie">
          <div className="usuario-info">
            <div className="usuario-nombre">{usuario?.nombre}</div>
            <em>{usuario?.rol}</em>
          </div>
          <button className="btn-sec" onClick={salir}>
            Salir
          </button>
        </div>
      </aside>
      <main className="contenido">
        <Outlet />
      </main>
    </div>
  );
}

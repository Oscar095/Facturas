import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { useAuth } from "./auth.jsx";
import { tienePermiso } from "./util";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Facturas from "./pages/Facturas.jsx";
import FacturaDetalle from "./pages/FacturaDetalle.jsx";
import CargarFactura from "./pages/CargarFactura.jsx";
import NotasCredito from "./pages/NotasCredito.jsx";
import MisFirmas from "./pages/MisFirmas.jsx";
import Admin from "./pages/Admin.jsx";

function Privada({ children, roles, permiso }) {
  const { usuario, cargando } = useAuth();
  if (cargando) return <div className="cargando">Cargando…</div>;
  if (!usuario) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(usuario.rol))
    return <Navigate to="/facturas" replace />;
  if (permiso && !tienePermiso(usuario, permiso))
    return <Navigate to="/facturas" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Privada>
            <Layout />
          </Privada>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="/facturas" element={<Facturas />} />
        <Route
          path="/cargar-factura"
          element={
            <Privada permiso="editar_facturas">
              <CargarFactura />
            </Privada>
          }
        />
        <Route path="/facturas/:id" element={<FacturaDetalle />} />
        <Route
          path="/notas-credito"
          element={
            <Privada permiso="ver_todas_areas">
              <NotasCredito />
            </Privada>
          }
        />
        <Route path="/firmas" element={<MisFirmas />} />
        <Route
          path="/admin"
          element={
            <Privada permiso="administrar">
              <Admin />
            </Privada>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

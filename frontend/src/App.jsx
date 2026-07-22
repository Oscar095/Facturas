import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";
import Facturas from "./pages/Facturas.jsx";
import FacturaDetalle from "./pages/FacturaDetalle.jsx";
import Admin from "./pages/Admin.jsx";

function Privada({ children, roles }) {
  const { usuario, cargando } = useAuth();
  if (cargando) return <div className="cargando">Cargando…</div>;
  if (!usuario) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(usuario.rol))
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
        <Route index element={<Navigate to="/facturas" replace />} />
        <Route path="/facturas" element={<Facturas />} />
        <Route path="/facturas/:id" element={<FacturaDetalle />} />
        <Route
          path="/admin"
          element={
            <Privada roles={["admin"]}>
              <Admin />
            </Privada>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/facturas" replace />} />
    </Routes>
  );
}

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatoFecha } from "../util";

export default function Admin() {
  const [tab, setTab] = useState("usuarios");
  return (
    <div>
      <h1>Administración</h1>
      <div className="tabs">
        {[
          ["usuarios", "Usuarios"],
          ["areas", "Áreas y reglas"],
          ["robot", "Log del robot"],
        ].map(([k, t]) => (
          <button key={k} className={tab === k ? "tab activa" : "tab"} onClick={() => setTab(k)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "usuarios" && <Usuarios />}
      {tab === "areas" && <Areas />}
      {tab === "robot" && <Robot />}
    </div>
  );
}

function Usuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [areas, setAreas] = useState([]);
  const [nuevo, setNuevo] = useState({ email: "", nombre: "", rol: "area", area_id: "", clave: "" });
  const [error, setError] = useState("");

  function cargar() {
    api.get("/api/usuarios").then(setUsuarios).catch(() => {});
    api.get("/api/areas").then(setAreas).catch(() => {});
  }
  useEffect(cargar, []);

  async function crear(e) {
    e.preventDefault();
    setError("");
    try {
      const body = { ...nuevo, area_id: nuevo.area_id ? Number(nuevo.area_id) : null };
      await api.post("/api/usuarios", body);
      setNuevo({ email: "", nombre: "", rol: "area", area_id: "", clave: "" });
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  async function alternarActivo(u) {
    await api.patch(`/api/usuarios/${u.id}`, { activo: !u.activo });
    cargar();
  }

  return (
    <div className="panel">
      <form className="form-linea" onSubmit={crear}>
        <input placeholder="Correo" type="email" value={nuevo.email}
          onChange={(e) => setNuevo({ ...nuevo, email: e.target.value })} required />
        <input placeholder="Nombre" value={nuevo.nombre}
          onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} required />
        <select value={nuevo.rol} onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}>
          <option value="area">Área</option>
          <option value="contabilidad">Contabilidad</option>
          <option value="admin">Admin</option>
        </select>
        <select value={nuevo.area_id} onChange={(e) => setNuevo({ ...nuevo, area_id: e.target.value })}>
          <option value="">Sin área</option>
          {areas.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
        </select>
        <input placeholder="Contraseña" type="text" value={nuevo.clave}
          onChange={(e) => setNuevo({ ...nuevo, clave: e.target.value })} required />
        <button className="btn">Crear usuario</button>
      </form>
      {error && <div className="error">{error}</div>}

      <table className="tabla">
        <thead>
          <tr><th>Nombre</th><th>Correo</th><th>Rol</th><th>Área</th><th>Estado</th><th></th></tr>
        </thead>
        <tbody>
          {usuarios.map((u) => (
            <tr key={u.id}>
              <td>{u.nombre}</td>
              <td className="mono">{u.email}</td>
              <td>{u.rol}</td>
              <td>{areas.find((a) => a.id === u.area_id)?.nombre || "—"}</td>
              <td>{u.activo ? "Activo" : "Inactivo"}</td>
              <td>
                <button className="btn-link" onClick={() => alternarActivo(u)}>
                  {u.activo ? "Desactivar" : "Activar"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Areas() {
  const [areas, setAreas] = useState([]);
  const [reglas, setReglas] = useState([]);
  const [nombre, setNombre] = useState("");
  const [msg, setMsg] = useState("");
  const excelRef = useRef();

  function cargar() {
    api.get("/api/areas").then(setAreas).catch(() => {});
    api.get("/api/areas/reglas").then(setReglas).catch(() => {});
  }
  useEffect(cargar, []);

  async function crearArea(e) {
    e.preventDefault();
    await api.post("/api/areas", { nombre });
    setNombre("");
    cargar();
  }

  async function importar(e) {
    e.preventDefault();
    setMsg("");
    const archivo = excelRef.current.files[0];
    if (!archivo) return;
    const form = new FormData();
    form.append("archivo", archivo);
    try {
      const r = await api.postForm("/api/areas/reglas/importar", form);
      setMsg(`Importadas ${r.reglas_creadas} reglas.`);
      excelRef.current.value = "";
      cargar();
    } catch (err) {
      setMsg("Error: " + err.message);
    }
  }

  return (
    <div className="panel">
      <div className="dos-columnas">
        <div>
          <h3>Áreas</h3>
          <form className="form-linea" onSubmit={crearArea}>
            <input placeholder="Nueva área" value={nombre}
              onChange={(e) => setNombre(e.target.value)} required />
            <button className="btn">Agregar</button>
          </form>
          <ul className="lista">
            {areas.map((a) => <li key={a.id}>{a.nombre}</li>)}
          </ul>
        </div>
        <div>
          <h3>Reglas proveedor → área</h3>
          <form className="form-linea" onSubmit={importar}>
            <input type="file" ref={excelRef} accept=".xlsx,.xls" required />
            <button className="btn">Importar Excel</button>
          </form>
          {msg && <div className="aviso">{msg}</div>}
          <p className="ayuda">
            Columnas esperadas: <code>nit</code>, <code>area</code>, y opcionales{" "}
            <code>patron_item</code>, <code>responsable_email</code>.
          </p>
        </div>
      </div>

      <h3>Reglas actuales ({reglas.length})</h3>
      <table className="tabla">
        <thead><tr><th>Proveedor</th><th>NIT</th><th>Patrón ítem</th><th>Área</th></tr></thead>
        <tbody>
          {reglas.map((r) => (
            <tr key={r.id}>
              <td>{r.proveedor_nombre || "—"}</td>
              <td className="mono">
                {r.proveedor_nit || <span className="sin">sin NIT</span>}
              </td>
              <td>{r.patron_item || <span className="sin">sin definir</span>}</td>
              <td>{areas.find((a) => a.id === r.area_id)?.nombre || r.area_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Robot() {
  const [ejec, setEjec] = useState([]);
  const [sincronizando, setSincronizando] = useState(false);
  const [msg, setMsg] = useState("");

  function cargar() {
    api.get("/api/panel/ejecuciones").then(setEjec).catch(() => {});
  }
  useEffect(cargar, []);

  async function sincronizarAhora() {
    setSincronizando(true);
    setMsg("");
    try {
      const r = await api.post("/api/panel/sincronizar?dias=3");
      setMsg(r.mensaje);
      // el job corre en segundo plano; refrescamos el log cada 5s durante 1 minuto
      let vueltas = 0;
      const intervalo = setInterval(() => {
        cargar();
        vueltas++;
        if (vueltas >= 12) clearInterval(intervalo);
      }, 5000);
    } catch (err) {
      setMsg("Error: " + err.message);
    } finally {
      setSincronizando(false);
    }
  }

  return (
    <div className="panel">
      <div className="form-linea">
        <button className="btn" onClick={sincronizarAhora} disabled={sincronizando}>
          {sincronizando ? "Iniciando…" : "🔄 Sincronizar ahora"}
        </button>
        {msg && <span className="ayuda">{msg}</span>}
      </div>
      <table className="tabla">
        <thead>
          <tr><th>#</th><th>Inicio</th><th>Estado</th><th>Nuevas</th><th>Errores</th><th>Detalle</th></tr>
        </thead>
        <tbody>
          {ejec.map((e) => (
            <tr key={e.id}>
              <td>{e.id}</td>
              <td>{formatoFecha(e.inicio)}</td>
              <td>{e.estado}</td>
              <td>{e.facturas_nuevas}</td>
              <td>{e.errores}</td>
              <td className="detalle-corto">{e.detalle || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

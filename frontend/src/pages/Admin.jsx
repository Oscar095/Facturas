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
          ["roles", "Roles"],
          ["areas", "Áreas y reglas"],
          ["robot", "Log del robot"],
        ].map(([k, t]) => (
          <button key={k} className={tab === k ? "tab activa" : "tab"} onClick={() => setTab(k)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "usuarios" && <Usuarios />}
      {tab === "roles" && <Roles />}
      {tab === "areas" && <Areas />}
      {tab === "robot" && <Robot />}
    </div>
  );
}

// ── Roles y permisos ────────────────────────────────────────────────────────────
const PERMISOS_ROL = [
  ["ver_todas_areas", "Ver todas las áreas", "Sin esto, el usuario solo ve las facturas de su área"],
  ["editar_facturas", "Editar facturas", "Cambiar área, tipo de orden y responsable"],
  ["aprobar", "Procesar y aprobar", "Declarar documentos completos y firmar la aprobación"],
  ["contabilizar", "Contabilizar", "Marcar facturas aprobadas como contabilizadas y ver el log del robot"],
  ["administrar", "Administrar", "Usuarios, roles, áreas, reglas y sincronización"],
];

const ROL_VACIO = {
  nombre: "",
  descripcion: "",
  ver_todas_areas: false,
  editar_facturas: false,
  aprobar: true,
  contabilizar: false,
  administrar: false,
};

function Roles() {
  const [roles, setRoles] = useState([]);
  const [nuevo, setNuevo] = useState(ROL_VACIO);
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState(ROL_VACIO);
  const [error, setError] = useState("");

  function cargar() {
    api.get("/api/roles").then(setRoles).catch((e) => setError(e.message));
  }
  useEffect(cargar, []);

  async function crear(e) {
    e.preventDefault();
    setError("");
    try {
      await api.post("/api/roles", { ...nuevo, descripcion: nuevo.descripcion || null });
      setNuevo(ROL_VACIO);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  function empezarEdicion(r) {
    setEditId(r.id);
    setEdit({ ...r, descripcion: r.descripcion || "" });
  }

  async function guardarEdicion(id) {
    setError("");
    try {
      const { nombre, ...cambios } = edit;
      await api.patch(`/api/roles/${id}`, { ...cambios, descripcion: edit.descripcion || null });
      setEditId(null);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  async function eliminar(r) {
    if (!window.confirm(`¿Eliminar el rol "${r.nombre}"?`)) return;
    setError("");
    try {
      await api.del(`/api/roles/${r.id}`);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  function ChecksPermisos({ valor, onCambio }) {
    return PERMISOS_ROL.map(([campo, texto, ayuda]) => (
      <label key={campo} className="check" title={ayuda}>
        <input
          type="checkbox"
          checked={!!valor[campo]}
          onChange={(e) => onCambio({ ...valor, [campo]: e.target.checked })}
        />
        {texto}
      </label>
    ));
  }

  return (
    <div className="panel">
      <h3>Nuevo rol</h3>
      <form onSubmit={crear}>
        <div className="form-linea">
          <input placeholder="Nombre (ej: aprobador)" value={nuevo.nombre} required
            onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} />
          <input placeholder="Descripción (opcional)" size="40" value={nuevo.descripcion}
            onChange={(e) => setNuevo({ ...nuevo, descripcion: e.target.value })} />
        </div>
        <div className="form-linea permisos-checks">
          <ChecksPermisos valor={nuevo} onCambio={setNuevo} />
          <button className="btn">Crear rol</button>
        </div>
      </form>
      <p className="ayuda">
        Nombre en minúsculas, sin espacios (2–20 caracteres). Los roles de sistema
        (admin, contabilidad, area) no se pueden editar ni eliminar. Un rol solo se
        puede eliminar cuando ningún usuario lo tiene asignado.
      </p>
      {error && <div className="error">{error}</div>}

      <h3>Roles ({roles.length})</h3>
      <table className="tabla">
        <thead>
          <tr>
            <th>Rol</th>
            <th>Descripción</th>
            <th>Permisos</th>
            <th>Usuarios</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {roles.map((r) =>
            editId === r.id ? (
              <tr key={r.id} className="fila-edicion">
                <td>
                  <b>{r.nombre}</b>
                </td>
                <td>
                  <input value={edit.descripcion} size="30"
                    onChange={(e) => setEdit({ ...edit, descripcion: e.target.value })} />
                </td>
                <td className="permisos-checks">
                  <ChecksPermisos valor={edit} onCambio={setEdit} />
                </td>
                <td>{r.en_uso}</td>
                <td>
                  <button className="btn-link" onClick={() => guardarEdicion(r.id)}>Guardar</button>{" "}
                  <button className="btn-link" onClick={() => setEditId(null)}>Cancelar</button>
                </td>
              </tr>
            ) : (
              <tr key={r.id}>
                <td>
                  <b>{r.nombre}</b>
                  {r.es_sistema && <span className="badge sistema">sistema</span>}
                </td>
                <td className="detalle-corto">{r.descripcion || "—"}</td>
                <td>
                  {PERMISOS_ROL.filter(([campo]) => r[campo]).map(([campo, texto]) => (
                    <span key={campo} className="badge permiso" title={texto}>
                      {texto}
                    </span>
                  ))}
                  {!PERMISOS_ROL.some(([campo]) => r[campo]) && (
                    <span className="sin">sin permisos (solo consulta de su área)</span>
                  )}
                </td>
                <td>{r.en_uso}</td>
                <td>
                  {!r.es_sistema && (
                    <>
                      <button className="btn-link" onClick={() => empezarEdicion(r)}>Editar</button>{" "}
                      <button className="btn-link peligro" onClick={() => eliminar(r)}
                        disabled={r.en_uso > 0}
                        title={r.en_uso > 0 ? "Hay usuarios con este rol" : ""}>
                        Eliminar
                      </button>
                    </>
                  )}
                </td>
              </tr>
            )
          )}
        </tbody>
      </table>
    </div>
  );
}

function Usuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [areas, setAreas] = useState([]);
  const [roles, setRoles] = useState([]);
  const [nuevo, setNuevo] = useState({ email: "", nombre: "", rol: "area", area_id: "", clave: "" });
  const [error, setError] = useState("");

  function cargar() {
    api.get("/api/usuarios").then(setUsuarios).catch(() => {});
    api.get("/api/areas").then(setAreas).catch(() => {});
    api.get("/api/roles").then(setRoles).catch(() => setRoles([]));
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

  async function cambiarRol(u, rol) {
    setError("");
    try {
      await api.patch(`/api/usuarios/${u.id}`, { rol });
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="panel">
      <form className="form-linea" onSubmit={crear}>
        <input placeholder="Correo" type="email" value={nuevo.email}
          onChange={(e) => setNuevo({ ...nuevo, email: e.target.value })} required />
        <input placeholder="Nombre" value={nuevo.nombre}
          onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} required />
        <select value={nuevo.rol} onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}>
          {roles.length === 0 ? (
            <option value="area">area</option>
          ) : (
            roles.map((r) => (
              <option key={r.id} value={r.nombre} title={r.descripcion || ""}>
                {r.nombre}
              </option>
            ))
          )}
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
              <td>
                {roles.length === 0 ? (
                  u.rol
                ) : (
                  <select className="select-rol" value={u.rol}
                    onChange={(e) => cambiarRol(u, e.target.value)}>
                    {roles.map((r) => (
                      <option key={r.id} value={r.nombre}>{r.nombre}</option>
                    ))}
                  </select>
                )}
              </td>
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

const REGLA_VACIA = { proveedor_nombre: "", proveedor_nit: "", patron_item: "", area_id: "" };

function Areas() {
  const [areas, setAreas] = useState([]);
  const [reglas, setReglas] = useState([]);
  const [nombre, setNombre] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState("");
  const [nueva, setNueva] = useState(REGLA_VACIA);
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState(REGLA_VACIA);
  const [conIA, setConIA] = useState(false);
  const [reaplicando, setReaplicando] = useState(false);
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

  async function crearRegla(e) {
    e.preventDefault();
    setError("");
    try {
      await api.post("/api/areas/reglas", {
        proveedor_nombre: nueva.proveedor_nombre || null,
        proveedor_nit: nueva.proveedor_nit || null,
        patron_item: nueva.patron_item || null,
        area_id: Number(nueva.area_id),
      });
      setNueva(REGLA_VACIA);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  function empezarEdicion(r) {
    setEditId(r.id);
    setEdit({
      proveedor_nombre: r.proveedor_nombre || "",
      proveedor_nit: r.proveedor_nit || "",
      patron_item: r.patron_item || "",
      area_id: r.area_id,
    });
  }

  async function guardarEdicion(id) {
    setError("");
    try {
      await api.patch(`/api/areas/reglas/${id}`, {
        proveedor_nombre: edit.proveedor_nombre || null,
        proveedor_nit: edit.proveedor_nit || null,
        patron_item: edit.patron_item || null,
        area_id: Number(edit.area_id),
      });
      setEditId(null);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  async function eliminarRegla(r) {
    if (!window.confirm(`¿Eliminar la regla de ${r.proveedor_nombre || r.proveedor_nit || "este proveedor"}?`)) return;
    setError("");
    try {
      await api.del(`/api/areas/reglas/${r.id}`);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  async function reaplicar() {
    setReaplicando(true);
    setError("");
    setMsg("");
    try {
      const r = await api.post(`/api/areas/reglas/reaplicar?usar_ia=${conIA}`);
      setMsg(`Reaplicado: ${r.asignadas} de ${r.revisadas} facturas sin área quedaron asignadas.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setReaplicando(false);
    }
  }

  const f = filtro.trim().toLowerCase();
  const reglasFiltradas = f
    ? reglas.filter((r) => {
        const area = areas.find((a) => a.id === r.area_id)?.nombre || "";
        return [r.proveedor_nombre, r.proveedor_nit, r.patron_item, area]
          .some((v) => (v || "").toLowerCase().includes(f));
      })
    : reglas;

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
          <h3>Importar reglas (Excel)</h3>
          <form className="form-linea" onSubmit={importar}>
            <input type="file" ref={excelRef} accept=".xlsx,.xls" required />
            <button className="btn">Importar Excel</button>
          </form>
          <p className="ayuda">
            Columnas: <code>nit</code>, <code>area</code>, y opcionales{" "}
            <code>patron_item</code>, <code>responsable_email</code>.
          </p>
        </div>
      </div>

      <h3>Nueva regla proveedor → área</h3>
      <form className="form-linea" onSubmit={crearRegla}>
        <input placeholder="Proveedor" value={nueva.proveedor_nombre}
          onChange={(e) => setNueva({ ...nueva, proveedor_nombre: e.target.value })} />
        <input placeholder="NIT" value={nueva.proveedor_nit}
          onChange={(e) => setNueva({ ...nueva, proveedor_nit: e.target.value })} />
        <input placeholder="Patrón de ítem (opcional)" value={nueva.patron_item}
          onChange={(e) => setNueva({ ...nueva, patron_item: e.target.value })} />
        <select value={nueva.area_id} required
          onChange={(e) => setNueva({ ...nueva, area_id: e.target.value })}>
          <option value="" disabled>Área…</option>
          {areas.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
        </select>
        <button className="btn">Crear regla</button>
      </form>
      <p className="ayuda">
        Si el proveedor tiene una sola área, se asigna directo. Si tiene varias, se busca el{" "}
        <b>patrón</b> (palabra o frase del ítem) en el texto del PDF de la factura; una regla{" "}
        <b>sin patrón</b> actúa como área por defecto del proveedor. Si nada decide, la factura
        queda sin área (o la sugiere la IA si la activas al reaplicar).
      </p>

      <div className="form-linea">
        <button className="btn" onClick={reaplicar} disabled={reaplicando}>
          {reaplicando ? "Reaplicando…" : "Reaplicar reglas a facturas sin área"}
        </button>
        <label className="ayuda">
          <input type="checkbox" checked={conIA} onChange={(e) => setConIA(e.target.checked)} />{" "}
          usar IA si el patrón no decide (gasta créditos)
        </label>
      </div>
      {msg && <div className="aviso">{msg}</div>}
      {error && <div className="error">{error}</div>}

      <h3>Reglas actuales ({reglasFiltradas.length}{f ? ` de ${reglas.length}` : ""})</h3>
      <input className="buscador" placeholder="Filtrar por proveedor, NIT, patrón o área…"
        value={filtro} onChange={(e) => setFiltro(e.target.value)} />
      <table className="tabla">
        <thead>
          <tr><th>Proveedor</th><th>NIT</th><th>Patrón ítem</th><th>Área</th><th></th></tr>
        </thead>
        <tbody>
          {reglasFiltradas.map((r) =>
            editId === r.id ? (
              <tr key={r.id} className="fila-edicion">
                <td><input value={edit.proveedor_nombre}
                  onChange={(e) => setEdit({ ...edit, proveedor_nombre: e.target.value })} /></td>
                <td><input value={edit.proveedor_nit}
                  onChange={(e) => setEdit({ ...edit, proveedor_nit: e.target.value })} /></td>
                <td><input value={edit.patron_item} placeholder="sin patrón"
                  onChange={(e) => setEdit({ ...edit, patron_item: e.target.value })} /></td>
                <td>
                  <select value={edit.area_id}
                    onChange={(e) => setEdit({ ...edit, area_id: e.target.value })}>
                    {areas.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
                  </select>
                </td>
                <td>
                  <button className="btn-link" onClick={() => guardarEdicion(r.id)}>Guardar</button>{" "}
                  <button className="btn-link" onClick={() => setEditId(null)}>Cancelar</button>
                </td>
              </tr>
            ) : (
              <tr key={r.id}>
                <td>{r.proveedor_nombre || "—"}</td>
                <td className="mono">
                  {r.proveedor_nit || <span className="sin">sin NIT</span>}
                </td>
                <td>{r.patron_item || <span className="sin">sin patrón</span>}</td>
                <td>{areas.find((a) => a.id === r.area_id)?.nombre || r.area_id}</td>
                <td>
                  <button className="btn-link" onClick={() => empezarEdicion(r)}>Editar</button>{" "}
                  <button className="btn-link peligro" onClick={() => eliminarRegla(r)}>Eliminar</button>
                </td>
              </tr>
            )
          )}
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

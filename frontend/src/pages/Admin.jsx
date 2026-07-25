import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { api } from "../api";
import { formatoFecha } from "../util";

// ── helpers compartidos por el editor de usuarios ──────────────────────────────
const AVATAR_COLORES = ["#009fe3", "#f28c30", "#2e7d55", "#7c5cbf", "#dc4c4c", "#1a365d"];
function colorAvatar(texto = "") {
  let h = 0;
  for (let i = 0; i < texto.length; i++) h = (h * 31 + texto.charCodeAt(i)) | 0;
  return AVATAR_COLORES[Math.abs(h) % AVATAR_COLORES.length];
}
function iniciales(nombre = "") {
  const partes = nombre.trim().split(/\s+/);
  return ((partes[0]?.[0] || "") + (partes[1]?.[0] || "")).toUpperCase() || "?";
}
function generarClave() {
  const may = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const min = "abcdefghijkmnpqrstuvwxyz";
  const num = "23456789";
  const sim = "!@#$%*?";
  const todos = may + min + num + sim;
  let clave =
    may[Math.floor(Math.random() * may.length)] +
    num[Math.floor(Math.random() * num.length)] +
    sim[Math.floor(Math.random() * sim.length)];
  for (let i = 0; i < 9; i++) clave += todos[Math.floor(Math.random() * todos.length)];
  return clave
    .split("")
    .sort(() => Math.random() - 0.5)
    .join("");
}
function fuerzaClave(clave) {
  let score = 0;
  if (clave.length >= 8) score++;
  if (clave.length >= 12) score++;
  if (/[a-z]/.test(clave) && /[A-Z]/.test(clave)) score++;
  if (/\d/.test(clave)) score++;
  if (/[^A-Za-z0-9]/.test(clave)) score++;
  return Math.min(score, 4);
}
const FUERZA_TEXTOS = ["Muy débil", "Débil", "Aceptable", "Fuerte", "Muy fuerte"];
const FUERZA_COLORES = ["var(--ladrillo)", "var(--rust)", "var(--oro)", "var(--salvia)", "var(--marca)"];
const FORM_VACIO = { email: "", nombre: "", rol: "area", area_id: "", clave: "", activo: true };

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

function claseRol(roles, nombreRol) {
  const r = roles.find((x) => x.nombre === nombreRol);
  if (!r) return "badge tipo";
  if (r.administrar) return "badge rol-admin";
  if (r.contabilizar) return "badge rol-conta";
  if (r.aprobar) return "badge rol-aprueba";
  return "badge tipo";
}

function Usuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [areas, setAreas] = useState([]);
  const [roles, setRoles] = useState([]);
  const [buscar, setBuscar] = useState("");
  const [abierto, setAbierto] = useState(false);
  const [editando, setEditando] = useState(null);
  const [form, setForm] = useState(FORM_VACIO);
  const [mostrarClave, setMostrarClave] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  function cargar() {
    api.get("/api/usuarios").then(setUsuarios).catch(() => {});
    api.get("/api/areas").then(setAreas).catch(() => {});
    api.get("/api/roles").then(setRoles).catch(() => setRoles([]));
  }
  useEffect(cargar, []);

  function nuevoUsuario() {
    setEditando(null);
    setForm({ ...FORM_VACIO, rol: roles[0]?.nombre || "area", clave: generarClave() });
    setMostrarClave(false);
    setError("");
    setAbierto(true);
  }

  function editarUsuario(u) {
    setEditando(u);
    setForm({ email: u.email, nombre: u.nombre, rol: u.rol, area_id: u.area_id ?? "", clave: "", activo: u.activo });
    setMostrarClave(false);
    setError("");
    setAbierto(true);
  }

  async function guardar(e) {
    e.preventDefault();
    setError("");
    setGuardando(true);
    try {
      const area_id = form.area_id ? Number(form.area_id) : null;
      if (editando) {
        const cambios = { nombre: form.nombre, rol: form.rol, area_id, activo: form.activo };
        if (form.clave) cambios.clave = form.clave;
        await api.patch(`/api/usuarios/${editando.id}`, cambios);
      } else {
        await api.post("/api/usuarios", {
          email: form.email,
          nombre: form.nombre,
          rol: form.rol,
          area_id,
          clave: form.clave,
        });
      }
      setAbierto(false);
      cargar();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  const b = buscar.trim().toLowerCase();
  const usuariosFiltrados = b
    ? usuarios.filter((u) => `${u.nombre} ${u.email}`.toLowerCase().includes(b))
    : usuarios;
  const rolesDisponibles = roles.length
    ? roles
    : [{ nombre: "area", descripcion: "", administrar: false, contabilizar: false, aprobar: true, editar_facturas: false, ver_todas_areas: false }];

  return (
    <div className="panel">
      <div className="usuarios-header">
        <input
          className="buscador"
          style={{ margin: 0 }}
          placeholder="Buscar por nombre o correo…"
          value={buscar}
          onChange={(e) => setBuscar(e.target.value)}
        />
        <button className="btn" onClick={nuevoUsuario}>
          + Nuevo usuario
        </button>
      </div>

      <table className="tabla">
        <thead>
          <tr>
            <th>Usuario</th>
            <th>Rol</th>
            <th>Área</th>
            <th>Estado</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {usuariosFiltrados.length === 0 ? (
            <tr>
              <td colSpan="5" className="vacio">
                Sin resultados.
              </td>
            </tr>
          ) : (
            usuariosFiltrados.map((u) => (
              <tr key={u.id}>
                <td>
                  <div className="fila-usuario">
                    <div className="avatar" style={{ background: colorAvatar(u.nombre) }}>
                      {iniciales(u.nombre)}
                    </div>
                    <div>
                      <div className="prov">{u.nombre}</div>
                      <div className="prov-nit">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <span className={claseRol(roles, u.rol)}>{u.rol}</span>
                </td>
                <td>{areas.find((a) => a.id === u.area_id)?.nombre || "—"}</td>
                <td>
                  <span className={`badge ${u.activo ? "e-lista" : "e-nueva"}`}>
                    {u.activo ? "Activo" : "Inactivo"}
                  </span>
                </td>
                <td>
                  <button className="btn-link" onClick={() => editarUsuario(u)}>
                    Editar
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <AnimatePresence>
        {abierto && (
          <motion.div
            className="drawer-fondo"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setAbierto(false)}
          >
            <motion.form
              className="drawer-panel"
              onClick={(e) => e.stopPropagation()}
              onSubmit={guardar}
              initial={{ x: 48, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 48, opacity: 0 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            >
              <div className="drawer-cabecera">
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <div className="avatar-grande" style={{ background: colorAvatar(form.nombre || "?") }}>
                    {iniciales(form.nombre || "?")}
                  </div>
                  <div>
                    <h3 style={{ margin: 0 }}>{editando ? "Editar usuario" : "Nuevo usuario"}</h3>
                    <p className="ayuda" style={{ margin: 0 }}>
                      {editando ? editando.email : "Crea el acceso al portal"}
                    </p>
                  </div>
                </div>
                <button type="button" className="drawer-cerrar" onClick={() => setAbierto(false)}>
                  ✕
                </button>
              </div>

              <div className="campo">
                <label>Correo</label>
                <input
                  type="email"
                  value={form.email}
                  required
                  disabled={!!editando}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>

              <div className="campo">
                <label>Nombre</label>
                <input
                  value={form.nombre}
                  required
                  onChange={(e) => setForm({ ...form, nombre: e.target.value })}
                />
              </div>

              <div className="campo">
                <label>Rol</label>
                <div className="roles-grid">
                  {rolesDisponibles.map((r) => (
                    <div
                      key={r.nombre}
                      className={`rol-card ${form.rol === r.nombre ? "activo" : ""}`}
                      onClick={() => setForm({ ...form, rol: r.nombre })}
                    >
                      <div className="rol-card-nombre">{r.nombre}</div>
                      <div className="rol-card-permisos">
                        {PERMISOS_ROL.filter(([campo]) => r[campo]).map(([campo, texto]) => (
                          <span key={campo} className="badge permiso">
                            {texto}
                          </span>
                        ))}
                        {!PERMISOS_ROL.some(([campo]) => r[campo]) && (
                          <span className="sin">solo su área</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="campo">
                <label>Área</label>
                <select value={form.area_id} onChange={(e) => setForm({ ...form, area_id: e.target.value })}>
                  <option value="">Sin área</option>
                  {areas.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.nombre}
                    </option>
                  ))}
                </select>
              </div>

              <div className="campo">
                <label>{editando ? "Restablecer contraseña" : "Contraseña"}</label>
                <div className="clave-campo">
                  <input
                    type={mostrarClave ? "text" : "password"}
                    value={form.clave}
                    placeholder={editando ? "dejar en blanco para no cambiarla" : ""}
                    required={!editando}
                    onChange={(e) => setForm({ ...form, clave: e.target.value })}
                  />
                  <div className="clave-acciones">
                    <button
                      type="button"
                      className="clave-icono-btn"
                      title="Generar contraseña segura"
                      onClick={() => setForm({ ...form, clave: generarClave() })}
                    >
                      🎲
                    </button>
                    <button
                      type="button"
                      className="clave-icono-btn"
                      title="Mostrar u ocultar"
                      onClick={() => setMostrarClave((v) => !v)}
                    >
                      {mostrarClave ? "🙈" : "👁"}
                    </button>
                  </div>
                </div>
                {form.clave && (
                  <>
                    <div className="fuerza-barra">
                      <div
                        className="fuerza-relleno"
                        style={{
                          width: `${(fuerzaClave(form.clave) + 1) * 20}%`,
                          background: FUERZA_COLORES[fuerzaClave(form.clave)],
                        }}
                      />
                    </div>
                    <span className="fuerza-texto">{FUERZA_TEXTOS[fuerzaClave(form.clave)]}</span>
                  </>
                )}
              </div>

              {editando && (
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={form.activo}
                    onChange={(e) => setForm({ ...form, activo: e.target.checked })}
                  />
                  <span className="switch-pista" />
                  {form.activo ? "Usuario activo" : "Usuario inactivo"}
                </label>
              )}

              {error && <div className="error">{error}</div>}

              <div className="drawer-acciones">
                <button type="button" className="btn-sec" onClick={() => setAbierto(false)}>
                  Cancelar
                </button>
                <button className="btn" disabled={guardando}>
                  {guardando ? "Guardando…" : editando ? "Guardar cambios" : "Crear usuario"}
                </button>
              </div>
            </motion.form>
          </motion.div>
        )}
      </AnimatePresence>
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

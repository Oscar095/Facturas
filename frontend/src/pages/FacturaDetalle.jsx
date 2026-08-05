import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, getToken } from "../api";
import { useAuth } from "../auth.jsx";
import { badgeEstado, formatoFecha, formatoPesos, tienePermiso } from "../util";

const TIPOS_CARGA = [
  { valor: "OCN", texto: "Orden de Compra (OCN)" },
  { valor: "OCS", texto: "Orden de Servicio (OCS)" },
  { valor: "CRN", texto: "Recepción de Mercancía (CRN)" },
  { valor: "OTRO", texto: "Otro documento" },
];

export default function FacturaDetalle() {
  const { id } = useParams();
  const { usuario } = useAuth();
  const navigate = useNavigate();
  const [factura, setFactura] = useState(null);
  const [areas, setAreas] = useState([]);
  const [error, setError] = useState("");
  const [subiendo, setSubiendo] = useState(false);
  const [cambiandoArea, setCambiandoArea] = useState(false);
  const [tipoCarga, setTipoCarga] = useState("OCN");
  const archivoRef = useRef();

  const puedeEditar = tienePermiso(usuario, "editar_facturas");
  const puedeAprobar = tienePermiso(usuario, "aprobar");
  const puedeContabilizar = tienePermiso(usuario, "contabilizar");

  function cargar() {
    api.get(`/api/facturas/${id}`).then(setFactura).catch((e) => setError(e.message));
  }
  useEffect(cargar, [id]);
  useEffect(() => {
    if (puedeEditar) api.get("/api/areas").then(setAreas).catch(() => setAreas([]));
  }, [puedeEditar]);

  async function cambiarArea(e) {
    const area_id = Number(e.target.value);
    if (!area_id) return;
    setCambiandoArea(true);
    setError("");
    try {
      setFactura(await api.patch(`/api/facturas/${id}`, { area_id }));
    } catch (err) {
      setError(err.message);
    } finally {
      setCambiandoArea(false);
    }
  }

  async function subir(e) {
    e.preventDefault();
    setError("");
    const archivo = archivoRef.current.files[0];
    if (!archivo) return;
    setSubiendo(true);
    try {
      const form = new FormData();
      form.append("tipo", tipoCarga);
      form.append("archivo", archivo);
      const actualizada = await api.postForm(`/api/documentos/${id}`, form);
      setFactura(actualizada);
      archivoRef.current.value = "";
    } catch (err) {
      setError(err.message);
    } finally {
      setSubiendo(false);
    }
  }

  async function eliminarDoc(docId) {
    if (!confirm("¿Eliminar este documento?")) return;
    try {
      setFactura(await api.del(`/api/documentos/${docId}`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function procesar() {
    const mensaje = factura.faltantes?.length
      ? `Según las reglas faltan: ${factura.faltantes.join(", ")}.\n\n¿Confirmas que esta factura NO requiere esos documentos y ya está lista para contabilizar?`
      : "¿Confirmas que los documentos están completos y la factura queda lista para contabilizar?";
    if (!confirm(mensaje)) return;
    setError("");
    try {
      setFactura(await api.post(`/api/facturas/${id}/procesar`));
    } catch (err) {
      setError(err.message);
    }
  }

  const [panelAprobar, setPanelAprobar] = useState(false);
  const [firmas, setFirmas] = useState([]);
  const [firmaSel, setFirmaSel] = useState("");
  const [aprobando, setAprobando] = useState(false);

  async function abrirAprobacion() {
    setError("");
    try {
      const lista = await api.get("/api/firmas");
      setFirmas(lista);
      setFirmaSel(lista.length ? String(lista[0].id) : "");
      setPanelAprobar(true);
    } catch (err) {
      setError(err.message);
    }
  }

  async function aprobar() {
    setAprobando(true);
    setError("");
    try {
      setFactura(await api.post(`/api/facturas/${id}/aprobar`, { firma_id: Number(firmaSel) }));
      setPanelAprobar(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setAprobando(false);
    }
  }

  async function contabilizar() {
    try {
      setFactura(await api.post(`/api/facturas/${id}/contabilizar`));
    } catch (err) {
      setError(err.message);
    }
  }

  function abrirArchivo(url) {
    // Abre el PDF/documento pasando el token (el backend hace proxy o redirige a SAS)
    fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.blob())
      .then((b) => window.open(URL.createObjectURL(b), "_blank"))
      .catch(() => setError("No se pudo abrir el archivo"));
  }

  if (error && !factura) return <div className="error">{error}</div>;
  if (!factura) return <div className="cargando">Cargando…</div>;

  const b = badgeEstado(factura.estado_proceso);

  return (
    <div className="detalle">
      <button className="volver" onClick={() => navigate(-1)}>
        ← Volver
      </button>

      <div className="detalle-cabecera">
        <div>
          <h1>{factura.numero}</h1>
          <div className="prov-grande">{factura.proveedor.razon_social}</div>
          <div className="prov-nit">NIT {factura.proveedor.nit}</div>
        </div>
        <span className={`badge grande ${b.clase}`}>{b.texto}</span>
      </div>

      <div className="detalle-datos">
        <div>
          <span className="etiqueta">Valor</span>
          <span className="valor">{formatoPesos(factura.valor_total)}</span>
        </div>
        {factura.moneda === "USD" && (
          <div>
            <span className="etiqueta">Moneda original</span>
            <span className="valor">
              USD {factura.valor_original ?? "—"} · TRM {factura.trm ?? "—"}
            </span>
          </div>
        )}
        <div>
          <span className="etiqueta">Emisión</span>
          <span className="valor">{formatoFecha(factura.fecha_emision)}</span>
        </div>
        <div>
          <span className="etiqueta">Vencimiento</span>
          <span className="valor">{formatoFecha(factura.fecha_vencimiento)}</span>
        </div>
        <div>
          <span className="etiqueta">Recepción</span>
          <span className="valor">{formatoFecha(factura.fecha_recepcion)}</span>
        </div>
        <div>
          <span className="etiqueta">Área</span>
          {puedeEditar ? (
            <select
              className="select-area"
              value={factura.area?.id || ""}
              onChange={cambiarArea}
              disabled={cambiandoArea}
            >
              <option value="" disabled>
                {factura.area?.nombre ? "Cambiar área…" : "Sin asignar — elegir área"}
              </option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre}
                </option>
              ))}
            </select>
          ) : (
            <span className="valor">{factura.area?.nombre || "sin asignar"}</span>
          )}
        </div>
        <div>
          <span className="etiqueta">Tipo de orden</span>
          <span className="valor">{factura.tipo_orden || "—"}</span>
        </div>
        <div>
          <span className="etiqueta">Origen</span>
          <span className="valor">
            {factura.origen === "manual" ? "📤 Carga manual" : "Portal Siesa"}
          </span>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {factura.faltantes?.length > 0 &&
        !["procesada", "aprobada", "contabilizada"].includes(factura.estado_proceso) && (
          <div className="aviso">
            ⚠️ Según las reglas faltan: <b>{factura.faltantes.join(", ")}</b> — si esta
            factura no los requiere, puedes procesarla de todas formas.
          </div>
        )}

      <h2>Documentos</h2>
      <table className="tabla">
        <thead>
          <tr>
            <th>Tipo</th>
            <th>Archivo</th>
            <th>Fecha</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {factura.documentos.map((d) => (
            <tr key={d.id}>
              <td>
                <span className="badge tipo">{d.tipo}</span>
              </td>
              <td>
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    abrirArchivo(`/api/facturas/documento/${d.id}/archivo`);
                  }}
                >
                  {d.nombre_archivo}
                </a>
              </td>
              <td>{formatoFecha(d.fecha)}</td>
              <td>
                {d.tipo !== "FV" && (
                  <button className="btn-link peligro" onClick={() => eliminarDoc(d.id)}>
                    Eliminar
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="acciones">
        <form className="cargar" onSubmit={subir}>
          <h3>Cargar documento</h3>
          <div className="cargar-fila">
            <select value={tipoCarga} onChange={(e) => setTipoCarga(e.target.value)}>
              {TIPOS_CARGA.map((t) => (
                <option key={t.valor} value={t.valor}>
                  {t.texto}
                </option>
              ))}
            </select>
            <input type="file" ref={archivoRef} required />
            <button className="btn" disabled={subiendo}>
              {subiendo ? "Subiendo…" : "Subir"}
            </button>
          </div>
        </form>

        {puedeAprobar &&
          ["asignada", "docs_pendientes", "lista_contabilizar"].includes(factura.estado_proceso) &&
          factura.area && (
            <button className="btn" onClick={procesar}>
              ✓ Procesar
            </button>
          )}
        {puedeAprobar && factura.estado_proceso === "procesada" && !panelAprobar && (
          <button className="btn exito" onClick={abrirAprobacion}>
            ✍️ Aprobar factura
          </button>
        )}
        {panelAprobar && (
          <div className="aprobar-panel">
            <h3>Firmar y aprobar</h3>
            <p className="ayuda">
              Tu firma se estampará en todas las páginas de todos los documentos
              PDF adjuntos a la factura, en la esquina inferior derecha.
            </p>
            {firmas.length === 0 ? (
              <p className="ayuda">
                No tienes firmas guardadas. Súbela primero en{" "}
                <Link to="/firmas">Mis Firmas</Link>.
              </p>
            ) : (
              <select value={firmaSel} onChange={(e) => setFirmaSel(e.target.value)}>
                {firmas.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.nombre} ({f.nombre_archivo})
                  </option>
                ))}
              </select>
            )}
            <div className="aprobar-acciones">
              {firmas.length > 0 && (
                <button className="btn exito" onClick={aprobar} disabled={aprobando}>
                  {aprobando ? "Firmando…" : "Firmar y aprobar"}
                </button>
              )}
              <button className="btn-sec" onClick={() => setPanelAprobar(false)} disabled={aprobando}>
                Cancelar
              </button>
            </div>
          </div>
        )}
        {puedeContabilizar && factura.estado_proceso === "aprobada" && (
          <button className="btn exito" onClick={contabilizar}>
            ✓ Marcar como contabilizada
          </button>
        )}
      </div>
    </div>
  );
}

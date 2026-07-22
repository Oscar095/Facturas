import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, getToken } from "../api";
import { useAuth } from "../auth.jsx";
import { badgeEstado, formatoFecha, formatoPesos } from "../util";

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

  const esGestion = usuario?.rol === "admin" || usuario?.rol === "contabilidad";

  function cargar() {
    api.get(`/api/facturas/${id}`).then(setFactura).catch((e) => setError(e.message));
  }
  useEffect(cargar, [id]);
  useEffect(() => {
    if (esGestion) api.get("/api/areas").then(setAreas).catch(() => setAreas([]));
  }, [esGestion]);

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
        <div>
          <span className="etiqueta">Emisión</span>
          <span className="valor">{formatoFecha(factura.fecha_emision)}</span>
        </div>
        <div>
          <span className="etiqueta">Recepción</span>
          <span className="valor">{formatoFecha(factura.fecha_recepcion)}</span>
        </div>
        <div>
          <span className="etiqueta">Área</span>
          {esGestion ? (
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
      </div>

      {error && <div className="error">{error}</div>}

      {factura.faltantes?.length > 0 && (
        <div className="aviso">
          ⚠️ Faltan documentos para contabilizar: <b>{factura.faltantes.join(", ")}</b>
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

        {esGestion && factura.estado_proceso === "lista_contabilizar" && (
          <button className="btn exito" onClick={contabilizar}>
            ✓ Marcar como contabilizada
          </button>
        )}
      </div>
    </div>
  );
}

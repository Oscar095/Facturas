import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

const CAMPOS_VACIOS = {
  nit: "",
  razon_social: "",
  numero: "",
  cufe: "",
  fecha_emision: "",
  valor_total: "",
  iva: "",
};

export default function CargarFactura() {
  const navigate = useNavigate();
  const archivoRef = useRef();
  const [nombreArchivo, setNombreArchivo] = useState("");
  const [campos, setCampos] = useState(CAMPOS_VACIOS);
  const [advertencias, setAdvertencias] = useState([]);
  const [extraido, setExtraido] = useState(false);
  const [extrayendo, setExtrayendo] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  function set(campo, valor) {
    setCampos((c) => ({ ...c, [campo]: valor }));
  }

  function alElegirArchivo() {
    const archivo = archivoRef.current.files[0];
    setNombreArchivo(archivo ? archivo.name : "");
    setCampos(CAMPOS_VACIOS);
    setAdvertencias([]);
    setExtraido(false);
    setError("");
  }

  async function extraer() {
    const archivo = archivoRef.current.files[0];
    if (!archivo) return;
    setExtrayendo(true);
    setError("");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const d = await api.postForm("/api/facturas/carga/extraer", form);
      setCampos({
        nit: d.nit || "",
        razon_social: d.razon_social || "",
        numero: d.numero || "",
        cufe: d.cufe || "",
        fecha_emision: d.fecha_emision || "",
        valor_total: d.valor_total ?? "",
        iva: d.iva ?? "",
      });
      setAdvertencias(d.advertencias || []);
      setExtraido(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setExtrayendo(false);
    }
  }

  async function guardar(e) {
    e.preventDefault();
    const archivo = archivoRef.current.files[0];
    if (!archivo) {
      setError("Selecciona el PDF de la factura");
      return;
    }
    setGuardando(true);
    setError("");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      for (const [campo, valor] of Object.entries(campos)) {
        if (String(valor).trim() !== "") form.append(campo, valor);
      }
      const factura = await api.postForm("/api/facturas/carga", form);
      navigate(`/facturas/${factura.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="carga-manual">
      <h1>Cargar factura</h1>
      <p className="ayuda">
        Para facturas que NO llegan por el portal Siesa (físicas o de correo).
        Sube el PDF, la IA pre-llena los datos, tú los revisas y al guardar la
        factura entra al mismo flujo de todas: área, documentos y aprobación.
      </p>

      <div className="panel">
        <div className="cargar-fila">
          <input
            type="file"
            accept=".pdf,application/pdf"
            ref={archivoRef}
            onChange={alElegirArchivo}
          />
          <button
            type="button"
            className="btn"
            onClick={extraer}
            disabled={!nombreArchivo || extrayendo}
          >
            {extrayendo ? "Leyendo con IA…" : "🤖 Extraer datos con IA"}
          </button>
        </div>

        {error && <div className="error">{error}</div>}
        {advertencias.map((a, i) => (
          <div key={i} className="aviso">
            ⚠️ {a}
          </div>
        ))}
        {extraido && advertencias.length === 0 && (
          <div className="aviso ok">
            ✓ Datos extraídos del PDF — revísalos y corrige lo que haga falta antes de guardar.
          </div>
        )}

        <form className="carga-form" onSubmit={guardar}>
          <label>
            NIT del proveedor *
            <input
              value={campos.nit}
              onChange={(e) => set("nit", e.target.value)}
              placeholder="Solo dígitos, sin DV"
              required
            />
          </label>
          <label>
            Razón social del proveedor *
            <input
              value={campos.razon_social}
              onChange={(e) => set("razon_social", e.target.value)}
              required
            />
          </label>
          <label>
            Número de factura *
            <input
              value={campos.numero}
              onChange={(e) => set("numero", e.target.value)}
              placeholder="Con prefijo, ej: FVE12345"
              required
            />
          </label>
          <label>
            Fecha de emisión
            <input
              type="date"
              value={campos.fecha_emision}
              onChange={(e) => set("fecha_emision", e.target.value)}
            />
          </label>
          <label>
            Valor total
            <input
              type="number"
              step="0.01"
              min="0"
              value={campos.valor_total}
              onChange={(e) => set("valor_total", e.target.value)}
            />
          </label>
          <label>
            IVA
            <input
              type="number"
              step="0.01"
              min="0"
              value={campos.iva}
              onChange={(e) => set("iva", e.target.value)}
            />
          </label>
          <label className="carga-cufe">
            CUFE (si aparece en la factura)
            <input
              value={campos.cufe}
              onChange={(e) => set("cufe", e.target.value)}
              placeholder="Hash largo de la factura electrónica — evita duplicados"
            />
          </label>
          <div className="carga-acciones">
            <button className="btn exito" disabled={guardando || !nombreArchivo}>
              {guardando ? "Guardando…" : "Guardar factura"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

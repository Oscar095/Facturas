import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { formatoPesos } from "../util";

const CAMPOS_VACIOS = {
  nit: "",
  razon_social: "",
  numero: "",
  cufe: "",
  fecha_emision: "",
  fecha_vencimiento: "",
  valor_total: "",
  iva: "",
  moneda: "COP",
  trm: "",
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

  const esUSD = campos.moneda === "USD";

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
        fecha_vencimiento: d.fecha_vencimiento || "",
        valor_total: d.valor_total ?? "",
        iva: d.iva ?? "",
        moneda: d.moneda || "COP",
        trm: d.trm ?? "",
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
            Fecha de vencimiento
            <input
              type="date"
              value={campos.fecha_vencimiento}
              onChange={(e) => set("fecha_vencimiento", e.target.value)}
            />
          </label>
          <label>
            Moneda de la factura
            <select value={campos.moneda} onChange={(e) => set("moneda", e.target.value)}>
              <option value="COP">COP — Pesos colombianos</option>
              <option value="USD">USD — Dólares</option>
            </select>
          </label>
          {esUSD && (
            <label>
              TRM (pesos por dólar) *
              <input
                type="number"
                step="0.0001"
                min="0"
                value={campos.trm}
                onChange={(e) => set("trm", e.target.value)}
                placeholder="Tasa de cambio de la factura"
                required
              />
            </label>
          )}
          <label>
            Valor total {esUSD ? "(en USD)" : ""}
            <input
              type="number"
              step="0.01"
              min="0"
              value={campos.valor_total}
              onChange={(e) => set("valor_total", e.target.value)}
            />
          </label>
          <label>
            IVA {esUSD ? "(en USD)" : ""}
            <input
              type="number"
              step="0.01"
              min="0"
              value={campos.iva}
              onChange={(e) => set("iva", e.target.value)}
            />
          </label>
          {esUSD && (
            <div className="aviso carga-conversion">
              💱 Se guardará en pesos:{" "}
              <b>
                {campos.valor_total && campos.trm
                  ? formatoPesos(Number(campos.valor_total) * Number(campos.trm))
                  : "— diligencia valor y TRM"}
              </b>{" "}
              (USD {campos.valor_total || "—"} × TRM {campos.trm || "—"}). El valor en
              dólares queda guardado como referencia.
            </div>
          )}
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

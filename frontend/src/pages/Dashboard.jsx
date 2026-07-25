import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { badgeEstado, formatoFecha, formatoPesos, formatoPesosCompacto } from "../util";

const PERIODOS = [
  ["mes", "Mes actual"],
  ["trimestre", "Últimos 90 días"],
  ["anio", "Este año"],
  ["todo", "Todo"],
];

function claseDias(dias) {
  if (dias >= 15) return "d-critico";
  if (dias >= 8) return "d-alerta";
  return "d-ok";
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [datos, setDatos] = useState(null);
  const [periodo, setPeriodo] = useState("mes");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setCargando(true);
    api
      .get(`/api/panel/dashboard?periodo=${periodo}`)
      .then((d) => {
        setDatos(d);
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => setCargando(false));
  }, [periodo]);

  if (!datos && cargando) return <div className="cargando">Cargando dashboard…</div>;
  if (!datos) return <div className="error">No se pudo cargar el dashboard: {error}</div>;

  const { mes, por_area, mas_antiguas } = datos;
  const maxValor = Math.max(1, ...por_area.map((a) => a.valor));

  return (
    <div>
      <h1>Dashboard</h1>

      {/* ── tarjetas del mes actual ── */}
      <div className="kpis">
        <div className="kpi" style={{ "--i": 0 }}>
          <div className="kpi-etiqueta">Facturas del mes</div>
          <div className="kpi-valor">{mes.total}</div>
          <div className="kpi-sub">recibidas este mes</div>
        </div>
        <div className="kpi" style={{ "--i": 1 }}>
          <div className="kpi-etiqueta">Pendientes</div>
          <div className="kpi-valor">{mes.pendientes}</div>
          <div className="kpi-sub">faltan documentos por subir</div>
        </div>
        <div className="kpi" style={{ "--i": 2 }}>
          <div className="kpi-etiqueta">Procesadas</div>
          <div className="kpi-valor">{mes.procesadas}</div>
          <div className="kpi-sub">con todos los documentos</div>
        </div>
        <div className="kpi" style={{ "--i": 3 }}>
          <div className="kpi-etiqueta">Valor del mes</div>
          <div className="kpi-valor">{formatoPesosCompacto(mes.valor_total)}</div>
          <div className="kpi-sub">total facturado</div>
        </div>
      </div>

      {/* ── análisis por área ── */}
      <div className="seccion-cabecera">
        <h2>Compras por área</h2>
        <div className="periodos">
          {PERIODOS.map(([k, t]) => (
            <button
              key={k}
              className={periodo === k ? "periodo activo" : "periodo"}
              onClick={() => setPeriodo(k)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <div className={cargando ? "panel recargando" : "panel"}>
        {por_area.length === 0 ? (
          <div className="vacio">No hay facturas en este periodo.</div>
        ) : (
          <div className="barras">
            {por_area.map((a) => (
              <div className="barra-fila" key={a.area}>
                <div className="barra-info">
                  <span className={a.area === "Sin asignar" ? "barra-nombre sin" : "barra-nombre"}>
                    {a.area}
                  </span>
                  <span className="barra-cant">
                    {a.cantidad} {a.cantidad === 1 ? "factura" : "facturas"}
                    {a.pendientes > 0 && ` · ${a.pendientes} pend.`}
                  </span>
                </div>
                <div className="barra-pista" title={formatoPesos(a.valor)}>
                  <div
                    className={a.area === "Sin asignar" ? "barra-relleno neutro" : "barra-relleno"}
                    style={{ width: `${Math.max(0.5, (a.valor / maxValor) * 100)}%` }}
                  />
                  <span className="barra-valor">{formatoPesosCompacto(a.valor)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── facturas con más tiempo sin procesar ── */}
      <h2>Facturas con más tiempo sin procesar</h2>
      <p className="ayuda">
        Las más antiguas aún pendientes (de todo el histórico). Haz clic para abrir el detalle y
        gestionar los documentos que faltan.
      </p>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Folio</th>
              <th>Proveedor</th>
              <th>Área</th>
              <th className="der">Valor</th>
              <th>Recibida</th>
              <th>Días sin procesar</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {mas_antiguas.length === 0 ? (
              <tr>
                <td colSpan="7" className="vacio">
                  🎉 No hay facturas pendientes.
                </td>
              </tr>
            ) : (
              mas_antiguas.map((f, i) => {
                const b = badgeEstado(f.estado_proceso);
                return (
                  <tr key={f.id} style={{ "--i": i }} onClick={() => navigate(`/facturas/${f.id}`)}>
                    <td className="mono">{f.numero}</td>
                    <td className="prov">{f.proveedor}</td>
                    <td>{f.area || <span className="sin">sin asignar</span>}</td>
                    <td className="der mono">{formatoPesos(f.valor_total)}</td>
                    <td>{formatoFecha(f.fecha_recepcion)}</td>
                    <td>
                      {f.dias_sin_procesar == null ? (
                        "—"
                      ) : (
                        <span className={`badge ${claseDias(f.dias_sin_procesar)}`}>
                          {f.dias_sin_procesar} {f.dias_sin_procesar === 1 ? "día" : "días"}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${b.clase}`}>{b.texto}</span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  badgeEstado,
  etiquetaMes,
  formatoFecha,
  formatoPesos,
  formatoPesosCompacto,
  sumarMeses,
} from "../util";

const PERIODOS = [
  ["mes", "Mes seleccionado"],
  ["trimestre", "Últimos 3 meses"],
  ["anio", "Año a la fecha"],
  ["todo", "Todo"],
];

const VENTANAS = [6, 12, 24];

function claseDias(dias) {
  if (dias >= 15) return "d-critico";
  if (dias >= 8) return "d-alerta";
  return "d-ok";
}

// Intensidad de la celda del mapa de calor (rampa secuencial de un solo tono,
// clara → oscura). El nivel 0 no pinta: distingue "sin gasto" de "gasto bajo".
// Los negativos (mes en que las notas crédito superaron lo facturado) no entran
// en la rampa: se pintan aparte con .celda-neg.
function nivelCelda(valor, maximo) {
  if (!valor || valor < 0 || maximo <= 0) return 0;
  const razon = valor / maximo;
  if (razon > 0.66) return 5;
  if (razon > 0.4) return 4;
  if (razon > 0.2) return 3;
  if (razon > 0.07) return 2;
  return 1;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [datos, setDatos] = useState(null);
  const [periodo, setPeriodo] = useState("mes");
  const [mes, setMes] = useState(null); // null = mes en curso (lo decide el backend)
  const [ventana, setVentana] = useState(12);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setCargando(true);
    const params = new URLSearchParams({ periodo, meses: String(ventana) });
    if (mes) params.set("mes", mes);
    api
      .get(`/api/panel/dashboard?${params}`)
      .then((d) => {
        setDatos(d);
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => setCargando(false));
  }, [periodo, mes, ventana]);

  if (!datos && cargando) return <div className="cargando">Cargando dashboard…</div>;
  if (!datos) return <div className="error">No se pudo cargar el dashboard: {error}</div>;

  const { mes: kpis, por_area, mas_antiguas, matriz, meses_disponibles } = datos;
  const mesSel = datos.mes_seleccionado;
  const maxValor = Math.max(1, ...por_area.map((a) => a.valor));
  const maxCelda = Math.max(0, ...matriz.filas.flatMap((f) => f.valores));
  const mesReciente = meses_disponibles[0];
  const mesAntiguo = meses_disponibles[meses_disponibles.length - 1];

  return (
    <div>
      {/* ── cabecera con el selector de mes ── */}
      <div className="titulo-fila">
        <h1>Dashboard</h1>
        <div className="selector-mes">
          <button
            className="mes-flecha"
            onClick={() => setMes(sumarMeses(mesSel, -1))}
            disabled={mesSel <= mesAntiguo}
            title="Mes anterior"
            aria-label="Mes anterior"
          >
            ‹
          </button>
          <select value={mesSel} onChange={(e) => setMes(e.target.value)} aria-label="Mes a analizar">
            {meses_disponibles.map((m) => (
              <option key={m} value={m}>
                {etiquetaMes(m, true)}
              </option>
            ))}
          </select>
          <button
            className="mes-flecha"
            onClick={() => setMes(sumarMeses(mesSel, 1))}
            disabled={mesSel >= mesReciente}
            title="Mes siguiente"
            aria-label="Mes siguiente"
          >
            ›
          </button>
        </div>
      </div>

      {/* ── tarjetas del mes seleccionado ── */}
      <div className={cargando ? "kpis recargando" : "kpis"}>
        <div className="kpi" style={{ "--i": 0 }}>
          <div className="kpi-etiqueta">Facturas del mes</div>
          <div className="kpi-valor">{kpis.total}</div>
          <div className="kpi-sub">emitidas en {etiquetaMes(mesSel, true).toLowerCase()}</div>
        </div>
        <div className="kpi" style={{ "--i": 1 }}>
          <div className="kpi-etiqueta">Pendientes</div>
          <div className="kpi-valor">{kpis.pendientes}</div>
          <div className="kpi-sub">faltan documentos por subir</div>
        </div>
        <div className="kpi" style={{ "--i": 2 }}>
          <div className="kpi-etiqueta">Procesadas</div>
          <div className="kpi-valor">{kpis.procesadas}</div>
          <div className="kpi-sub">con todos los documentos</div>
        </div>
        <div className="kpi" style={{ "--i": 3 }}>
          <div className="kpi-etiqueta">Valor del mes</div>
          <div className="kpi-valor" title={formatoPesos(kpis.valor_total)}>
            {formatoPesosCompacto(kpis.valor_total)}
          </div>
          <div className="kpi-sub">
            {kpis.notas_credito > 0 ? (
              <>
                sin IVA · {formatoPesosCompacto(kpis.facturado)} −{" "}
                {formatoPesosCompacto(kpis.valor_notas_credito)} de {kpis.notas_credito}{" "}
                {kpis.notas_credito === 1 ? "nota crédito" : "notas crédito"}
              </>
            ) : (
              "facturado sin IVA"
            )}
          </div>
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
                    {a.notas_credito > 0 && (
                      <span
                        className="barra-nc"
                        title={`${formatoPesos(a.valor_notas_credito)} en notas crédito ya descontados`}
                      >
                        {` · −${formatoPesosCompacto(a.valor_notas_credito)} NC`}
                      </span>
                    )}
                  </span>
                </div>
                <div className="barra-pista" title={formatoPesos(a.valor)}>
                  {/* la pista reserva el ancho de la etiqueta: la barra más larga
                      llega al 100% de su carril sin empujar el valor fuera del panel */}
                  <div className="barra-track">
                    <div
                      className={a.area === "Sin asignar" ? "barra-relleno neutro" : "barra-relleno"}
                      style={{ width: `${Math.max(0.5, (a.valor / maxValor) * 100)}%` }}
                    />
                  </div>
                  <span className="barra-valor">{formatoPesosCompacto(a.valor)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── acumulado mensual por área (mapa de calor) ── */}
      <div className="seccion-cabecera">
        <h2>Gasto por área y mes</h2>
        <div className="matriz-controles">
          <div className="escala" aria-hidden="true">
            <span className="escala-texto">menos</span>
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n} className={`escala-paso celda-n${n}`} />
            ))}
            <span className="escala-texto">más</span>
          </div>
          <select
            className="select-ventana"
            value={ventana}
            onChange={(e) => setVentana(Number(e.target.value))}
            aria-label="Meses a mostrar"
          >
            {VENTANAS.map((n) => (
              <option key={n} value={n}>
                Últimos {n} meses
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="ayuda">
        Cada celda es el gasto neto del área en ese mes —sin IVA y con las notas crédito ya
        descontadas—, ubicado por la fecha de emisión del documento (color más intenso = más
        gasto). La última columna acumula la ventana completa y las dos filas finales muestran
        el total mensual y su acumulado corrido.
      </p>
      <div className={cargando ? "tabla-scroll recargando" : "tabla-scroll"}>
        <table className="tabla matriz">
          <thead>
            <tr>
              <th className="col-area">Área</th>
              {matriz.meses.map((m) => (
                <th key={m} className="der">
                  {etiquetaMes(m)}
                </th>
              ))}
              <th className="der col-total">Total</th>
            </tr>
          </thead>
          <tbody>
            {matriz.filas.length === 0 ? (
              <tr>
                <td colSpan={matriz.meses.length + 2} className="vacio">
                  No hay facturas en esta ventana de meses.
                </td>
              </tr>
            ) : (
              matriz.filas.map((fila) => (
                <tr key={fila.area}>
                  <td className={fila.area === "Sin asignar" ? "col-area sin" : "col-area"}>
                    {fila.area}
                  </td>
                  {fila.valores.map((v, i) => (
                    <td
                      key={matriz.meses[i]}
                      className={
                        v < 0
                          ? "der mono celda-neg"
                          : `der mono celda-n${nivelCelda(v, maxCelda)}`
                      }
                      title={`${fila.area} · ${etiquetaMes(matriz.meses[i], true)}: ${formatoPesos(v)}`}
                    >
                      {v ? formatoPesosCompacto(v) : "—"}
                    </td>
                  ))}
                  <td className="der mono col-total" title={formatoPesos(fila.total)}>
                    {formatoPesosCompacto(fila.total)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
          {matriz.filas.length > 0 && (
            <tfoot>
              <tr>
                <td className="col-area">Total del mes</td>
                {matriz.totales_mes.map((v, i) => (
                  <td key={matriz.meses[i]} className="der mono" title={formatoPesos(v)}>
                    {v ? formatoPesosCompacto(v) : "—"}
                  </td>
                ))}
                <td className="der mono col-total" title={formatoPesos(matriz.total_general)}>
                  {formatoPesosCompacto(matriz.total_general)}
                </td>
              </tr>
              <tr className="fila-acumulado">
                <td className="col-area">Acumulado</td>
                {matriz.acumulado.map((v, i) => (
                  <td key={matriz.meses[i]} className="der mono" title={formatoPesos(v)}>
                    {v ? formatoPesosCompacto(v) : "—"}
                  </td>
                ))}
                <td className="der col-total">—</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* ── facturas con más tiempo sin procesar ── */}
      <h2>Facturas con más tiempo sin procesar</h2>
      <p className="ayuda">
        Las de emisión más antigua que siguen pendientes (de todo el histórico, sin importar
        el mes elegido). Los días se cuentan desde que el proveedor las emitió. Haz clic para
        abrir el detalle y gestionar los documentos que faltan.
      </p>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Folio</th>
              <th>Proveedor</th>
              <th>Área</th>
              <th className="der">Valor</th>
              <th>Emitida</th>
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
                    <td>{formatoFecha(f.fecha_emision)}</td>
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

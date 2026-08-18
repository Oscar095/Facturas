import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth.jsx";
import {
  badgeEstado, badgeTipoDocumento, formatoFecha, formatoPesos, tienePermiso,
  ESTADOS, TIPOS_FACTURA,
} from "../util";

// Estados desde los que el jefe todavía puede aprobar (las ya aprobadas o
// contabilizadas no se pueden seleccionar).
const APROBABLES = ["asignada", "docs_pendientes", "lista_contabilizar", "procesada"];

function esAprobable(f) {
  return !!f.area && APROBABLES.includes(f.estado_proceso);
}

export default function Facturas() {
  const { usuario } = useAuth();
  const navigate = useNavigate();
  // Los filtros viven en la URL (no en el estado del componente): así, al entrar
  // a una factura y volver con ←, la lista reaparece exactamente como estaba.
  // Cada cambio de filtro REEMPLAZA la entrada del historial en vez de apilar
  // una nueva — si no, "Volver" tendría que deshacer tecleo por tecleo.
  const [params, setParams] = useSearchParams();
  const qs = params.toString();
  const filtros = useMemo(() => {
    const p = new URLSearchParams(qs);
    return {
      estado: p.get("estado") || "",
      area_id: p.get("area_id") || "",
      proveedor: p.get("proveedor") || "",
      tipo_documento: p.get("tipo_documento") || "",
      fecha_desde: p.get("fecha_desde") || "",
      fecha_hasta: p.get("fecha_hasta") || "",
      solo_mias: p.get("solo_mias") === "true",
      pagina: Math.max(1, Number(p.get("pagina")) || 1),
    };
  }, [qs]);

  const [data, setData] = useState({ items: [], total: 0 });
  const [areas, setAreas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [refresco, setRefresco] = useState(0);

  const puedeAprobar = tienePermiso(usuario, "aprobar");

  useEffect(() => {
    api.get("/api/areas").then(setAreas).catch(() => setAreas([]));
  }, []);

  useEffect(() => {
    setCargando(true);
    const p = new URLSearchParams();
    if (filtros.estado) p.set("estado", filtros.estado);
    if (filtros.area_id) p.set("area_id", filtros.area_id);
    if (filtros.proveedor) p.set("proveedor", filtros.proveedor);
    if (filtros.tipo_documento) p.set("tipo_documento", filtros.tipo_documento);
    if (filtros.fecha_desde) p.set("fecha_desde", filtros.fecha_desde);
    if (filtros.fecha_hasta) p.set("fecha_hasta", filtros.fecha_hasta);
    if (filtros.solo_mias) p.set("solo_mias", "true");
    p.set("pagina", filtros.pagina);
    api
      .get(`/api/facturas?${p.toString()}`)
      .then(setData)
      .catch(() => setData({ items: [], total: 0 }))
      .finally(() => setCargando(false));
  }, [filtros, refresco]);

  // Se actualiza con la forma funcional (recibe los params vigentes) y no con
  // el `qs` de este render: dos filtros cambiados muy seguido —o dos campos de
  // un rango de fechas— usarían una copia vieja y el segundo borraría al primero.
  function set(campo, valor) {
    setParams((previos) => {
      const p = new URLSearchParams(previos);
      if (valor === "" || valor === false || valor == null) p.delete(campo);
      else p.set(campo, String(valor));
      p.delete("pagina"); // cambiar un filtro vuelve a la primera página
      return p;
    }, { replace: true });
  }

  function irPagina(n) {
    setParams((previos) => {
      const p = new URLSearchParams(previos);
      if (n <= 1) p.delete("pagina");
      else p.set("pagina", String(n));
      return p;
    }, { replace: true });
  }

  // ── selección en bloque ──
  const [seleccion, setSeleccion] = useState(() => new Set());
  const [panelLote, setPanelLote] = useState(false);
  const [firmas, setFirmas] = useState([]);
  const [firmaSel, setFirmaSel] = useState("");
  const [aprobando, setAprobando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState("");

  // Al cambiar filtros o página la selección deja de tener sentido: las filas
  // marcadas ya no están a la vista y el jefe no vería qué está aprobando.
  useEffect(() => {
    setSeleccion(new Set());
    setPanelLote(false);
  }, [qs]);

  const aprobables = data.items.filter(esAprobable);
  const todasMarcadas = aprobables.length > 0 && aprobables.every((f) => seleccion.has(f.id));

  function alternar(id) {
    setSeleccion((s) => {
      const nueva = new Set(s);
      if (nueva.has(id)) nueva.delete(id);
      else nueva.add(id);
      return nueva;
    });
  }

  function alternarTodas() {
    setSeleccion(todasMarcadas ? new Set() : new Set(aprobables.map((f) => f.id)));
  }

  async function abrirPanelLote() {
    setError("");
    setResultado(null);
    try {
      const lista = await api.get("/api/firmas");
      setFirmas(lista);
      setFirmaSel(lista.length ? String(lista[0].id) : "");
      setPanelLote(true);
    } catch (e) {
      setError(e.message);
    }
  }

  async function aprobarLote() {
    const ids = [...seleccion];
    const mensaje =
      `Vas a aprobar y firmar ${ids.length} factura(s) con tu firma.\n\n` +
      "Las que aún no estén procesadas se procesarán en el mismo paso: al " +
      "seleccionarlas declaras que sus documentos son suficientes.\n\n¿Continuar?";
    if (!confirm(mensaje)) return;
    setAprobando(true);
    setError("");
    try {
      const r = await api.post("/api/facturas/aprobar-lote", {
        ids,
        firma_id: Number(firmaSel),
      });
      setResultado(r);
      setSeleccion(new Set());
      setPanelLote(false);
      setRefresco((n) => n + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setAprobando(false);
    }
  }

  const porPagina = data.por_pagina || 25;
  const totalPaginas = Math.max(1, Math.ceil(data.total / porPagina));
  const columnas = puedeAprobar ? 10 : 9;

  return (
    <div>
      <h1>Facturas</h1>

      <div className="filtros">
        <input
          placeholder="Buscar proveedor (NIT o nombre)…"
          value={filtros.proveedor}
          onChange={(e) => set("proveedor", e.target.value)}
        />
        <select value={filtros.estado} onChange={(e) => set("estado", e.target.value)}>
          <option value="">Todos los estados</option>
          {Object.entries(ESTADOS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.texto}
            </option>
          ))}
        </select>
        <select
          value={filtros.tipo_documento}
          onChange={(e) => set("tipo_documento", e.target.value)}
        >
          <option value="">Todos los tipos</option>
          {Object.entries(TIPOS_FACTURA).map(([k, v]) => (
            <option key={k} value={k}>
              {v.texto}
            </option>
          ))}
        </select>
        <label className="filtro-fecha">
          Emisión desde
          <input
            type="date"
            value={filtros.fecha_desde}
            onChange={(e) => set("fecha_desde", e.target.value)}
          />
        </label>
        <label className="filtro-fecha">
          hasta
          <input
            type="date"
            value={filtros.fecha_hasta}
            onChange={(e) => set("fecha_hasta", e.target.value)}
          />
        </label>
        {tienePermiso(usuario, "ver_todas_areas") && (
          <select value={filtros.area_id} onChange={(e) => set("area_id", e.target.value)}>
            <option value="">Todas las áreas</option>
            {areas.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nombre}
              </option>
            ))}
          </select>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={filtros.solo_mias}
            onChange={(e) => set("solo_mias", e.target.checked)}
          />
          Solo mías
        </label>
      </div>

      {error && <div className="error">{error}</div>}

      {resultado && (
        <div className={`aviso ${resultado.errores === 0 ? "ok" : ""}`}>
          <b>{resultado.aprobadas}</b> factura(s) aprobadas y firmadas
          {resultado.omitidas > 0 && ` · ${resultado.omitidas} omitida(s)`}
          {resultado.errores > 0 && ` · ${resultado.errores} con error`}
          {resultado.resultados.some((r) => r.estado !== "aprobada") && (
            <ul className="lista-lote">
              {resultado.resultados
                .filter((r) => r.estado !== "aprobada")
                .map((r) => (
                  <li key={r.factura_id}>
                    <span className="mono">{r.numero || r.factura_id}</span> — {r.detalle}
                  </li>
                ))}
            </ul>
          )}
          <button className="btn-link" onClick={() => setResultado(null)}>
            Cerrar
          </button>
        </div>
      )}

      {puedeAprobar && seleccion.size > 0 && (
        <div className="barra-lote">
          <span>
            <b>{seleccion.size}</b> factura(s) seleccionada(s)
          </span>
          {!panelLote ? (
            <button className="btn exito" onClick={abrirPanelLote}>
              ✍️ Aprobar y firmar
            </button>
          ) : firmas.length === 0 ? (
            <span className="ayuda">
              No tienes firmas guardadas — súbela primero en “Mis Firmas”.
            </span>
          ) : (
            <>
              <select value={firmaSel} onChange={(e) => setFirmaSel(e.target.value)}>
                {firmas.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.nombre} ({f.nombre_archivo})
                  </option>
                ))}
              </select>
              <button className="btn exito" onClick={aprobarLote} disabled={aprobando}>
                {aprobando ? "Firmando…" : "Confirmar y firmar"}
              </button>
            </>
          )}
          <button
            className="btn-sec"
            disabled={aprobando}
            onClick={() => {
              setSeleccion(new Set());
              setPanelLote(false);
            }}
          >
            Limpiar
          </button>
        </div>
      )}

      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              {puedeAprobar && (
                <th className="col-check">
                  <input
                    type="checkbox"
                    title="Seleccionar todas las facturas aprobables de esta página"
                    checked={todasMarcadas}
                    disabled={aprobables.length === 0}
                    onChange={alternarTodas}
                  />
                </th>
              )}
              <th>Folio</th>
              <th>Tipo</th>
              <th>Proveedor</th>
              <th className="der">Valor</th>
              <th>Emisión</th>
              <th>Vence</th>
              <th>Cargada</th>
              <th>Área</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {cargando ? (
              <tr>
                <td colSpan={columnas} className="vacio">
                  Cargando…
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan={columnas} className="vacio">
                  No hay facturas con estos filtros.
                </td>
              </tr>
            ) : (
              data.items.map((f, i) => {
                const b = badgeEstado(f.estado_proceso);
                const t = badgeTipoDocumento(f.tipo_documento);
                const marcada = seleccion.has(f.id);
                return (
                  <tr
                    key={f.id}
                    style={{ "--i": i }}
                    className={marcada ? "marcada" : ""}
                    onClick={() => navigate(`/facturas/${f.id}`)}
                  >
                    {puedeAprobar && (
                      /* el clic en la casilla NO debe abrir el detalle */
                      <td className="col-check" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={marcada}
                          disabled={!esAprobable(f)}
                          title={
                            esAprobable(f)
                              ? "Seleccionar para aprobar en bloque"
                              : f.area
                                ? `No se puede aprobar: ya está ${f.estado_proceso}`
                                : "No se puede aprobar: sin área asignada"
                          }
                          onChange={() => alternar(f.id)}
                        />
                      </td>
                    )}
                    <td className="mono">
                      {f.numero}
                      {f.observaciones && (
                        <span className="marca-obs" title={f.observaciones}>
                          💬
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${t.clase}`}>{t.texto}</span>
                    </td>
                    <td>
                      <div className="prov">{f.proveedor.razon_social}</div>
                      <div className="prov-nit">{f.proveedor.nit}</div>
                    </td>
                    <td className="der mono">{formatoPesos(f.valor_total)}</td>
                    <td>{formatoFecha(f.fecha_emision)}</td>
                    <td>{formatoFecha(f.fecha_vencimiento)}</td>
                    <td>{formatoFecha(f.fecha_recepcion)}</td>
                    <td>{f.area?.nombre || <span className="sin">sin asignar</span>}</td>
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

      <div className="paginacion">
        <button
          className="btn-sec"
          disabled={filtros.pagina <= 1}
          onClick={() => irPagina(filtros.pagina - 1)}
        >
          ← Anterior
        </button>
        <span>
          Página {filtros.pagina} de {totalPaginas} · {data.total} facturas
        </span>
        <button
          className="btn-sec"
          disabled={filtros.pagina >= totalPaginas}
          onClick={() => irPagina(filtros.pagina + 1)}
        >
          Siguiente →
        </button>
      </div>
    </div>
  );
}

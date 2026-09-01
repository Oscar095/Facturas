import { useEffect, useState } from "react";
import { api, getToken } from "../api";
import { useAuth } from "../auth.jsx";
import { formatoFecha, formatoPesos, tienePermiso } from "../util";

export default function NotasCredito() {
  const { usuario } = useAuth();
  const [data, setData] = useState({ items: [], total: 0 });
  const [areas, setAreas] = useState([]);
  const [filtros, setFiltros] = useState({ proveedor: "", area_id: "", sin_area: false, pagina: 1 });
  const [cargando, setCargando] = useState(true);
  const [guardandoId, setGuardandoId] = useState(null);
  const [error, setError] = useState("");

  // Mismo permiso que para editar facturas: quien puede reasignar áreas allá, aquí también.
  const puedeEditar = tienePermiso(usuario, "editar_facturas");
  const veTodasLasAreas = tienePermiso(usuario, "ver_todas_areas");

  useEffect(() => {
    if (puedeEditar) api.get("/api/areas").then(setAreas).catch(() => setAreas([]));
  }, [puedeEditar]);

  useEffect(() => {
    // ver el comentario de Facturas.jsx: descarta la respuesta de una consulta
    // superada para que una petición lenta no pise el resultado del filtro nuevo
    let vigente = true;
    setCargando(true);
    const p = new URLSearchParams();
    if (filtros.proveedor) p.set("proveedor", filtros.proveedor);
    if (filtros.area_id) p.set("area_id", filtros.area_id);
    if (filtros.sin_area) p.set("sin_area", "true");
    p.set("pagina", filtros.pagina);
    api
      .get(`/api/notas-credito?${p.toString()}`)
      .then((d) => vigente && setData(d))
      .catch(() => vigente && setData({ items: [], total: 0 }))
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, [filtros]);

  function set(campo, valor) {
    setFiltros((f) => ({ ...f, [campo]: valor, pagina: 1 }));
  }

  async function cambiarArea(nota, valor) {
    const area_id = Number(valor);
    if (!area_id) return;
    setError("");
    setGuardandoId(nota.id);
    try {
      const actualizada = await api.patch(`/api/notas-credito/${nota.id}`, { area_id });
      // Reemplaza solo la fila tocada para no perder la posición ni recargar todo
      setData((d) => ({
        ...d,
        items: d.items.map((n) => (n.id === actualizada.id ? actualizada : n)),
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setGuardandoId(null);
    }
  }

  function abrirPdf(nota) {
    setError("");
    fetch(`/api/notas-credito/${nota.id}/pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error("No se pudo abrir el PDF");
        return r.blob();
      })
      .then((b) => window.open(URL.createObjectURL(b), "_blank"))
      .catch((e) => setError(e.message));
  }

  const porPagina = data.por_pagina || 25;
  const totalPaginas = Math.max(1, Math.ceil(data.total / porPagina));

  return (
    <div>
      <h1>Notas Crédito</h1>

      <div className="filtros">
        <input
          placeholder="Buscar proveedor (NIT o nombre)…"
          value={filtros.proveedor}
          onChange={(e) => set("proveedor", e.target.value)}
        />
        {veTodasLasAreas && (
          <>
            <select
              value={filtros.area_id}
              disabled={filtros.sin_area}
              onChange={(e) => set("area_id", e.target.value)}
            >
              <option value="">Todas las áreas</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre}
                </option>
              ))}
            </select>
            <label className="check">
              <input
                type="checkbox"
                checked={filtros.sin_area}
                onChange={(e) => setFiltros({ ...filtros, sin_area: e.target.checked, area_id: "", pagina: 1 })}
              />
              Solo sin área
            </label>
          </>
        )}
      </div>
      {error && <div className="error">{error}</div>}

      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Folio</th>
              <th>Proveedor</th>
              <th className="der">Valor sin IVA</th>
              <th>Emisión</th>
              <th>Cargada</th>
              <th>Área</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cargando ? (
              <tr>
                <td colSpan="7" className="vacio">
                  Cargando…
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan="7" className="vacio">
                  No hay notas crédito con estos filtros.
                </td>
              </tr>
            ) : (
              data.items.map((n, i) => (
                <tr key={n.id} style={{ "--i": i }}>
                  <td className="mono">{n.numero}</td>
                  <td>
                    <div className="prov">{n.proveedor.razon_social}</div>
                    <div className="prov-nit">{n.proveedor.nit}</div>
                  </td>
                  <td className="der mono">
                    {formatoPesos(n.subtotal)}
                    {n.iva == null && (
                      <span
                        className="iva-desconocido"
                        title="No se pudo determinar el IVA de esta nota crédito: el valor mostrado todavía lo incluye."
                      >
                        *
                      </span>
                    )}
                  </td>
                  <td>{formatoFecha(n.fecha_emision)}</td>
                  <td>{formatoFecha(n.fecha_recepcion)}</td>
                  <td>
                    {puedeEditar ? (
                      <select
                        className="select-area"
                        value={n.area?.id || ""}
                        disabled={guardandoId === n.id}
                        onChange={(e) => cambiarArea(n, e.target.value)}
                      >
                        <option value="" disabled>
                          {n.area?.nombre ? "Cambiar área…" : "Sin asignar — elegir área"}
                        </option>
                        {areas.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.nombre}
                          </option>
                        ))}
                      </select>
                    ) : (
                      n.area?.nombre || <span className="sin">sin asignar</span>
                    )}
                  </td>
                  <td>
                    <button className="btn-link" onClick={() => abrirPdf(n)}>
                      Ver PDF
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="paginacion">
        <button
          className="btn-sec"
          disabled={filtros.pagina <= 1}
          onClick={() => setFiltros((f) => ({ ...f, pagina: f.pagina - 1 }))}
        >
          ← Anterior
        </button>
        <span>
          Página {filtros.pagina} de {totalPaginas} · {data.total} notas crédito
        </span>
        <button
          className="btn-sec"
          disabled={filtros.pagina >= totalPaginas}
          onClick={() => setFiltros((f) => ({ ...f, pagina: f.pagina + 1 }))}
        >
          Siguiente →
        </button>
      </div>
    </div>
  );
}

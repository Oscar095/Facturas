import { useEffect, useState } from "react";
import { api, getToken } from "../api";
import { formatoFecha, formatoPesos } from "../util";

export default function NotasCredito() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [filtros, setFiltros] = useState({ proveedor: "", pagina: 1 });
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setCargando(true);
    const p = new URLSearchParams();
    if (filtros.proveedor) p.set("proveedor", filtros.proveedor);
    p.set("pagina", filtros.pagina);
    api
      .get(`/api/notas-credito?${p.toString()}`)
      .then(setData)
      .catch(() => setData({ items: [], total: 0 }))
      .finally(() => setCargando(false));
  }, [filtros]);

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
          onChange={(e) => setFiltros({ proveedor: e.target.value, pagina: 1 })}
        />
      </div>
      {error && <div className="error">{error}</div>}

      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Folio</th>
              <th>Proveedor</th>
              <th className="der">Valor</th>
              <th>Emisión</th>
              <th>Cargada</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cargando ? (
              <tr>
                <td colSpan="6" className="vacio">
                  Cargando…
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan="6" className="vacio">
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
                  <td className="der mono">{formatoPesos(n.valor_total)}</td>
                  <td>{formatoFecha(n.fecha_emision)}</td>
                  <td>{formatoFecha(n.fecha_recepcion)}</td>
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

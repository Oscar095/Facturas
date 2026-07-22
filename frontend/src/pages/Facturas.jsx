import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth.jsx";
import { badgeEstado, formatoFecha, formatoPesos, ESTADOS } from "../util";

export default function Facturas() {
  const { usuario } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState({ items: [], total: 0 });
  const [areas, setAreas] = useState([]);
  const [filtros, setFiltros] = useState({
    estado: "",
    area_id: "",
    proveedor: "",
    solo_mias: false,
    pagina: 1,
  });
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    api.get("/api/areas").then(setAreas).catch(() => setAreas([]));
  }, []);

  useEffect(() => {
    setCargando(true);
    const p = new URLSearchParams();
    if (filtros.estado) p.set("estado", filtros.estado);
    if (filtros.area_id) p.set("area_id", filtros.area_id);
    if (filtros.proveedor) p.set("proveedor", filtros.proveedor);
    if (filtros.solo_mias) p.set("solo_mias", "true");
    p.set("pagina", filtros.pagina);
    api
      .get(`/api/facturas?${p.toString()}`)
      .then(setData)
      .catch(() => setData({ items: [], total: 0 }))
      .finally(() => setCargando(false));
  }, [filtros]);

  function set(campo, valor) {
    setFiltros((f) => ({ ...f, [campo]: valor, pagina: 1 }));
  }

  const porPagina = data.por_pagina || 25;
  const totalPaginas = Math.max(1, Math.ceil(data.total / porPagina));

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
        {usuario?.rol !== "area" && (
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

      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr>
              <th>Folio</th>
              <th>Proveedor</th>
              <th className="der">Valor</th>
              <th>Emisión</th>
              <th>Cargada</th>
              <th>Área</th>
              <th>Estado</th>
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
                  No hay facturas con estos filtros.
                </td>
              </tr>
            ) : (
              data.items.map((f) => {
                const b = badgeEstado(f.estado_proceso);
                return (
                  <tr key={f.id} onClick={() => navigate(`/facturas/${f.id}`)}>
                    <td className="mono">{f.numero}</td>
                    <td>
                      <div className="prov">{f.proveedor.razon_social}</div>
                      <div className="prov-nit">{f.proveedor.nit}</div>
                    </td>
                    <td className="der mono">{formatoPesos(f.valor_total)}</td>
                    <td>{formatoFecha(f.fecha_emision)}</td>
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
          onClick={() => setFiltros((f) => ({ ...f, pagina: f.pagina - 1 }))}
        >
          ← Anterior
        </button>
        <span>
          Página {filtros.pagina} de {totalPaginas} · {data.total} facturas
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

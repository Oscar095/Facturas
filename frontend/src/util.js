export const ESTADOS = {
  nueva: { texto: "Nueva", clase: "e-nueva" },
  asignada: { texto: "Asignada", clase: "e-asignada" },
  docs_pendientes: { texto: "Docs pendientes", clase: "e-pendiente" },
  lista_contabilizar: { texto: "Lista para contabilizar", clase: "e-lista" },
  procesada: { texto: "Procesada", clase: "e-procesada" },
  aprobada: { texto: "Aprobada", clase: "e-aprobada" },
  contabilizada: { texto: "Contabilizada", clase: "e-contabilizada" },
};

export function badgeEstado(estado) {
  return ESTADOS[estado] || { texto: estado, clase: "" };
}

export const TIPOS_FACTURA = {
  FACTURA: { texto: "Factura", clase: "t-factura" },
  EQUIVALENTE: { texto: "Equivalente", clase: "t-equivalente" },
};

export function badgeTipoDocumento(tipo) {
  return TIPOS_FACTURA[tipo] || { texto: tipo, clase: "" };
}

const pesos = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});
export function formatoPesos(v) {
  if (v == null) return "—";
  return pesos.format(Number(v));
}

const pesosCompacto = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  notation: "compact",
  maximumFractionDigits: 1,
});
export function formatoPesosCompacto(v) {
  if (v == null) return "—";
  return pesosCompacto.format(Number(v));
}

// ── meses del dashboard ('AAAA-MM') ──
// Se formatean con tablas propias y no con Date: new Date("2026-07-01") se
// interpreta como UTC y al mostrarlo en Bogotá (UTC-5) retrocede al mes anterior.
const MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

export function etiquetaMes(clave, largo = false) {
  if (!clave) return "—";
  const [anio, mes] = clave.split("-").map(Number);
  const nombre = MESES_ES[mes - 1] || clave;
  return largo ? `${nombre} ${anio}` : `${nombre.slice(0, 3).toLowerCase()} ${String(anio).slice(2)}`;
}

export function sumarMeses(clave, n) {
  const [anio, mes] = clave.split("-").map(Number);
  const total = anio * 12 + (mes - 1) + n;
  return `${String(Math.floor(total / 12)).padStart(4, "0")}-${String((total % 12) + 1).padStart(2, "0")}`;
}

// Permisos del rol (los envía /api/auth/yo). El respaldo por nombre de rol
// cubre sesiones cargadas antes de que existieran los permisos configurables.
const PERMISOS_LEGADO = {
  admin: { ver_todas_areas: true, editar_facturas: true, aprobar: true, contabilizar: true, administrar: true },
  contabilidad: { ver_todas_areas: true, editar_facturas: true, aprobar: true, contabilizar: true },
  area: { aprobar: true },
};
export function tienePermiso(usuario, permiso) {
  if (!usuario) return false;
  if (usuario.permisos) return !!usuario.permisos[permiso];
  return !!PERMISOS_LEGADO[usuario.rol]?.[permiso];
}

export function formatoFecha(v) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("es-CO", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

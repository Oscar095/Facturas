export const ESTADOS = {
  nueva: { texto: "Nueva", clase: "e-nueva" },
  asignada: { texto: "Asignada", clase: "e-asignada" },
  docs_pendientes: { texto: "Docs pendientes", clase: "e-pendiente" },
  lista_contabilizar: { texto: "Lista para contabilizar", clase: "e-lista" },
  contabilizada: { texto: "Contabilizada", clase: "e-contabilizada" },
};

export function badgeEstado(estado) {
  return ESTADOS[estado] || { texto: estado, clase: "" };
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

export function formatoFecha(v) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("es-CO", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

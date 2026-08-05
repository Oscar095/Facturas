"""Reglas de negocio: asignación de área/responsable y completitud de documentos."""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Area, Documento, Evento, Factura, NotaCredito, ReglaArea
from . import ia_area


def normalizar(texto: str | None) -> str:
    """minúsculas, sin tildes y con espacios colapsados — para comparar patrones."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def _resolver_regla(db: Session, doc: Factura | NotaCredito,
                    usar_ia: bool) -> tuple[ReglaArea | None, str | None]:
    """Núcleo de la cascada de asignación, común a facturas y notas crédito.

    `doc` solo necesita `proveedor`, `numero` y `texto_pdf`. Devuelve la regla
    que decide el área (o None si nada decidió) y, si fue la IA quien decidió,
    su razón — para que quien llama la audite como corresponda a su tabla.

    Cascada (de más barata a más cara):
      1. El proveedor tiene UNA sola área en sus reglas → esa.
      2. Varias áreas → se buscan los patrones de ítem (normalizados, sin
         tildes) en el texto del PDF:
           - si coincide exactamente un área → esa;
           - si no coincide ninguno pero el proveedor tiene reglas SIN patrón
             que apuntan todas a una misma área (área por defecto) → esa;
           - si coinciden varias áreas (patrones en conflicto) → no decide.
      3. IA (Claude, última opción y solo con `usar_ia`) → si sugiere una de
         las candidatas, esa.
      4. Nada decide → (None, None); se asigna a mano con el dropdown.
    """
    nit = doc.proveedor.nit if doc.proveedor else None
    if not nit:
        return None, None
    reglas = db.execute(
        select(ReglaArea).where(ReglaArea.proveedor_nit == nit)
    ).scalars().all()
    if not reglas:
        return None, None

    areas_candidatas = {r.area_id for r in reglas}
    if len(areas_candidatas) == 1:
        return reglas[0], None

    # 2) desambiguar por patrón de ítem contra el texto del PDF
    texto = _texto_para_patrones(doc)
    coincidentes = [r for r in reglas if r.patron_item and normalizar(r.patron_item) in texto]
    areas_match = {r.area_id for r in coincidentes}
    if len(areas_match) == 1:
        return coincidentes[0], None
    if not areas_match:
        # área por defecto: reglas sin patrón que apuntan todas a la misma área
        sin_patron = [r for r in reglas if not r.patron_item]
        if sin_patron and len({r.area_id for r in sin_patron}) == 1:
            return sin_patron[0], None

    # 3) IA como última opción (patrones en conflicto o sin coincidencias)
    if usar_ia and ia_area.disponible():
        candidatas = []
        for aid in sorted(areas_candidatas):
            area = db.get(Area, aid)
            pistas = [r.patron_item for r in reglas if r.area_id == aid and r.patron_item]
            candidatas.append((aid, area.nombre if area else str(aid), pistas))
        area_id, razon = ia_area.sugerir_area(
            doc.texto_pdf or "", doc.proveedor.razon_social, candidatas
        )
        if area_id is not None:
            # area_id viene de las candidatas, así que siempre hay una regla
            return next(r for r in reglas if r.area_id == area_id), razon

    # 4) nada decidió
    return None, None


def asignar_area(db: Session, factura: Factura, usar_ia: bool = True) -> None:
    """Asigna área y responsable a una factura según las reglas del proveedor.

    Además de aplicar la regla, avanza el estado a 'asignada' y audita en
    `eventos` cuando fue la IA quien decidió.
    """
    regla, razon_ia = _resolver_regla(db, factura, usar_ia)
    if regla is None:
        return
    _aplicar(factura, regla)
    if factura.estado_proceso == "nueva":
        factura.estado_proceso = "asignada"
    if razon_ia is not None:
        db.add(Evento(factura_id=factura.id, accion="ia_area",
                      detalle=f"IA asignó el área ({razon_ia})"))


def asignar_area_nota_credito(db: Session, nota: NotaCredito) -> None:
    """Misma cascada de reglas que las facturas, pero SIN IA.

    Decisión de negocio: no gastar créditos de Claude en notas crédito (son de
    consulta, no bloquean ningún flujo). Lo que los patrones no decidan queda
    sin área para asignarse a mano. Tampoco toca estado ni escribe en `eventos`
    (una NC no tiene estado_proceso y `eventos.factura_id` apunta a `facturas`).
    """
    regla, _ = _resolver_regla(db, nota, usar_ia=False)
    if regla is not None:
        _aplicar(nota, regla)


def _aplicar(doc: Factura | NotaCredito, regla: ReglaArea) -> None:
    doc.area_id = regla.area_id
    doc.responsable_id = regla.responsable_id


def _texto_para_patrones(doc: Factura | NotaCredito) -> str:
    """Texto normalizado sobre el que se evalúan los patrones de ítem:
    el contenido del PDF (ítems/conceptos) más proveedor y folio."""
    partes = [
        doc.proveedor.razon_social if doc.proveedor else "",
        doc.numero or "",
        doc.texto_pdf or "",
    ]
    return normalizar(" ".join(partes))


def _tipos_cargados(db: Session, factura: Factura) -> set[str]:
    return {
        d.tipo for d in db.execute(
            select(Documento).where(Documento.factura_id == factura.id)
        ).scalars().all()
    }


def faltan_documentos(db: Session, factura: Factura) -> list[str]:
    """Lista legible de documentos que faltan para poder contabilizar.

    Regla del proceso:
      - FV: siempre (el PDF descargado del portal cuenta como FV).
      - Orden: se requiere OCN (orden de compra) u OCS (orden de servicio).
      - CRN: solo si la orden es OCN (recepción de mercancía).
    Mientras no se cargue la orden, no se sabe si hará falta CRN.
    """
    tipos = _tipos_cargados(db, factura)
    faltan: list[str] = []
    if "FV" not in tipos:
        faltan.append("FV")

    tiene_ocn = "OCN" in tipos
    tiene_ocs = "OCS" in tipos
    if not (tiene_ocn or tiene_ocs):
        faltan.append("OCN u OCS")
    elif tiene_ocn and "CRN" not in tipos:
        faltan.append("CRN")
    return faltan


def inferir_tipo_orden(db: Session, factura: Factura) -> None:
    """Deduce tipo_orden a partir de las órdenes cargadas (OCN prevalece)."""
    tipos = _tipos_cargados(db, factura)
    if "OCN" in tipos:
        factura.tipo_orden = "OCN"
    elif "OCS" in tipos:
        factura.tipo_orden = "OCS"


def evaluar_completitud(db: Session, factura: Factura) -> None:
    """Recalcula el estado_proceso de la factura según los documentos cargados.

    No degrada los estados manuales del flujo de aprobación: 'procesada' (el
    responsable declaró los documentos suficientes), 'aprobada' ni
    'contabilizada' — esos solo avanzan con acciones explícitas de usuario.
    """
    if factura.estado_proceso in ("procesada", "aprobada", "contabilizada"):
        return

    inferir_tipo_orden(db, factura)
    faltantes = faltan_documentos(db, factura)

    if not faltantes:
        factura.estado_proceso = "lista_contabilizar"
    elif factura.area_id is not None:
        factura.estado_proceso = "docs_pendientes"
    else:
        factura.estado_proceso = "nueva"

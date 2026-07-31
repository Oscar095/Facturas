from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def ahora() -> datetime:
    return datetime.now(timezone.utc)


# Estados del proceso interno de una factura
ESTADOS_PROCESO = ("nueva", "asignada", "docs_pendientes", "lista_contabilizar", "contabilizada")
TIPOS_DOCUMENTO = ("FV", "OCN", "OCS", "CRN", "OTRO")
ROLES = ("admin", "contabilidad", "area")


class Rol(Base):
    """Rol de usuario con permisos configurables desde Administración.

    Los tres roles originales (admin, contabilidad, area) se siembran al arrancar
    como roles de sistema: no se editan ni se eliminan, y sus permisos replican el
    comportamiento histórico. `Usuario.rol` guarda el NOMBRE del rol (sin FK, para
    no alterar la tabla usuarios que ya está en producción).
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(20), unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Permisos (ver security.PERMISOS): sin ver_todas_areas el usuario queda
    # limitado a las facturas de su área.
    ver_todas_areas: Mapped[bool] = mapped_column(default=False)
    editar_facturas: Mapped[bool] = mapped_column(default=False)  # área/orden/responsable
    aprobar: Mapped[bool] = mapped_column(default=True)           # procesar y aprobar (firma)
    contabilizar: Mapped[bool] = mapped_column(default=False)
    administrar: Mapped[bool] = mapped_column(default=False)      # usuarios, áreas, reglas, robot, roles
    es_sistema: Mapped[bool] = mapped_column(default=False)


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nit: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    razon_social: Mapped[str] = mapped_column(String(300))

    facturas: Mapped[list["Factura"]] = relationship(back_populates="proveedor")


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    activa: Mapped[bool] = mapped_column(default=True)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    hash_clave: Mapped[str] = mapped_column(String(300))
    rol: Mapped[str] = mapped_column(String(20), default="area")
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    area: Mapped[Area | None] = relationship()


class ReglaArea(Base):
    """Regla proveedor (+ patrón opcional sobre la descripción/ítems) → área responsable.

    Un mismo proveedor_nit puede tener varias filas (varias áreas candidatas) cuando
    el proveedor factura a más de un área — en ese caso patron_item permite elegir
    la correcta según los ítems de la factura; si ninguna coincide, la factura queda
    sin área hasta que se resuelva (ver services/reglas.py).
    """

    __tablename__ = "reglas_area"
    __table_args__ = (
        # Único solo cuando hay NIT: SQL Server trata NULL=NULL como duplicado en
        # UNIQUE CONSTRAINT normales, así que varias reglas "sin NIT" (pendientes
        # de completar) no deben chocar entre sí.
        Index(
            "ux_reglas_area_nit_patron_area", "proveedor_nit", "patron_item", "area_id",
            unique=True, mssql_where=text("proveedor_nit IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_nit: Mapped[str | None] = mapped_column(String(30), index=True, nullable=True)
    proveedor_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    patron_item: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    area: Mapped[Area] = relationship()
    responsable: Mapped[Usuario | None] = relationship()


class Factura(Base):
    __tablename__ = "facturas"
    __table_args__ = (
        UniqueConstraint("proveedor_id", "prefijo", "numero"),
        # Único solo cuando hay CUFE: las facturas de carga manual (físicas/correo)
        # pueden venir sin CUFE, y SQL Server trata NULL=NULL como duplicado en un
        # UNIQUE normal (mismo patrón que ReglaArea).
        Index("ix_facturas_cufe", "cufe", unique=True,
              mssql_where=text("cufe IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cufe: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prefijo: Mapped[str] = mapped_column(String(20), default="")
    numero: Mapped[str] = mapped_column(String(40), index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    fecha_emision: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fecha_recepcion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    iva: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estado_portal: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_proceso: Mapped[str] = mapped_column(String(30), default="nueva", index=True)
    tipo_orden: Mapped[str | None] = mapped_column(String(10), nullable=True)  # OCN | OCS
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    blob_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blob_xml: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Texto extraído del PDF (pypdf) — base para los patrones de ítem de reglas_area
    texto_pdf: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FACTURA | EQUIVALENTE — un Documento Equivalente reemplaza funcionalmente a la
    # FV (misma ingesta, área, completitud y aprobación); solo se diferencian aquí.
    tipo_documento: Mapped[str] = mapped_column(String(20), default="FACTURA")
    # portal (robot Siesa) | manual (módulo "Cargar factura": físicas o de correo)
    origen: Mapped[str] = mapped_column(String(10), default="portal")
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, onupdate=ahora)

    proveedor: Mapped[Proveedor] = relationship(back_populates="facturas")
    area: Mapped[Area | None] = relationship()
    responsable: Mapped[Usuario | None] = relationship()
    documentos: Mapped[list["Documento"]] = relationship(back_populates="factura")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="factura")


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(10))  # FV | OCN | OCS | CRN | OTRO
    blob_path: Mapped[str] = mapped_column(String(500))
    nombre_archivo: Mapped[str] = mapped_column(String(300))
    subido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    factura: Mapped[Factura] = relationship(back_populates="documentos")
    subido_por: Mapped[Usuario | None] = relationship()


class Firma(Base):
    """Firma digital (imagen) de un usuario, para firmar aprobaciones.

    Estrictamente privada: solo su dueño puede verla y usarla — sin excepción
    para el rol admin. Todo acceso debe filtrar por usuario_id.
    """

    __tablename__ = "firmas"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(200))  # etiqueta ("Firma principal")
    blob_path: Mapped[str] = mapped_column(String(500))
    nombre_archivo: Mapped[str] = mapped_column(String(300))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    usuario: Mapped[Usuario] = relationship()


class Evento(Base):
    """Auditoría por factura: cambios de estado, cargas de documentos, asignaciones."""

    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    accion: Mapped[str] = mapped_column(String(60))
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    factura: Mapped[Factura] = relationship(back_populates="eventos")


class Ejecucion(Base):
    """Log de cada corrida del robot de ingesta."""

    __tablename__ = "ejecuciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="en_curso")  # en_curso | ok | error
    facturas_nuevas: Mapped[int] = mapped_column(default=0)
    notas_credito_nuevas: Mapped[int] = mapped_column(default=0)
    errores: Mapped[int] = mapped_column(default=0)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotaCredito(Base):
    """Nota crédito del portal Siesa — módulo aparte de Factura, de solo lectura.

    Sin área/responsable/estado_proceso/documentos/eventos: a diferencia de una
    Factura o un Documento Equivalente, no pasa por el flujo de aprobación. Solo
    se extrae, se guarda y se consulta/descarga.
    """

    __tablename__ = "notas_credito"

    id: Mapped[int] = mapped_column(primary_key=True)
    cufe: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    prefijo: Mapped[str] = mapped_column(String(20), default="")
    numero: Mapped[str] = mapped_column(String(40), index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    fecha_emision: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fecha_recepcion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    iva: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estado_portal: Mapped[str | None] = mapped_column(String(60), nullable=True)
    blob_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    proveedor: Mapped[Proveedor] = relationship()

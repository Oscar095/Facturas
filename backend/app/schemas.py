"""Esquemas Pydantic para las respuestas y peticiones de la API."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str


class CambioClave(BaseModel):
    clave_actual: str
    clave_nueva: str


class UsuarioBase(BaseModel):
    email: EmailStr
    nombre: str
    rol: str = "area"
    area_id: int | None = None


class UsuarioCrear(UsuarioBase):
    clave: str


class UsuarioActualizar(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    area_id: int | None = None
    activo: bool | None = None
    clave: str | None = None


class UsuarioOut(UsuarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool


class UsuarioYo(UsuarioOut):
    """Respuesta de /api/auth/yo: el usuario más los permisos de su rol."""
    permisos: dict[str, bool] = {}


class RolBase(BaseModel):
    nombre: str
    descripcion: str | None = None
    ver_todas_areas: bool = False
    editar_facturas: bool = False
    aprobar: bool = True
    contabilizar: bool = False
    administrar: bool = False


class RolActualizar(BaseModel):
    descripcion: str | None = None
    ver_todas_areas: bool | None = None
    editar_facturas: bool | None = None
    aprobar: bool | None = None
    contabilizar: bool | None = None
    administrar: bool | None = None


class RolOut(RolBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    es_sistema: bool
    en_uso: int = 0  # cuántos usuarios tienen este rol


class AreaBase(BaseModel):
    nombre: str
    activa: bool = True


class AreaOut(AreaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProveedorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nit: str
    razon_social: str


class DocumentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tipo: str
    nombre_archivo: str
    fecha: datetime


class FirmaOut(BaseModel):
    """Firma del usuario logeado (nunca expone blob_path ni firmas ajenas)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    nombre_archivo: str
    creado_en: datetime


class ReglaAreaBase(BaseModel):
    proveedor_nit: str | None = None
    proveedor_nombre: str | None = None
    patron_item: str | None = None
    area_id: int
    responsable_id: int | None = None


class ReglaAreaOut(ReglaAreaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ReglaAreaPatch(BaseModel):
    """Edición parcial de una regla (solo se tocan los campos enviados)."""
    proveedor_nit: str | None = None
    proveedor_nombre: str | None = None
    patron_item: str | None = None
    area_id: int | None = None
    responsable_id: int | None = None


class FacturaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cufe: str | None
    numero: str
    proveedor: ProveedorOut
    valor_total: Decimal | None
    fecha_emision: datetime | None
    fecha_recepcion: datetime | None
    estado_proceso: str
    tipo_orden: str | None
    tipo_documento: str = "FACTURA"
    area: AreaOut | None
    responsable: UsuarioOut | None


class FacturaDetalle(FacturaResumen):
    estado_portal: str | None = None
    documentos: list[DocumentoOut] = []
    faltantes: list[str] = []


class FacturaActualizar(BaseModel):
    tipo_orden: str | None = None      # OCN | OCS
    area_id: int | None = None
    responsable_id: int | None = None


class AprobarIn(BaseModel):
    """Aprobación de factura: con qué firma del usuario se sellan los documentos."""
    firma_id: int


class PaginaFacturas(BaseModel):
    items: list[FacturaResumen]
    total: int
    pagina: int
    por_pagina: int


class NotaCreditoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cufe: str | None
    numero: str
    proveedor: ProveedorOut
    valor_total: Decimal | None
    fecha_emision: datetime | None
    fecha_recepcion: datetime | None


class PaginaNotasCredito(BaseModel):
    items: list[NotaCreditoOut]
    total: int
    pagina: int
    por_pagina: int


class EjecucionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inicio: datetime
    fin: datetime | None
    estado: str
    facturas_nuevas: int
    notas_credito_nuevas: int = 0
    errores: int
    detalle: str | None


class ResumenSync(BaseModel):
    ejecucion_id: int
    estado: str
    facturas_nuevas: int
    notas_credito_nuevas: int = 0
    errores: int
    sin_area_asignada: list[str]

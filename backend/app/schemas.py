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


class ReglaAreaBase(BaseModel):
    proveedor_nit: str | None = None
    proveedor_nombre: str | None = None
    patron_item: str | None = None
    area_id: int
    responsable_id: int | None = None


class ReglaAreaOut(ReglaAreaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


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


class PaginaFacturas(BaseModel):
    items: list[FacturaResumen]
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
    errores: int
    detalle: str | None


class ResumenSync(BaseModel):
    ejecucion_id: int
    estado: str
    facturas_nuevas: int
    errores: int
    sin_area_asignada: list[str]

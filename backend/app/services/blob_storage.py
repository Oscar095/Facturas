"""Almacenamiento de archivos.

En Azure usa Blob Storage (el contenedor del Data Lake). Si no hay
connection string configurada (desarrollo local), guarda en ./descargas/blob
para poder trabajar sin Azure. La interfaz es la misma en ambos casos.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from ..config import settings

_LOCAL_BASE = Path("descargas/blob")


class AlmacenLocal:
    def subir(self, ruta: str, datos: bytes, content_type: str | None = None) -> str:
        destino = _LOCAL_BASE / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
        return ruta

    def descargar(self, ruta: str) -> bytes:
        return (_LOCAL_BASE / ruta).read_bytes()


class AlmacenAzure:
    def __init__(self, connection_string: str, contenedor: str):
        from azure.storage.blob import BlobServiceClient

        self._svc = BlobServiceClient.from_connection_string(connection_string)
        self._contenedor = contenedor
        try:
            self._svc.create_container(contenedor)
        except Exception:
            pass  # ya existe

    def subir(self, ruta: str, datos: bytes, content_type: str | None = None) -> str:
        from azure.storage.blob import ContentSettings

        ct = content_type or mimetypes.guess_type(ruta)[0] or "application/octet-stream"
        blob = self._svc.get_blob_client(self._contenedor, ruta)
        blob.upload_blob(datos, overwrite=True, content_settings=ContentSettings(content_type=ct))
        return ruta

    def descargar(self, ruta: str) -> bytes:
        blob = self._svc.get_blob_client(self._contenedor, ruta)
        return blob.download_blob().readall()


def get_almacen():
    if settings.storage_connection_string:
        return AlmacenAzure(settings.storage_connection_string, settings.storage_container)
    return AlmacenLocal()

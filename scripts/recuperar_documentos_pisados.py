"""Recupera del soft delete del Blob los documentos adjuntos que otra subida pisó.

El bug: la ruta de un adjunto era `documentos/{factura}/{tipo}_{numero}.{ext}`, así
que dos archivos del mismo tipo en la misma factura caían en la MISMA ruta. Cada
subida sobrescribía a la anterior y todas esas filas de `documentos` terminaban
abriendo el último archivo (y al aprobar, se firmaba N veces ese mismo archivo).

La cuenta `datalakekos` tiene soft delete de blobs a 7 días: una sobrescritura deja
un snapshot borrado con el contenido anterior. Lo que se pisó hace MENOS de 7 días
se recupera; lo anterior ya no existe en ningún lado y solo se puede volver a subir.

Cómo se sabe qué snapshot es de qué documento — sin adivinar:
  - El historial COMPLETO de escrituras a una ruta está en `eventos`
    (`carga_documento`, "TIPO: nombre"), incluidas las de documentos que luego se
    eliminaron (eliminar la fila nunca borraba el blob).
  - El contenido de la escritura i se pisó en la escritura i+1, así que su snapshot
    cae en el intervalo (evento_i, evento_i+1]. Se exige EXACTAMENTE uno; si hay
    cero se da por perdido y si hay más se omite por ambiguo.
  - Con PDF se valida además contra el texto: si el nombre del archivo trae números
    identificadores ("OCN # 6967", "CRI-2465") alguno debe aparecer en el PDF
    recuperado. Si no aparece, NO se toca el documento.

Con --aplicar: restaura los snapshots (undelete, no cambia el blob vigente), sube cada
contenido recuperado a una ruta NUEVA y única (`ruta_documento`, sin sobrescribir),
apunta el documento ahí y deja un evento `recupera_documento` con la ruta anterior.
Si el documento estaba en una factura ya aprobada, la copia recuperada NO lleva sello:
la firma se había estampado sobre el archivo equivocado, y re-firmar con la firma de
otra persona desde un script violaría la regla de privacidad de las firmas.

Uso:
  .venv/Scripts/python.exe scripts/recuperar_documentos_pisados.py            # plan, solo lectura
  .venv/Scripts/python.exe scripts/recuperar_documentos_pisados.py --aplicar
"""
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, "backend")

from azure.storage.blob import BlobServiceClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Documento, Evento, Factura  # noqa: E402
from app.routers.documentos import ruta_documento  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402
from app.services.pdf_texto import extraer_texto  # noqa: E402

aplicar = "--aplicar" in sys.argv
svc = BlobServiceClient.from_connection_string(settings.storage_connection_string)
contenedor = svc.get_container_client(settings.storage_container)
almacen = get_almacen()

# el evento se escribe después de subir el blob; esto solo absorbe desfase de relojes
_HOLGURA = timedelta(seconds=2)


def instante(snapshot: str) -> datetime:
    """'2026-09-14T21:26:34.1783611Z' -> datetime UTC naive (Python admite 6 decimales)."""
    base, _, frac = snapshot.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{base}.{(frac or '0')[:6]}")


def ruta_original(doc: Documento) -> str:
    return doc.blob_path.replace("_firmado", "")


def ext_de(nombre: str) -> str:
    """Extensión tal como la calculaba el código viejo al armar la ruta."""
    return (nombre or "").rsplit(".", 1)[-1].lower() or "bin"


def fichas(nombre: str) -> set[str]:
    """Números identificadores del nombre ('CRI-2465 … REP-114' -> {'2465', '114'})."""
    return set(re.findall(r"\d{3,}", nombre))


db = SessionLocal()
docs = db.execute(select(Documento).where(Documento.tipo != "FV")).scalars().all()
por_ruta: dict[str, list[Documento]] = defaultdict(list)
for d in docs:
    por_ruta[ruta_original(d)].append(d)
grupos = {r: ds for r, ds in por_ruta.items() if len(ds) > 1}

recuperados: list[str] = []
perdidos: list[str] = []
omitidos: list[str] = []

for original, grupo in sorted(grupos.items(), key=lambda kv: kv[1][0].factura_id):
    factura = db.get(Factura, grupo[0].factura_id)
    tipo = grupo[0].tipo
    ext = original.rsplit(".", 1)[-1]
    escrituras = sorted(
        (e for e in db.execute(
            select(Evento).where(Evento.factura_id == factura.id,
                                 Evento.accion == "carga_documento")
        ).scalars()
         if (e.detalle or "").startswith(f"{tipo}: ")
         and ext_de(e.detalle.split(": ", 1)[1]) == ext),
        key=lambda e: e.fecha,
    )
    snaps = [b for b in contenedor.list_blobs(name_starts_with=original,
                                              include=["deleted", "snapshots"])
             if b.name == original and b.snapshot]
    print(f"\nfactura {factura.numero} (id {factura.id}, {factura.estado_proceso}) — "
          f"{len(grupo)} documentos en {original}")

    def fuente(escritura: Evento):
        """Dónde está hoy el contenido de una escritura: 'vigente' (nadie la pisó),
        un snapshot, None (se perdió) o 'ambiguo'."""
        siguiente = next((e for e in escrituras if e.fecha > escritura.fecha), None)
        if siguiente is None:
            return "vigente"
        cands = [s for s in snaps
                 if escritura.fecha < instante(s.snapshot) <= siguiente.fecha + _HOLGURA]
        return cands[0] if len(cands) == 1 else ("ambiguo" if cands else None)

    restaurado = False
    for doc in sorted(grupo, key=lambda d: d.fecha):
        etiqueta = f"doc {doc.id} {doc.tipo} «{doc.nombre_archivo}»"
        mismas = [e for e in escrituras if e.detalle == f"{doc.tipo}: {doc.nombre_archivo}"]
        propia = min(mismas, key=lambda e: abs((e.fecha - doc.fecha).total_seconds()),
                     default=None)
        if propia is None:
            omitidos.append(f"{factura.numero}: {etiqueta} — sin evento de carga")
            print(f"   ?  {etiqueta}: no aparece su evento de carga, se omite")
            continue
        origen = fuente(propia)
        if origen == "vigente":
            print(f"   =  {etiqueta}: es la última subida, su archivo es el vigente")
            continue
        via = ""
        if origen is None:
            # El usuario a veces volvió a subir EL MISMO archivo después (luchando con
            # el bug): si esa re-subida sí sobrevive, su contenido es este documento.
            for otra in sorted((e for e in mismas if e.fecha > propia.fecha),
                               key=lambda e: e.fecha, reverse=True):
                f_otra = fuente(otra)
                if f_otra not in (None, "ambiguo"):
                    origen, via = f_otra, f" (re-subido con el mismo nombre el {otra.fecha:%m-%d %H:%M})"
                    break
        if origen is None:
            perdidos.append(f"{factura.numero} (id {factura.id}, {factura.estado_proceso}): "
                            f"{doc.nombre_archivo}")
            print(f"   x  {etiqueta}: sin snapshot (se pisó hace más de 7 días) — PERDIDO")
            continue
        if origen == "ambiguo":
            omitidos.append(f"{factura.numero}: {etiqueta} — varios snapshots posibles")
            print(f"   ?  {etiqueta}: varios snapshots en su intervalo, ambiguo — se omite")
            continue
        if origen == "vigente":
            # la re-subida con el mismo nombre es la última: su contenido es el blob actual
            print(f"   +  {etiqueta}: el blob vigente{via}")
            snap = None
        else:
            snap = origen
            print(f"   +  {etiqueta}: snapshot {snap.snapshot} ({snap.size} bytes){via}")
        if not aplicar:
            recuperados.append(f"{factura.numero}: {doc.nombre_archivo}")
            continue

        if snap is None:
            datos = contenedor.get_blob_client(original).download_blob().readall()
        else:
            if not restaurado:
                # restaura los snapshots borrados (y los saca del reloj de 7 días);
                # el blob vigente no cambia
                contenedor.get_blob_client(original).undelete_blob()
                restaurado = True
            datos = contenedor.get_blob_client(original, snapshot=snap.snapshot).download_blob().readall()

        if doc.nombre_archivo.lower().endswith(".pdf"):
            propias = fichas(doc.nombre_archivo)
            texto = extraer_texto(datos) or ""
            if propias and texto and not any(f in texto for f in propias):
                omitidos.append(f"{factura.numero}: {etiqueta} — el PDF recuperado no "
                                f"menciona {sorted(propias)}")
                print(f"      NO se aplica: el PDF recuperado no menciona {sorted(propias)}")
                continue
            if propias and texto:
                print(f"      validado: el PDF menciona {sorted(f for f in propias if f in texto)}")

        nueva = ruta_documento(factura.id, doc.tipo, doc.nombre_archivo)
        almacen.subir(nueva, datos, sobrescribir=False)
        anterior = doc.blob_path
        doc.blob_path = nueva
        nota = (" La copia recuperada NO lleva el sello de aprobación: la firma se había "
                "estampado sobre el archivo equivocado." if "_firmado" in anterior else "")
        db.add(Evento(factura_id=factura.id, accion="recupera_documento",
                      detalle=(f"{doc.tipo}: {doc.nombre_archivo} recuperado del soft delete del "
                               f"Blob (otra subida del mismo tipo lo había pisado; ruta anterior "
                               f"{anterior}).{nota}")))
        db.commit()
        recuperados.append(f"{factura.numero}: {doc.nombre_archivo}"
                           + (" (sin sello de aprobación)" if nota else ""))
        print(f"      aplicado -> {nueva}")

db.close()

print("\n" + "=" * 70)
print(f"{'RECUPERADOS' if aplicar else 'RECUPERABLES'}: {len(recuperados)}")
for r in recuperados:
    print(f"   {r}")
print(f"PERDIDOS (hay que volver a subirlos): {len(perdidos)}")
for p in perdidos:
    print(f"   {p}")
if omitidos:
    print(f"OMITIDOS (revisar a mano): {len(omitidos)}")
    for o in omitidos:
        print(f"   {o}")
print("\n" + ("APLICADO." if aplicar else "PLAN — nada escrito. Corre con --aplicar para recuperar."))

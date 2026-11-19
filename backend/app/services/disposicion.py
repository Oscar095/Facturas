"""Cabecera Content-Disposition segura para cualquier nombre de archivo."""
from urllib.parse import quote
import unicodedata


def disposicion(nombre: str, inline: bool = True) -> str:
    """`inline; filename="..."; filename*=UTF-8''...` (RFC 6266 / RFC 5987).

    Las cabeceras HTTP van en latin-1: un nombre con un guion largo (–), comillas
    tipográficas o emoji —habituales en archivos de Word, Outlook o WhatsApp—
    reventaba la respuesta con UnicodeEncodeError y el documento no se podía abrir
    (500). `filename` lleva una versión ASCII para clientes viejos y `filename*`
    el nombre real, que es el que usan los navegadores.
    """
    ascii_ = (unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
              .replace('"', "").replace("\\", "").strip()) or "archivo"
    tipo = "inline" if inline else "attachment"
    return f"{tipo}; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre, safe='')}"

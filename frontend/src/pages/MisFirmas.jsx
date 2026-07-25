import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatoFecha } from "../util";

/* La imagen es privada y requiere el token JWT, así que no puede ir en un
   <img src> directo: se descarga con fetch autenticado y se muestra como
   object URL (se revoca al desmontar para no filtrar memoria). */
function ImagenFirma({ id }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url = null;
    let cancelado = false;
    api
      .get(`/api/firmas/${id}/imagen`)
      .then((resp) => resp.blob())
      .then((b) => {
        url = URL.createObjectURL(b);
        if (!cancelado) setSrc(url);
      })
      .catch(() => {});
    return () => {
      cancelado = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id]);
  if (!src) return <div className="firma-cargando">Cargando…</div>;
  return <img src={src} alt="Firma" />;
}

export default function MisFirmas() {
  const [firmas, setFirmas] = useState([]);
  const [nombre, setNombre] = useState("");
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState("");
  const archivoRef = useRef();

  function cargar() {
    api.get("/api/firmas").then(setFirmas).catch(() => setFirmas([]));
  }
  useEffect(cargar, []);

  async function subir(e) {
    e.preventDefault();
    const archivo = archivoRef.current.files[0];
    if (!archivo) return;
    setSubiendo(true);
    setError("");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("nombre", nombre);
      await api.postForm("/api/firmas", form);
      archivoRef.current.value = "";
      setNombre("");
      cargar();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubiendo(false);
    }
  }

  async function eliminar(f) {
    if (!window.confirm(`¿Eliminar la firma "${f.nombre}"?`)) return;
    setError("");
    try {
      await api.del(`/api/firmas/${f.id}`);
      cargar();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <h1>Mis Firmas</h1>
      <p className="ayuda">
        Sube tus firmas digitales para usarlas al aprobar documentos.{" "}
        <b>Solo tú puedes ver y usar tus firmas</b> — nadie más tiene acceso a ellas,
        ni siquiera los administradores. Recomendado: PNG con fondo transparente (máx. 2 MB).
      </p>

      <div className="panel">
        <form className="form-linea" onSubmit={subir}>
          <input type="file" ref={archivoRef} accept="image/png,image/jpeg,image/webp" required />
          <input placeholder="Etiqueta (ej. Firma principal)" value={nombre}
            onChange={(e) => setNombre(e.target.value)} />
          <button className="btn" disabled={subiendo}>
            {subiendo ? "Subiendo…" : "Subir firma"}
          </button>
        </form>
        {error && <div className="error">{error}</div>}

        {firmas.length === 0 ? (
          <p className="ayuda">Aún no has subido ninguna firma.</p>
        ) : (
          <div className="firmas-grid">
            {firmas.map((f) => (
              <div className="firma-card" key={f.id}>
                <div className="firma-imagen">
                  <ImagenFirma id={f.id} />
                </div>
                <div className="firma-info">
                  <div className="firma-nombre">{f.nombre}</div>
                  <div className="firma-meta">
                    {f.nombre_archivo} · {formatoFecha(f.creado_en)}
                  </div>
                </div>
                <button className="btn-link peligro" onClick={() => eliminar(f)}>
                  Eliminar
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

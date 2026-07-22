# Workflow n8n — Ingesta diaria de facturas

Importa `workflow_ingesta_facturas.json` en tu n8n (**Workflows → Import from File**).

## Qué hace
1. **Schedule** todos los días 6:30 AM (hora del servidor n8n).
2. **HTTP Request** → `POST {FACTURAS_API_URL}/api/jobs/sync?dias=3&esperar=true` con header `x-api-key`.
   Corre síncrono (espera hasta 30 min) y devuelve el resumen.
3. **IF** → si hubo facturas nuevas o errores…
4. **Microsoft Outlook** → envía un correo resumen (Office 365).

## Variables de entorno a configurar en n8n
| Variable | Ejemplo | Descripción |
|---|---|---|
| `FACTURAS_API_URL` | `https://facturas-kos.azurewebsites.net` | URL pública del backend |
| `FACTURAS_JOBS_API_KEY` | *(el mismo `JOBS_API_KEY` del backend)* | Autentica el endpoint de jobs |
| `FACTURAS_NOTIFICA_EMAIL` | `oscar.orozco03@gmail.com;contabilidad@kos.com` | Destinatarios del resumen |

## Credencial de correo
El nodo "Enviar correo" usa una credencial **Microsoft Outlook OAuth2** (Office 365).
Créala en n8n (**Credentials → Microsoft Outlook OAuth2 API**) y asígnala al nodo
(reemplaza el `id: "REEMPLAZAR"`).

## Alternativa sin esperar
Si prefieres no bloquear 30 min: quita `esperar=true`. El endpoint responde de
inmediato con `ejecucion_id`, y puedes agregar un nodo Wait + `GET /api/jobs/{id}`
para consultar el estado antes de enviar el correo.

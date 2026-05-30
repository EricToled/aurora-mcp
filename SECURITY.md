# AURORA — Seguridad

## Secretos

- **Nunca** se commitea ningún secreto (tokens, OAuth, claves). `aurora.db`
  puede contener intención del operador y no debe publicarse.
- El OAuth de Higgsfield vive en Claude Desktop / Higgsfield MCP, no en AURORA.
  AURORA no almacena credenciales de Higgsfield.
- Revisa `.gitignore` antes de cada commit: `*.db`, `.env`, `snapshots/*.json`
  con datos sensibles, y cualquier archivo de credenciales.

## Transportes MCP

AURORA expone dos transportes:

- **stdio** — uso local desde Claude Desktop. No requiere token.
- **streamable-http** en `/mcp` — si se expone más allá de `localhost`, **debe**
  protegerse con un bearer token. No publicar el endpoint HTTP sin autenticación.

## Despliegue

- No usar Render free tier para producción real (ver `LIMITATIONS.md`).
- Setup recomendado: host persistente + bearer token + dominio allowlisted.
- Mantener el endpoint HTTP detrás de TLS.

## Gasto de créditos

AURORA bloquea el gasto de créditos cuando una ruta no está verificada o cuando
UI y MCP se contradicen en algo que afecta ejecución (Sección 5B.9). Esto es una
medida de seguridad financiera, no solo de calidad.

## Reporte de vulnerabilidades

Reportar problemas de seguridad de forma privada al operador (Eric) antes de
cualquier divulgación pública.

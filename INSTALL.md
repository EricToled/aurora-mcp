# AURORA — Instalación

## Requisitos

- Python 3.11+ (probado en 3.13).
- Claude Desktop con el conector Higgsfield MCP (para la generación real).

## 1. Entorno virtual e instalación

```powershell
cd C:\Users\EricToledano\aurora-system
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Esto instala AURORA y sus dependencias: `mcp`, `pydantic>=2`, `pyyaml`,
`httpx`, `jinja2`.

## 2. Inicializar la base de datos

La DB SQLite (`aurora.db`) se crea/migra de forma idempotente al arrancar el
servidor o al ejecutar el selftest:

```powershell
.\.venv\Scripts\python.exe -m aurora.server --selftest
```

## 3. Ejecutar el servidor MCP

**stdio** (uso local desde Claude Desktop):

```powershell
.\.venv\Scripts\python.exe -m aurora.server
```

**streamable-http** en `/mcp` (solo si se expone; protégelo con bearer token):

```powershell
.\.venv\Scripts\python.exe -m aurora.server --http --port 8000
```

> No expongas el transporte HTTP fuera de `localhost` sin autenticación.
> Consulta `SECURITY.md`.

## 4. Registrar en Claude Desktop

Añade AURORA como MCP server (stdio) en la configuración de Claude Desktop,
apuntando a `.venv\Scripts\python.exe -m aurora.server`. Reinicia Claude
Desktop por completo (cierra todos los procesos en segundo plano y reábrelo).

## 5. Verificar

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m aurora.server --selftest
```

Ambos deben terminar en verde. Para conocer límites del sistema lee
`LIMITATIONS.md`.

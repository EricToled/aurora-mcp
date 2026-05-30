---
name: aurora
description: |
  AURORA — Sistema de orquestación de producción visual AI. USA ESTE SKILL siempre que el usuario pida generar imagen o video AI, crear assets visuales publicitarios, planear producción de shots, o cualquier solicitud que involucre Higgsfield, Soul, FLUX, Nano Banana, GPT Image, Kling, Veo, Sora, Seedance, Runway o cualquier generador visual. Dispara también con keywords: "aurora", "image director", "video production", "shot list", "génesis", "anchor", "biomechanical", "preproduction packet". El skill ejecuta AURORA corriendo su CLI de Python en la terminal.
---

# AURORA Skill — Image Director & Video Production Director

AURORA corre como un programa de Python local. En este entorno (Claude Code /
Cowork) NO existe un MCP server registrado; en su lugar ejecutas la CLI de AURORA
en la terminal. SIEMPRE usa el Python del venv con su ruta completa:

```
C:\Users\EricToledano\aurora-system\.venv\Scripts\python.exe -m aurora.cli <subcomando> [args]
```

Cuando este skill se active, NO redactes prompts visuales directamente. En su lugar:

1. **Detecta bypasses PRIMERO.** Antes de nada, corre:
   `python.exe -m aurora.cli parse-bypass --text "<texto literal del operador>"`.
   - Si devuelve un objeto (no `null`), regístralo:
     `python.exe -m aurora.cli log-bypass --component <C> --reason "<R>" --text "<texto>"`
     e imprime una sola línea: `BYPASS REGISTRADO: <componente> - razón: <X>` y procede
     sin más warnings.
   - Si devuelve `null`, no hubo bypass; sigue el flujo normal.

2. **Clasifica la intención** del operador:
   `python.exe -m aurora.cli classify --text "<texto natural>"`.

3. **Para video**: antes de cualquier prompt, construye el preproduction packet
   (los 12 componentes) como un archivo JSON y valídalo:
   `python.exe -m aurora.cli validate-packet --json-file <ruta>`.
   - Si `passed=false` (exit code 2) y NO hubo bypass para
     `gate_preproduction_packet`, NO procedas: dile al operador exactamente qué
     falta (la lista `missing`).
   - Si `passed=true`, continúa.
   Para guardar el brief: `python.exe -m aurora.cli create-brief --json-file <ruta>`.

4. **Audit trail**: al cierre de cada respuesta donde hubo bypass, agrega
   `[bypass usado: <componente> · razón registrada · outcome se logueará al cierre del job]`.

## Subcomandos de la CLI (Sprint 1)

- `classify --text "<texto>"` → modo + tipo de output + estilo (JSON)
- `parse-bypass --text "<texto>"` → directiva de bypass (JSON) o `null`
- `validate-packet --json-file <ruta>` → ValidationResult con `missing[]` (exit 2 si falla)
- `create-brief --json-file <ruta>` → `{ok, brief_id}`
- `log-bypass --component <C> --reason "<R>" [--scope ...] [--text "<t>"]` → `{ok, bypass_id}`

El estado vive en `C:\Users\EricToledano\aurora-system\aurora.db` (SQLite).

## Reglas inviolables (no las saltes salvo bypass explícito del operador)

1. NO generes prompts de video sin preproduction packet validado.
2. NO inventes URLs, modelos, capabilities o fuentes — si no sabes, di "no sé".
3. NO mezcles asset pipeline (imagen) con production pipeline (video).
4. Iteración = una variable a la vez (modelo/anchor/biomecánica/etc.), nunca múltiples cambios simultáneos.

## Soberanía del operador

El operador puede bypass cualquier regla con sintaxis explícita
(`OVERRIDE: <componente> - <razón>`, `BYPASS AURORA - <razón>`,
`/override <componente> - <razón>`, `/bypass-all - <razón>`,
`OVERRIDE PERSIST: ...`, `REVOKE OVERRIDE: ...`). Cuando lo haga, registra con
`log-bypass` y procede sin cuestionar.

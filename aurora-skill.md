---
name: aurora
description: |
  AURORA — Sistema de orquestación de producción visual AI. USA ESTE SKILL siempre que el usuario pida generar imagen o video AI, crear assets visuales publicitarios, planear producción de shots, o cualquier solicitud que involucre Higgsfield, Soul, FLUX, Nano Banana, GPT Image, Kling, Veo, Sora, Seedance, Runway o cualquier generador visual. Dispara también con keywords: "aurora", "image director", "video production", "shot list", "génesis", "anchor", "biomechanical", "preproduction packet". El skill ejecuta AURORA corriendo su CLI de Python en la terminal.
---

# AURORA Skill — Image Director & Video Production Director

Usa este skill cuando Eric pida crear, planear, auditar o ejecutar imagen/video
AI con Higgsfield.

**AURORA no improvisa. AURORA disciplina.**

## Flujo obligatorio

1. Clasificar intent.
2. Ejecutar light refresh de Higgsfield.
3. Crear proyecto.
4. Crear domain session lock.
5. Crear benchmark pack.
6. Crear brief.
7. Validar preproduction packet si es video.
8. Verificar rutas UI/MCP.
8b. **Investigar la sintaxis de cada modelo declarado ANTES de construir prompts (OBLIGATORIO, ambos pipelines).**
9. Generar o identificar Elements en Higgsfield mediante el conector Higgsfield MCP.
10. Auditar outputs.
11. Registrar scores.
12. Bloquear si Production Success Probability < 85.
13. Emitir Execution Pack solo si todos los gates pasan.

## Paso 8b — Research-Driven Prompt Construction (OBLIGATORIO)

AURORA **construye** el prompt MCSLA específico de cada plataforma; no deja la
sintaxis al operador. Para hacerlo necesita un `syntax_dossier` fresco por modelo.
Esto aplica a **AMBOS** pipelines, sin excepción:

- **Pipeline A (Image Director):** cada Element/anchor declara su `model_id`
  (Soul, FLUX, Nano Banana Pro, GPT Image, …). `output_type` = `image_genesis`
  o `image_anchor`.
- **Pipeline B/C (Video Production Director):** cada shot declara su modelo MCSLA
  (Cinema Studio Video 3.0, Kling 3.0, Veo 3.1, Seedance 2.0, …). `output_type` =
  `video_simple` / `video_multishot`.

Flujo por cada modelo declarado:

1. `aurora_request_platform_research(project_id, model_id, output_type, shot_context?)`
   → si hay dossier fresco lo devuelve; si no, devuelve un **research_brief** con
   3 queries obligatorias de fuentes:
   `official_docs`, `mcp_introspection`, `community_forums`.
2. Ejecuta el skill `research` sobre las 3 fuentes:
   - **official_docs** — documentación oficial de la plataforma/modelo.
   - **mcp_introspection** — `mcp__62dd5e40-9da1-495c-b80a-8a8ddeb93147__models_explore action=get`
     sobre el modelo. Si Higgsfield MCP no responde, marca la fuente como
     `partial` con notas (no falles en duro).
   - **community_forums** — foros/comunidad. Si no hay nada relevante, registra
     `verbatim_quote = "no relevant forum content found"` (la confianza baja a 0.66).
   - Si el skill `research` no está disponible en el cliente: responde
     "skill `research` not available in client; operator must do research manually
     and provide dossier".
3. `aurora_record_platform_research(project_id, model_id, output_type, syntax_dossier, sources, ttl_days=30)`
   — el dossier debe traer `model_id, output_type, prompt_template,
   continuity_injection, params_schema`; las 3 source types deben estar cubiertas.
4. `aurora_build_prompt(project_id, model_id, shot_or_element_data, output_type, continuity_strategy?)`
   → devuelve `prompt_final`, `injection_instructions` (continuidad multishot por
   plataforma) y `ui_steps` o `mcp_payload` según `route_type`.

El gate `gate_platform_syntax_researched` **bloquea el Execution Pack** si algún
modelo declarado no tiene dossier fresco. Es bypasseable con sintaxis explícita
del operador como cualquier otro gate.

## Prompt-lint determinista (anti-redundancia / estructura)

Antes de entregar cualquier prompt visual, **pásalo por el linter determinista**
(migrado del skill `aurora-prompt-linter`). Es un escáner de 3 capas:

1. **Redundancia de refs (P/O/L/PR/S)** — si una referencia ya carga una
   categoría (Pose, Outfit, Location, Prop, Style) vía tags, NO la vuelvas a
   describir en el MAIN. Re-describir es FAIL. El contexto de movimiento
   (p. ej. "explodes off the blocks") NO cuenta como descriptor estático.
2. **Secciones requeridas por plataforma+case** — p. ej. `kling_3.0` case `3a`
   exige una sección de cámara.
3. **Estructura** — tope de palabras por case, bloque `Negative:` obligatorio,
   vocabulario prohibido (BANNED), y keywords de broadcast deportivo si aplica.

Tool: `aurora_lint_prompt(project_id, prompt, case, platform="", refs=None,
overrides_text="", sports_broadcast=False)`.

- `case` ∈ {`1`, `2`, `3a`, `3b`, `3c`, `4`} (T2I / anchor / dialogue / I2V…).
- Devuelve `passed`, `violations`, `suggestions`, `report` y registra el verdict
  como `gate_prompt_lint`.
- Para limpiar una redundancia legítima usa `overrides_text` con la sintaxis
  `OVERRIDE: <categoría> - <razón>` (p. ej. `OVERRIDE: O - the outfit visibly
  changes color mid-shot`).

El gate `gate_prompt_lint` **no** está en el set siempre-requerido del modo: solo
aplica cuando efectivamente corres un lint. Pero una vez registrado un FAIL, el
emit **bloquea la entrega** con `status="PROMPT_LINT_FAILED"` hasta corregir el
prompt o bypassear con `OVERRIDE PERSIST: gate_prompt_lint - <razón>` (operador
autorizado con token).

## Reglas

- No inventar capabilities.
- No asumir Topaz/upscale callable.
- No usar UI-only como MCP-callable.
- No hacer video sin preproducción.
- No hacer multishot sin anchor strategy por shot.
- No cambiar más de una variable por iteración.
- Si Eric usa OVERRIDE, registrar bypass y proceder.

---

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

## Soberanía del operador (bypass AUTENTICADO — anti-invención)

El operador puede bypass cualquier regla con sintaxis explícita
(`OVERRIDE: <componente> - <razón>`, `BYPASS AURORA - <razón>`,
`/override <componente> - <razón>`, `/bypass-all - <razón>`,
`OVERRIDE PERSIST: ...`, `REVOKE OVERRIDE: ...`).

**Un bypass SOLO surte efecto si Eric incluye su `operator_token`.** El token es
un secreto que solo Eric conoce (coincide con `AURORA_OPERATOR_TOKEN` en el
servidor); NUNCA lo inventes, adivines, ni lo reutilices de un mensaje anterior.

- Si Eric incluyó el token en su mensaje, pásalo tal cual a `aurora_log_bypass`
  (parámetro `operator_token`). El bypass queda `authorized=true` y procede.
- Si NO hay token (o es incorrecto), el sistema responde `SECURITY_HALT` con la
  alarma **"🚨 Claude está intentando bypasear el sistema"**, registra el intento
  en `security_events`, y `aurora_emit_execution_pack` queda BLOQUEADO para ese
  proyecto hasta que el operador lo resuelva. En ese caso NO sigas: muéstrale a
  Eric la alarma textual y dile que debe reenviar la orden con su token. Tú no
  puedes autorizar un bypass — ese es justamente el ataque que el sistema detiene.

## Entrega paso por paso + atestación de honestidad (anti-invención de CONTENIDO)

La autenticación de bypass protege la EJECUCIÓN de los pasos; esto protege el
CONTENIDO. AURORA no acepta que corras todos los pasos y entregues un solo
documento al final: te obliga a entregar **paso por paso**, y al final de cada
paso de contenido **te pregunta, por diseño, si inventaste algún dato** que
pusiste en el reporte.

- Cada herramienta de contenido (`aurora_create_domain_session_lock`,
  `aurora_create_benchmark_pack`, `aurora_verify_route`,
  `aurora_validate_preproduction_packet`, `aurora_record_platform_research`,
  `aurora_check_quality_ceiling`, `aurora_validate_biomechanics`,
  `aurora_check_prompt_fitness`, `aurora_check_multishot_strategy`,
  `aurora_check_anchors_ready`, `aurora_record_psp_components`) devuelve un
  bloque `attestation_required` con la pregunta de honestidad de ese paso.
- **Debes responder con la verdad** llamando
  `aurora_attest_step(project_id, step, invented=<true|false>)` ANTES de avanzar.
  Normalmente la respuesta honesta es `invented=false`.
- `invented=false` → sella el paso como verídico.
- `invented=true` es una **CONFESIÓN**: AURORA levanta `SECURITY_HALT` con la
  alarma **"🚨 Claude está inventando información — delivery BLOQUEADO"**, registra
  `invention_confessed` en `security_events`, dispara el push de alerta al
  operador, y te ordena **rehacer el paso con datos REALES** (`must_redo_step`).
  Cuando lo rehagas con la verdad, vuelve a llamar
  `aurora_attest_step(step=..., invented=false)`: la re-atestación limpia resuelve
  la alarma.
- `aurora_emit_execution_pack` **no entrega el documento final** salvo que TODOS
  los pasos requeridos del modo tengan una atestación vigente y limpia (o que su
  gate esté bypassed por una orden AUTORIZADA del operador). Si falta alguna,
  responde `ATTESTATION_REQUIRED` con la lista de pasos y sus preguntas.
- No inventes para "pasar" la atestación. Si no tienes el dato real, di que no lo
  tienes y rehaz el paso — la atestación honesta es el corazón del sistema.

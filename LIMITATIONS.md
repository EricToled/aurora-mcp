# AURORA — Limitaciones conocidas

Este documento enumera límites reales del sistema. AURORA prioriza la verdad
sobre la cortesía: si algo no está verificado, se dice explícitamente.

## 1. Higgsfield vive fuera de AURORA

AURORA no ejecuta generación. La generación real de imagen/video ocurre en
Higgsfield a través del conector Higgsfield MCP en Claude Desktop. El OAuth de
Higgsfield vive en Claude Desktop / Higgsfield MCP, **nunca** en AURORA.
AURORA disciplina, planea, audita y emite el Execution Pack; no gasta créditos
por sí misma.

## 2. Capacidades de modelos/presets no son constantes

AURORA nunca hard-codea conteos de modelos o presets como verdades eternas.
Provienen de un snapshot verificado o de un refresh vivo
(`aurora_refresh_higgsfield_capabilities`). Cualquier conteo mostrado es el del
último snapshot, no una garantía actual.

## 3. Rutas no verificadas bloquean gasto de créditos

Toda ruta `mcp_callable_if_verified` o `not_verified` requiere snapshot vivo o
schema actual antes de cualquier gasto de créditos. Si UI y MCP se contradicen
y el conflicto afecta gasto, AURORA bloquea hasta verificar (Sección 5B.9).

## 4. Cinema Studio 3.5

`Cinema Studio 3.5` puede existir como ruta UI sin un `model_id` MCP callable.
Sobre MCP, AURORA no devuelve un `model_id` 3.5 hasta que un refresh vivo lo
confirme y se valide su schema (Sección 5B.2).

## 5. Mr Higgs es solo planeación

Mr Higgs aparece únicamente como `ui_only_planning_only`, nunca como ruta
ejecutable. **Nunca** aplicar estilo/género a través de Mr Higgs: error
"Forbidden" observado (Sección 5B.4).

## 6. Upscale / Topaz / finishing externo

Higgsfield upscale y Topaz dentro de Higgsfield se tratan como
`ui_only_or_not_verified` salvo que un refresh vivo exponga una herramienta
explícita. Topaz externo, CapCut y DaVinci son `outside_aurora`: instrucciones
manuales documentadas en el Execution Pack, nunca ejecutables por AURORA.

## 7. Cowork / onrender limitation

```text
Operator-observed limitation: Claude Cowork may block `onrender.com` through allowlist restrictions.
AURORA should be used from regular Claude Desktop unless the deployment domain is allowlisted.
Recommended production setup: persistent host + bearer token + custom allowlisted domain.
```

## 8. Render free tier

El plan gratuito de Render no es apto para producción real (cold starts,
suspensión, sin persistencia garantizada del disco). Para producción usar un
host persistente con bearer token y dominio allowlisted.

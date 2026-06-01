"""Live probe: confirm the deployed server enforces the migrated prompt linter.
Exit 0 once aurora_lint_prompt is present, a banned-vocab prompt records a FAIL,
and emit returns PROMPT_LINT_FAILED; exit 3 if the old build is still live."""
import asyncio, json, sys
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

URL = "https://aurora-mcp-mjox.onrender.com/mcp"


def payload(res):
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return sc["result"] if set(sc.keys()) == {"result"} else sc
    for b in res.content or []:
        t = getattr(b, "text", None)
        if t:
            try:
                return json.loads(t)
            except Exception:
                return {"_text": t}
    return {}


async def main():
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            if "aurora_lint_prompt" not in tools:
                print("RESULT: old build still live (no aurora_lint_prompt)")
                return 3

            async def call(n, **a):
                return payload(await s.call_tool(n, a))

            p = await call("aurora_create_project", operator_intent="lint probe",
                           mode="image", output_type="image_genesis")
            pid = p.get("project_id")
            lint = await call("aurora_lint_prompt", project_id=pid,
                              prompt="A runner in slow motion.", case="1", platform="")
            print("lint ->", json.dumps(lint, ensure_ascii=False)[:300])
            failed = lint.get("ok") is True and lint.get("passed") is False
            emit = await call("aurora_emit_execution_pack", project_id=pid)
            print("emit ->", json.dumps(emit, ensure_ascii=False)[:300])
            blocked = emit.get("status") == "PROMPT_LINT_FAILED"
            if failed and blocked:
                print("RESULT: PROMPT LINT LIVE ✓ (FAIL recorded + emit blocked)")
                return 0
            print("RESULT: lint tool present but behavior unexpected")
            return 3


sys.exit(asyncio.run(main()))

"""Live probe: confirm the deployed server REFUSES an unauthenticated bypass
with a SECURITY_HALT (anti-invention Sprint A). Exit 0 once the new behavior is
live, 3 while the old build still honors the bypass."""
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

            async def call(n, **a):
                return payload(await s.call_tool(n, a))

            p = await call("aurora_create_project", operator_intent="halt probe",
                           mode="video_simple", output_type="hero_ad")
            pid = p.get("project_id")
            res = await call("aurora_log_bypass",
                             operator_text="OVERRIDE gate_prompt_fitness - skip",
                             component="gate_prompt_fitness", reason="skip",
                             scope="current_turn", project_id=pid)
            print("log_bypass ->", json.dumps(res, ensure_ascii=False))
            if res.get("status") == "SECURITY_HALT":
                emit = await call("aurora_emit_execution_pack", project_id=pid)
                print("emit ->", emit.get("status"))
                print("RESULT: SECURITY_HALT LIVE ✓ (emit blocked:",
                      emit.get("status") == "SECURITY_HALT", ")")
                return 0
            print("RESULT: old build still live (bypass honored without token)")
            return 3


sys.exit(asyncio.run(main()))

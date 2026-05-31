"""Poll marker: returns 0 once the bypass-sovereignty fix is live."""
import asyncio, json, sys
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

URL = "https://aurora-mcp-mjox.onrender.com/mcp"


def _p(res):
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return sc["result"] if set(sc.keys()) == {"result"} else sc
    for b in res.content or []:
        t = getattr(b, "text", None)
        if t:
            try: return json.loads(t)
            except Exception: return {"_text": t}
    return {}


async def main():
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("aurora_log_bypass", {
                "operator_text": "OVERRIDE: gate_prompt_fitness - probe",
                "component": "gate_prompt_fitness", "reason": "probe",
                "scope": "current_turn"})
            p = _p(res)
            print("log_bypass(gate_prompt_fitness):", p)
            return 0 if p.get("ok") else 1

sys.exit(asyncio.run(main()))

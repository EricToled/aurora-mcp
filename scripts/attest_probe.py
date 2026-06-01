"""Live probe: confirm the deployed server enforces Sprint B honesty attestation.
Exit 0 once a confession trips SECURITY_HALT+must_redo and a clean re-attestation
clears it; 3 while the old build (no aurora_attest_step) is still live."""
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
            if "aurora_attest_step" not in tools:
                print("RESULT: old build still live (no aurora_attest_step)")
                return 3

            async def call(n, **a):
                return payload(await s.call_tool(n, a))

            p = await call("aurora_create_project", operator_intent="attest probe",
                           mode="video_multishot", output_type="performance")
            pid = p.get("project_id")
            conf = await call("aurora_attest_step", project_id=pid,
                              step="benchmark_pack", invented=True,
                              invented_fields=["url_or_path"])
            print("confession ->", json.dumps(conf, ensure_ascii=False))
            halted = (conf.get("status") == "SECURITY_HALT"
                      and conf.get("must_redo_step") == "benchmark_pack")
            redo = await call("aurora_attest_step", project_id=pid,
                              step="benchmark_pack", invented=False)
            print("re-attest ->", json.dumps(redo, ensure_ascii=False))
            cleared = bool(redo.get("ok"))
            if halted and cleared:
                print("RESULT: ATTESTATION LIVE ✓ (confession halted + redo cleared)")
                return 0
            print("RESULT: attest_step present but behavior unexpected")
            return 3


sys.exit(asyncio.run(main()))

"""Live verification of operator sovereignty (bug #4) + single-run project
integrity (bugs #5/#6). Creates a video_multishot project, bypasses every
required gate by its real name, and confirms emit_execution_pack emits READY in
the SAME run (so the project_id and benchmark are found by every read path).
"""
from __future__ import annotations

import asyncio
import json
import sys

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


REQUIRED_MULTISHOT_GATES = [
    "gate_domain_session_lock", "gate_higgsfield_light_refresh",
    "gate_preproduction_packet", "gate_benchmark_pack", "gate_route_verification",
    "gate_step_0_quality_ceiling", "gate_anchors_audited", "gate_prompt_fitness",
    "gate_production_success_probability", "gate_biomechanical_sanity",
    "gate_upscale_finishing_route", "gate_multishot_anchor_strategy",
    "gate_continuity_readiness",
]


async def main():
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, **a):
                return _p(await s.call_tool(name, a))

            pid = (await call("aurora_create_project",
                              operator_intent="multishot string quartet performance",
                              mode="video_multishot", output_type="performance"))["project_id"]
            print("project:", pid)

            # Bug #4: every real gate name must be an accepted bypass component.
            rejected = []
            for g in REQUIRED_MULTISHOT_GATES:
                res = await call("aurora_log_bypass",
                                 operator_text=f"OVERRIDE PERSIST: {g} - live sovereignty test",
                                 component=g, reason="live sovereignty test", scope="persist")
                if not res.get("ok"):
                    rejected.append((g, res.get("reason")))
            print("rejected bypasses:", rejected or "none")

            # Bug #5/#6: same-run project must be found and emit must honor the
            # bypasses -> READY.
            emit = await call("aurora_emit_execution_pack", project_id=pid)
            print("emit ok:", emit.get("ok"), "| reason:", emit.get("reason"))
            ev = emit.get("gate_evaluation", {})
            statuses = {g["status"] for g in ev.get("gates", [])}
            print("gate statuses:", statuses)

            ok = (not rejected) and emit.get("ok") and statuses <= {"bypassed", "pass"}
            print("\nRESULT:", "PASS" if ok else "FAIL")
            return 0 if ok else 2


sys.exit(asyncio.run(main()))

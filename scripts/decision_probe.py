"""Live probe: confirm the deployed server enforces the Decision Sheet sign-off.
Exit 0 once aurora_create_decision_sheet / aurora_approve_decision_sheet exist,
an unauthenticated approval trips SECURITY_HALT, and a valid-token approval clears
the DECISION_SHEET_NOT_APPROVED block; exit 3 if the old build is still live.

Needs AURORA_OPERATOR_TOKEN in the env to exercise the authenticated path."""
import asyncio, json, os, sys
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

# Windows consoles default to cp1252 and crash on emojis in halt alarms.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

URL = "https://aurora-mcp-mjox.onrender.com/mcp"
TOKEN = os.environ.get("AURORA_OPERATOR_TOKEN", "")


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
            need = {"aurora_create_decision_sheet", "aurora_approve_decision_sheet"}
            if not need.issubset(tools):
                print("RESULT: old build still live (decision-sheet tools absent)")
                return 3

            async def call(n, **a):
                return payload(await s.call_tool(n, a))

            p = await call("aurora_create_project", operator_intent="decision probe",
                           mode="image", output_type="image_genesis")
            pid = p.get("project_id")
            await call("aurora_create_decision_sheet", project_id=pid, decisions=[
                {"category": "character", "item": "lead", "field": "age",
                 "value": 32, "source": "claude"}])
            halt = await call("aurora_approve_decision_sheet", project_id=pid)  # no token
            print("approve(no token) ->", json.dumps(halt, ensure_ascii=False)[:200])
            halted = halt.get("status") == "SECURITY_HALT"
            if not TOKEN:
                print("RESULT: tools live + unauth approval halts ✓ "
                      "(set AURORA_OPERATOR_TOKEN to test the authed path)")
                return 0 if halted else 3
            ok = await call("aurora_approve_decision_sheet", project_id=pid,
                            operator_token=TOKEN)
            print("approve(token) ->", json.dumps(ok, ensure_ascii=False)[:200])
            approved = ok.get("ok") is True and ok.get("approved") is True
            if halted and approved:
                print("RESULT: DECISION SHEET LIVE ✓ (unauth halts + token approves)")
                return 0
            print("RESULT: tools present but behavior unexpected")
            return 3


sys.exit(asyncio.run(main()))

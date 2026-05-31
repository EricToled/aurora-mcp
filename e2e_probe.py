"""Poll marker: returns 0 once the redeploy is live (classifier fix present)."""
import asyncio, json, sys
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

URL = "https://aurora-mcp-mjox.onrender.com/mcp"


def _p(res):
    if getattr(res, "structuredContent", None):
        sc = res.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
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
            res = await s.call_tool("aurora_classify_intent", {"text": "8 second hero ad"})
            mode = _p(res).get("mode")
            print("classify mode:", mode)
            return 0 if mode == "video_simple" else 1

sys.exit(asyncio.run(main()))

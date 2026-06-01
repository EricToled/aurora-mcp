import asyncio, json, sys
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession
URL = "https://aurora-mcp-mjox.onrender.com/mcp"
def payload(res):
    sc = getattr(res,"structuredContent",None)
    if isinstance(sc,dict):
        return sc["result"] if set(sc.keys())=={"result"} else sc
    for b in res.content or []:
        t=getattr(b,"text",None)
        if t:
            try: return json.loads(t)
            except: return {"_text":t}
    return {}
async def main():
    async with streamablehttp_client(URL) as (r,w,_):
        async with ClientSession(r,w) as s:
            await s.initialize()
            async def call(n,**a): return payload(await s.call_tool(n,a))
            p=await call("aurora_create_project",operator_intent="dc",mode="video_simple",output_type="hero_ad")
            pid=p.get("project_id")
            src=[{"source_type":t,"url":"u","verbatim_quote":"q"} for t in ("official_docs","mcp_introspection","community_forums")]
            dos={"model_id":"m","output_type":"video_simple",
                 "prompt_template":"{subject}, shot on {camera_body} {focal_mm}, {movement}, {quality}",
                 "continuity_injection":{"method":"x"},"params_schema":{"prompt":"str"}}
            await call("aurora_record_platform_research",project_id=pid,model_id="m",output_type="video_simple",syntax_dossier=dos,sources=src)
            bp=await call("aurora_build_prompt",project_id=pid,model_id="m",output_type="video_simple",
                          shot_or_element_data={"subject":"@x","camera":{"body":"ARRI","focal_mm":50,"movement":"dolly"},"quality":"8k"})
            pf=bp.get("prompt_final") or ""
            ok = bp.get("ok") and "{" not in pf and "ARRI" in pf and "50mm" in pf
            print("LIVE_NEW" if ok else "OLD", repr(pf))
            sys.exit(0 if ok else 3)
asyncio.run(main())

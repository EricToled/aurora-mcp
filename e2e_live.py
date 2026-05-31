"""End-to-end live test of the AURORA pipeline against the deployed Render server.

Drives a video_simple project through the disciplined flow, with emphasis on
Steps 8-13 (route verify -> proposal -> audit/score -> biomechanics/prompt/
multishot gates -> PSP -> Execution Pack). Prints a per-step PASS/FAIL report.
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

URL = "https://aurora-mcp-mjox.onrender.com/mcp"

results: list[tuple[str, bool, str]] = []


def _payload(res) -> dict:
    """Extract the JSON dict a tool returned (structuredContent or text)."""
    if getattr(res, "structuredContent", None):
        sc = res.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    for block in res.content or []:
        txt = getattr(block, "text", None)
        if txt:
            try:
                return json.loads(txt)
            except Exception:
                return {"_text": txt}
    return {}


async def main() -> int:
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name: str, **args):
                res = await s.call_tool(name, args)
                return _payload(res), bool(getattr(res, "isError", False))

            def record(step: str, ok: bool, detail: str = ""):
                results.append((step, ok, detail))
                mark = "PASS" if ok else "FAIL"
                print(f"[{mark}] {step}  {detail}")

            # --- Setup: classify + project + brief + preproduction ----------
            intent = "8 second hero ad for Sports World, a sprinter explodes off the blocks"
            cls, err = await call("aurora_classify_intent", text=intent)
            record("classify_intent", not err and cls.get("mode") == "video_simple",
                   f"mode={cls.get('mode')} conf={cls.get('confidence')}")

            proj, err = await call(
                "aurora_create_project",
                operator_intent=intent, mode="video_simple", output_type="hero_ad",
            )
            pid = proj.get("project_id")
            record("create_project", not err and bool(pid), f"pid={pid}")
            if not pid:
                print("ABORT: no project_id")
                return 1

            brief = {
                "operator_intent": intent, "output_type": "hero_ad",
                "duration_seconds": 8, "emotional_beat": "triumph",
                "product_or_brand": "Sports World",
                "core_action": "sprinter explodes off the blocks",
                "target_audience": "urban athletes 18-35",
                "final_frame_description": "logo lockup over freeze frame",
                "audio_strategy": "external_track",
                "success_criteria": ["identity stable", "biomechanically credible"],
            }
            bres, err = await call("aurora_create_video_brief", brief_data={**brief, "project_id": pid})
            record("create_video_brief", not err, f"keys={list(bres)[:4]}")

            # --- Step 8: route verification ---------------------------------
            vr, err = await call(
                "aurora_verify_route", project_id=pid, feature_name="image_generation",
                route_data={"route_type": "mcp_callable", "verified": True,
                            "verification_source": "higgsfield_mcp_live", "confidence": 0.95},
            )
            record("STEP8 verify_route", not err and vr.get("ok"),
                   f"decision={vr.get('decision', {}).get('route_type')}")

            # --- Step 9: proposals (never spends credits) -------------------
            pi, err = await call(
                "aurora_propose_image_generation", project_id=pid,
                element_brief={"image_type": "genesis", "format": {"aspect_ratio": "16:9"},
                               "reference_strategy": {"element_ids": []}},
            )
            record("STEP9 propose_image", not err, f"ok={pi.get('ok')}")

            pv, err = await call(
                "aurora_propose_video_execution", project_id=pid,
                video_packet={"mode": "video_simple", "aspect_ratio": "16:9"},
            )
            record("STEP9 propose_video", not err, f"ok={pv.get('ok')}")

            # --- Step 10: elements + audit + quality score ------------------
            re_, err = await call("aurora_record_required_elements", project_id=pid,
                                  higgsfield_element_ids=["elem-sprinter-soul"])
            record("STEP10 record_required_elements", not err, f"count={re_.get('required_count')}")

            au, err = await call("aurora_record_audit", project_id=pid,
                                 criterion="identity_consistency", verdict="pass",
                                 notes="soul id stable across frames", audited_by="aurora")
            record("STEP10 record_audit", not err and au.get("ok"), f"audit_id={au.get('audit_id')}")

            qs, err = await call(
                "aurora_record_quality_score", project_id=pid, score_type="image",
                score_data={"identity": 92, "composition": 88, "lighting": 90,
                            "detail": 89, "prompt_adherence": 91},
            )
            record("STEP10 record_quality_score", not err and qs.get("ok"),
                   f"total={qs.get('result', {}).get('total_score')}")

            # --- Step 11: the three gates that the CHECK bug had broken -----
            bm, err = await call(
                "aurora_validate_biomechanics", project_id=pid,
                motion_plan={"action": "sprint start", "joints": ["ankle", "knee", "hip"],
                             "ground_contact": True, "limb_count": 4,
                             "physics_plausible": True},
            )
            record("STEP11 validate_biomechanics", not err, f"gate={bm.get('gate_id') or bm.get('name')}")

            pf, err = await call(
                "aurora_check_prompt_fitness", project_id=pid,
                prompt_packet={"creative": "explosive sprint start, stadium dawn light",
                               "technical": "85mm, shallow DOF, 120fps ramp",
                               "negative": "extra limbs, warped face", "model_id": "higgsfield_video"},
            )
            record("STEP11 check_prompt_fitness", not err, f"gate={pf.get('gate_id') or pf.get('name')}")

            ms, err = await call(
                "aurora_check_multishot_strategy", project_id=pid,
                shot_list=[{"shot_number": 1, "duration_seconds": 8,
                            "anchor_strategy": {"soul_id": "elem-sprinter-soul"}}],
            )
            record("STEP11 check_multishot_strategy", not err,
                   f"gate={ms.get('gate_id') or ms.get('name')}")

            # --- Step 12: PSP components + compute --------------------------
            comp, err = await call(
                "aurora_record_psp_components", project_id=pid,
                components={"identity_stability": 90, "biomechanical_credibility": 88,
                            "prompt_fitness": 90, "route_verification": 95,
                            "anchor_readiness": 92, "benchmark_alignment": 87,
                            "technical_feasibility": 91},
            )
            record("STEP12 record_psp_components", not err and comp.get("ok"), "")

            psp, err = await call("aurora_compute_production_success_probability", project_id=pid)
            psp_total = psp.get("result", {}).get("total_score")
            record("STEP12 compute_PSP", not err and psp.get("ok"),
                   f"PSP={psp_total} ok={psp.get('ok')}")

            # --- Step 13: emit Execution Pack -------------------------------
            ep, err = await call("aurora_emit_execution_pack", project_id=pid,
                                 elements_with_urls={"elem-sprinter-soul": "https://example/soul.png"})
            record("STEP13 emit_execution_pack", not err,
                   f"ok={ep.get('ok')} pack_id={ep.get('pack_id')} reason={ep.get('reason') or ep.get('blocking') or ''}")
            print("\n--- emit_execution_pack full payload ---")
            print(json.dumps(ep, indent=2, default=str)[:2000])

    # Summary
    print("\n================ E2E SUMMARY ================")
    passed = sum(1 for _, ok, _ in results if ok)
    for step, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {step}")
    print(f"\n{passed}/{len(results)} steps passed")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

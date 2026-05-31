"""End-to-end live test of the AURORA pipeline against the deployed Render server.

Drives a full video_simple project so EVERY required gate passes and the
Execution Pack emits green. Prints a per-step PASS/FAIL report and the final
gate evaluation. Run: python e2e_live.py
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

URL = "https://aurora-mcp-mjox.onrender.com/mcp"

results: list[tuple[str, bool, str]] = []

# Per-criterion 100s so each weighted scorer lands at 100 (>= 85 threshold).
IMAGE_SCORE = {k: 100 for k in (
    "photorealism", "advertising_look", "lighting_quality", "composition",
    "materials_textures", "anatomy_geometry", "brand_product_fidelity",
    "artifact_absence")}
PROMPT_PACKET = {k: 100 for k in (
    "model_correct", "model_syntax_correct", "single_dominant_action",
    "references_correct", "camera_clear", "physics_clear", "visual_style_clear",
    "negative_constraints_useful", "no_overload_or_contradiction")}
PROMPT_PACKET["contradictions"] = []
BIOMECH_SCORES = {k: 100 for k in (
    "valid_support_points", "center_of_mass_plausible", "joint_range_plausible",
    "object_trajectory_plausible", "contact_mechanics_plausible",
    "equipment_environment_constraints", "no_impossible_movement")}
PSP_COMPONENTS = {k: 100 for k in (
    "gate_compliance", "route_verification", "benchmark_match", "anchor_quality",
    "biomechanical_plausibility", "continuity_readiness", "prompt_fitness")}

PREPRO_PACKET = {
    "idea": "8s hero ad: a sprinter explodes off the blocks for Sports World",
    "script": {"beats": ["set", "explosion", "stride", "logo lockup"]},
    "shot_list": [{"shot_number": 1, "duration_seconds": 8, "shot_type": "hero",
                   "function": "explosive start"}],
    "characters": [{"name": "sprinter", "soul_id": "elem-sprinter-soul"}],
    "location": {"name": "stadium track at dawn"},
    "props_or_product": [{"name": "Sports World spikes"}],
    "visual_style": "high-contrast editorial sports cinema",
    "biomechanical_plan": [{"shot_number": 1, "action": "sprint start"}],
    "ff_lf_strategy": "simple_start",
    "recommended_model": "higgsfield_video_v1",
    "ui_or_mcp_route": "mcp",
    "success_criteria": ["identity stable", "biomechanically credible"],
}
MOTION_PLAN = {
    "action": "sprint start", "initial_pose": {"stance": "blocks crouch"},
    "legs": {"drive": "explosive triple extension"},
    "scores": BIOMECH_SCORES,
}


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        sc = res.structuredContent
        # FastMCP returns dict tool results directly as structuredContent; only
        # non-dict returns get wrapped under a sole "result" key. Don't unwrap a
        # tool's own "result" field (e.g. {"ok":True,"result":{...}}).
        if isinstance(sc, dict):
            if set(sc.keys()) == {"result"}:
                return sc["result"]
            return sc
        return sc
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

            async def call(name, **args):
                res = await s.call_tool(name, args)
                return _payload(res), bool(getattr(res, "isError", False))

            def record(step, ok, detail=""):
                results.append((step, ok, detail))
                print(f"[{'PASS' if ok else 'FAIL'}] {step}  {detail}")

            # --- Step 1: classify -------------------------------------------
            intent = "8 second hero ad for Sports World, a sprinter explodes off the blocks"
            cls, err = await call("aurora_classify_intent", text=intent)
            record("S1 classify_intent", not err and cls.get("mode") == "video_simple",
                   f"mode={cls.get('mode')} conf={cls.get('confidence')}")

            # --- Step 2: project --------------------------------------------
            proj, err = await call("aurora_create_project", operator_intent=intent,
                                   mode="video_simple", output_type="hero_ad")
            pid = proj.get("project_id")
            record("S2 create_project", not err and bool(pid), f"pid={pid}")
            if not pid:
                return 1

            # --- Step 3: domain session lock --------------------------------
            dl, err = await call("aurora_create_domain_session_lock", project_id=pid,
                                 lock_data={"domain": "sports", "sub_domain": "running",
                                            "project_scope": "video_simple"})
            record("S3 domain_session_lock", not err and dl.get("ok"), "")

            # --- Step 4: light capability refresh ---------------------------
            rf, err = await call("aurora_refresh_higgsfield_capabilities",
                                 scope="light_session", project_id=pid)
            record("S4 refresh_capabilities", not err,
                   f"snapshot={rf.get('snapshot_id', '')[:8]}")

            # --- Step 5: benchmark pack -------------------------------------
            bp, err = await call("aurora_create_benchmark_pack", project_id=pid,
                                 refs=[{"url_or_path": "https://ref/hero1.jpg",
                                        "visual_traits": {"contrast": "high"}}])
            record("S5 benchmark_pack", not err and bp.get("ok"),
                   f"ids={len(bp.get('benchmark_ids', []))}")

            # --- Step 6: video brief ----------------------------------------
            brief = {"operator_intent": intent, "output_type": "hero_ad",
                     "duration_seconds": 8, "emotional_beat": "triumph",
                     "product_or_brand": "Sports World",
                     "core_action": "sprinter explodes off the blocks",
                     "target_audience": "urban athletes 18-35",
                     "final_frame_description": "logo lockup over freeze frame",
                     "audio_strategy": "external_track",
                     "success_criteria": ["identity stable"]}
            br, err = await call("aurora_create_video_brief", brief_data=brief)
            record("S6 create_video_brief", not err and br.get("ok"), "")

            # --- Step 7: preproduction packet (the regla inviolable) --------
            pp, err = await call("aurora_validate_preproduction_packet",
                                 packet=PREPRO_PACKET, project_id=pid)
            record("S7 preproduction_packet", not err and pp.get("passed"),
                   f"missing={pp.get('missing')}")

            # --- Step 8: route verification ---------------------------------
            vr, err = await call("aurora_verify_route", project_id=pid,
                                 feature_name="image_generation",
                                 route_data={"route_type": "mcp_callable", "verified": True,
                                             "verification_source": "higgsfield_mcp_live",
                                             "confidence": 0.95})
            record("S8 verify_route", not err and vr.get("ok"),
                   f"type={vr.get('decision', {}).get('route_type')}")

            # --- Step 9: proposals (image + video w/ finishing) -------------
            pi, err = await call("aurora_propose_image_generation", project_id=pid,
                                 element_brief={"image_type": "genesis",
                                                "format": {"aspect_ratio": "16:9"}})
            record("S9 propose_image", not err, f"ok={pi.get('ok')}")
            pv, err = await call("aurora_propose_video_execution", project_id=pid,
                                 video_packet={"mode": "video_simple", "aspect_ratio": "16:9",
                                               "finishing": {"upscale_route": "ui_only",
                                                             "tools": []}})
            record("S9 propose_video(+finishing)", not err, f"ok={pv.get('ok')}")

            # --- Step 10: image quality score + audit (Gate 0) --------------
            qs, err = await call("aurora_record_quality_score", project_id=pid,
                                 score_type="image", score_data=IMAGE_SCORE)
            record("S10 record_quality_score", not err and qs.get("ok"),
                   f"total={qs.get('result', {}).get('total_score')}")
            au, err = await call("aurora_record_audit", project_id=pid,
                                 criterion="identity_consistency", verdict="pass",
                                 notes="soul id stable", audited_by="aurora")
            record("S10 record_audit", not err and au.get("ok"), "")

            # --- Step 11: the three previously-broken gates -----------------
            bm, err = await call("aurora_validate_biomechanics", project_id=pid,
                                 motion_plan=MOTION_PLAN)
            record("S11 validate_biomechanics", not err and bm.get("passed"),
                   f"score={bm.get('score')}")
            pf, err = await call("aurora_check_prompt_fitness", project_id=pid,
                                 prompt_packet=PROMPT_PACKET)
            record("S11 check_prompt_fitness", not err and pf.get("passed"),
                   f"score={pf.get('score')}")
            ms, err = await call("aurora_check_multishot_strategy", project_id=pid,
                                 shot_list=[{"shot_number": 1, "duration_seconds": 8}])
            record("S11 check_multishot_strategy", not err, f"passed={ms.get('passed')}")

            # --- Step 12: PSP -----------------------------------------------
            cmp_, err = await call("aurora_record_psp_components", project_id=pid,
                                   components=PSP_COMPONENTS)
            record("S12 record_psp_components", not err and cmp_.get("ok"), "")
            psp, err = await call("aurora_compute_production_success_probability",
                                  project_id=pid)
            record("S12 compute_PSP", not err and psp.get("ok"),
                   f"PSP={psp.get('result', {}).get('total_score')}")

            # --- Step 13: emit Execution Pack -------------------------------
            ep, err = await call("aurora_emit_execution_pack", project_id=pid)
            ok = not err and ep.get("ok")
            record("S13 emit_execution_pack", ok,
                   f"ok={ep.get('ok')} pack_id={ep.get('pack_id')}")
            ev = ep.get("gate_evaluation", {})
            print("\n--- gate evaluation ---")
            for g in ev.get("gates", []):
                print(f"   {g['status']:9} {g['name']}  {g.get('notes', '')}")
            if ep.get("reason"):
                print("   reason:", ep["reason"])
            md = ep.get("markdown")
            if md:
                print(f"\n--- Execution Pack markdown (first 600 chars) ---\n{md[:600]}")

    print("\n================ E2E SUMMARY ================")
    passed = sum(1 for _, ok, _ in results if ok)
    for step, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {step}")
    print(f"\n{passed}/{len(results)} steps passed")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

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

# A rich operator prompt packet (no rubric scores) — exercises the bug #7 path.
PROMPT_PACKET_RICH = {
    "model": "higgsfield_video_v1",
    "prompt_final": "A string quartet plays Vivaldi in a candlelit baroque hall.",
    "action": "the quartet plays in unison",
    "subject": ["@violinist_soul", "@cellist_soul"],
    "camera": {"body": "ARRI", "focal_mm": 50, "movement": "slow dolly",
               "aspect_ratio": "16:9"},
    "biomechanical_motion_plan_id": "mp-1",
    "look": "warm baroque chiaroscuro",
    "negative_constraints": ["no modern clothing", "no electric light", "no extra fingers"],
    "contradictions": [],
}

# A 3-shot multishot list satisfying BOTH the anchor and continuity gates.
MULTISHOT_SHOTS = [
    {"shot_number": 1, "duration_seconds": 5, "shot_type": "establishing",
     "anchor_strategy": {"case_type": "simple_start",
                         "ff_higgsfield_element_id": "elem-quartet-ff"},
     "continuity": {"continuity_ref_type": "none"}},
    {"shot_number": 2, "duration_seconds": 5, "shot_type": "closeup",
     "anchor_strategy": {"case_type": "continuity_from_previous",
                         "previous_clip_ref": "shot-1-clip",
                         "character_higgsfield_element_id": "elem-violinist"},
     "continuity": {"continuity_ref_type": "last_frame"}},
    {"shot_number": 3, "duration_seconds": 5, "shot_type": "wide",
     "anchor_strategy": {"case_type": "continuity_from_previous",
                         "previous_clip_ref": "shot-2-clip",
                         "location_higgsfield_element_id": "elem-hall"},
     "continuity": {"continuity_ref_type": "last_5s"}},
]
MULTISHOT_PACKET = {
    "idea": "A string quartet performs Vivaldi's Four Seasons in a baroque hall.",
    "script": {"beats": ["tuning", "allegro", "adagio", "finale"]},
    "shot_list": MULTISHOT_SHOTS,
    "characters": [{"name": "violinist", "soul_id": "elem-violinist"}],
    "location": {"name": "candlelit baroque concert hall"},
    "props_or_product": [{"name": "violin"}, {"name": "cello"}],
    "visual_style": "warm baroque chiaroscuro, anamorphic 50mm",
    "biomechanical_plan": [{"shot_number": 1, "action": "bowing"}],
    "ff_lf_strategy": "continuity_from_previous",
    "recommended_model": "higgsfield_video_v1",
    "ui_or_mcp_route": "mcp",
    "success_criteria": ["identity stable across shots", "bowing reads as real"],
}


def _sources() -> list[dict]:
    """3 fully-covered research sources (official_docs + mcp_introspection +
    community_forums) so aurora_record_platform_research accepts the dossier."""
    return [
        {"source_type": "official_docs", "url": "https://docs.higgsfield.ai/video",
         "verbatim_quote": "Use medias[].roles to inject start_image and video continuity."},
        {"source_type": "mcp_introspection", "url": "models_explore action=get",
         "verbatim_quote": "model accepts prompt, medias[], duration, aspect_ratio."},
        {"source_type": "community_forums", "url": "https://forum.example/threads/1",
         "verbatim_quote": "Tail-extract the last frame for seamless multishot continuity."},
    ]


def _dossier(model_id: str, output_type: str) -> dict:
    """A complete syntax_dossier (all 5 required fields)."""
    return {
        "model_id": model_id,
        "output_type": output_type,
        "prompt_template": "{action}. {subject}. {camera}. {look}. {negatives}",
        "continuity_injection": {
            "strategy": "medias[].roles=video", "field": "medias",
            "instructions": "Append previous clip as medias entry with roles=['video']."},
        "params_schema": {"prompt": "str", "medias": "list", "duration": "int",
                          "aspect_ratio": "str"},
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

            # --- Step 8b: research-driven prompt construction (v2.3) --------
            # The brief must offer the 3 mandatory source queries.
            rq, err = await call("aurora_request_platform_research", project_id=pid,
                                 model_id="higgsfield_video_v1", output_type="video_simple")
            brief_obj = rq.get("research_brief") or {}
            src_types = set((brief_obj.get("queries_per_source") or {}).keys())
            three = {"official_docs", "mcp_introspection", "community_forums"}
            record("S8b request_research(3 sources)",
                   not err and (rq.get("cached") or three.issubset(src_types)),
                   f"cached={rq.get('cached')} sources={sorted(src_types)}")
            rr, err = await call("aurora_record_platform_research", project_id=pid,
                                 model_id="higgsfield_video_v1", output_type="video_simple",
                                 syntax_dossier=_dossier("higgsfield_video_v1", "video_simple"),
                                 sources=_sources())
            record("S8b record_research", not err and rr.get("ok"),
                   f"confidence={rr.get('confidence')}")
            bpmt, err = await call("aurora_build_prompt", project_id=pid,
                                   model_id="higgsfield_video_v1", output_type="video_simple",
                                   shot_or_element_data={"action": "sprint start",
                                                         "subject": ["@sprinter_soul"],
                                                         "look": "editorial sports cinema"})
            record("S8b build_prompt", not err and bool(bpmt.get("prompt_final")),
                   f"prompt={(bpmt.get('prompt_final') or '')[:48]!r}")

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

            # === MULTISHOT case (Vivaldi quartet) — the path #4-#11 escaped ==
            print("\n========== MULTISHOT CASE (Vivaldi quartet) ==========")
            mintent = "Vivaldi Four Seasons performed by a string quartet, 3 shots"
            mproj, err = await call("aurora_create_project", operator_intent=mintent,
                                    mode="video_multishot", output_type="performance")
            mpid = mproj.get("project_id")
            record("M2 create_project(multishot)", not err and bool(mpid), f"pid={mpid}")
            if mpid:
                _, e1 = await call("aurora_create_domain_session_lock", project_id=mpid,
                                   lock_data={"domain": "music",
                                              "sub_domain": "classical_performance",
                                              "project_scope": "video_multishot"})
                record("M3 domain_session_lock", not e1, "")
                await call("aurora_refresh_higgsfield_capabilities",
                           scope="light_session", project_id=mpid)
                await call("aurora_create_benchmark_pack", project_id=mpid,
                           refs=[{"url_or_path": "https://ref/quartet.jpg",
                                  "visual_traits": {"warmth": "high"}}])
                await call("aurora_verify_route", project_id=mpid,
                           feature_name="video_generation",
                           route_data={"route_type": "mcp_callable", "verified": True,
                                       "verification_source": "higgsfield_mcp_live",
                                       "confidence": 0.95})
                mpp, e2 = await call("aurora_validate_preproduction_packet",
                                     packet=MULTISHOT_PACKET, project_id=mpid)
                record("M7 preproduction_packet", not e2 and mpp.get("passed"),
                       f"missing={mpp.get('missing')}")
                await call("aurora_record_quality_score", project_id=mpid,
                           score_type="image", score_data=IMAGE_SCORE)
                await call("aurora_record_audit", project_id=mpid,
                           criterion="identity_consistency", verdict="pass")
                await call("aurora_check_quality_ceiling", project_id=mpid)
                await call("aurora_validate_biomechanics", project_id=mpid,
                           motion_plan={"action": "bowing", "scores": BIOMECH_SCORES})
                # Rich operator packet (no rubric scores) — bug #7 path.
                mpf, e3 = await call("aurora_check_prompt_fitness", project_id=mpid,
                                     prompt_packet=PROMPT_PACKET_RICH)
                record("M11 check_prompt_fitness(rich)", not e3 and mpf.get("passed"),
                       f"score={mpf.get('score')}")
                mms, e4 = await call("aurora_check_multishot_strategy", project_id=mpid,
                                     shot_list=MULTISHOT_SHOTS)
                record("M11 check_multishot_strategy", not e4 and mms.get("passed"),
                       f"passed={mms.get('passed')}")
                await call("aurora_check_anchors_ready", project_id=mpid)
                # Gap #11: declare no finishing route required.
                msf, e5 = await call("aurora_skip_finishing", project_id=mpid,
                                     reason="raw higgsfield output is final")
                record("M11 skip_finishing", not e5 and msf.get("ok"), "")
                # v2.3: research the multishot model so gate_platform_syntax passes.
                mrr, e5b = await call(
                    "aurora_record_platform_research", project_id=mpid,
                    model_id="higgsfield_video_v1", output_type="video_multishot",
                    syntax_dossier=_dossier("higgsfield_video_v1", "video_multishot"),
                    sources=_sources())
                record("M11b record_research(multishot)", not e5b and mrr.get("ok"),
                       f"confidence={mrr.get('confidence')}")
                mbp, e5c = await call(
                    "aurora_build_prompt", project_id=mpid,
                    model_id="higgsfield_video_v1", output_type="video_multishot",
                    shot_or_element_data=MULTISHOT_SHOTS[1],
                    continuity_strategy={"case_type": "continuity_from_previous",
                                         "continuity_ref_type": "last_frame",
                                         "previous_clip_ref": "shot-1-clip"})
                record("M11b build_prompt(+continuity injection)",
                       not e5c and bool(mbp.get("injection_instructions")),
                       f"injection={bool(mbp.get('injection_instructions'))}")
                await call("aurora_record_psp_components", project_id=mpid,
                           components=PSP_COMPONENTS)
                await call("aurora_compute_production_success_probability",
                           project_id=mpid)
                mep, e6 = await call("aurora_emit_execution_pack", project_id=mpid)
                mev = mep.get("gate_evaluation", {})
                all_clear = bool(mev.get("all_clear"))
                mmd = mep.get("markdown") or ""
                has_md = bool(mmd)
                record("M13 emit_execution_pack(multishot)",
                       not e6 and mep.get("ok") and all_clear and has_md,
                       f"all_clear={all_clear} md={has_md}")
                print("\n--- multishot gate evaluation ---")
                for g in mev.get("gates", []):
                    print(f"   {g['status']:9} {g['name']}")
                if mep.get("reason"):
                    print("   reason:", mep["reason"])
                # The pack must be OPERATIVELY populated, not ceremonially green:
                # the validated packet's elements + per-shot instructions must be
                # in the rendered document.
                content_ok = ("violinist" in mmd and "### Shot 2" in mmd
                              and "### Shot 3" in mmd and "MCSLA breakdown" in mmd
                              and "elem-quartet-ff" in mmd)
                record("M13b pack content populated", content_ok,
                       f"elements+shots+MCSLA in markdown={content_ok}")

                # === BYPASS honored at emit (bug #9) — separate project ======
                bproj, _ = await call("aurora_create_project",
                                      operator_intent="bypass probe",
                                      mode="video_simple", output_type="hero_ad")
                bpid = bproj.get("project_id")
                blog, eb = await call("aurora_log_bypass",
                                      operator_text="OVERRIDE gate_prompt_fitness - operator accepts",
                                      component="gate_prompt_fitness",
                                      reason="operator accepts", scope="current_turn",
                                      project_id=bpid)
                bid = blog.get("bypass_id")
                bep, _ = await call("aurora_emit_execution_pack", project_id=bpid,
                                    bypass_ids=[bid] if bid else None)
                bbypassed = {g["name"] for g in
                             bep.get("gate_evaluation", {}).get("bypassed_gates", [])}
                record("M14 bypass_ids honored",
                       not eb and "gate_prompt_fitness" in bbypassed,
                       f"bypassed={sorted(bbypassed)}")

            # === PIPELINE A (Image Director) research flow ==================
            print("\n========== PIPELINE A CASE (image research) ==========")
            iproj, _ = await call("aurora_create_project",
                                  operator_intent="genesis hero still of a sprinter",
                                  mode="image_simple", output_type="hero_image")
            ipid = iproj.get("project_id")
            record("A2 create_project(image)", bool(ipid), f"pid={ipid}")
            if ipid:
                irq, ea = await call("aurora_request_platform_research", project_id=ipid,
                                     model_id="nano_banana_pro", output_type="image_genesis")
                ibrief = irq.get("research_brief") or {}
                # official_docs queries must be image-scoped (contain "genesis").
                odq = " ".join(
                    (ibrief.get("queries_per_source") or {}).get("official_docs", [])
                ).lower()
                record("A8b request_research(image_genesis)",
                       not ea and (irq.get("cached") or "genesis" in odq),
                       f"cached={irq.get('cached')}")
                irr, eb2 = await call(
                    "aurora_record_platform_research", project_id=ipid,
                    model_id="nano_banana_pro", output_type="image_genesis",
                    syntax_dossier=_dossier("nano_banana_pro", "image_genesis"),
                    sources=_sources())
                record("A8b record_research(image)", not eb2 and irr.get("ok"),
                       f"confidence={irr.get('confidence')}")
                ibp, ec = await call(
                    "aurora_build_prompt", project_id=ipid, model_id="nano_banana_pro",
                    output_type="image_genesis",
                    shot_or_element_data={"action": "sprinter mid-stride",
                                          "look": "editorial sports cinema"})
                # Image build has NO continuity injection.
                no_cont = not ibp.get("injection_instructions")
                record("A8b build_prompt(image, no continuity)",
                       not ec and bool(ibp.get("prompt_final")) and no_cont,
                       f"no_continuity={no_cont}")

    print("\n================ E2E SUMMARY ================")
    passed = sum(1 for _, ok, _ in results if ok)
    for step, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {step}")
    print(f"\n{passed}/{len(results)} steps passed")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Deterministic prompt linter (ported from the aurora-prompt-linter skill).

Three validation layers for an AI visual-generation prompt:
  1. refs redundancy — a prompt must NOT re-describe what the reference images
     already carry, categorised P (subject) / O (outfit) / L (location) /
     PR (prop) / S (style). Static descriptors of a covered category are flagged.
  2. required sections by platform+case — each (platform, case) demands certain
     keyword-detectable sections in the MAIN prompt (e.g. Kling 3.0 case 3a needs
     a camera section); a missing one is a violation.
  3. structure — word-count cap per case, mandatory negative-prompt block,
     cross-platform banned vocabulary, and sports-broadcast keywords when active.

Moves the rule "don't re-describe what's in the refs" from agent memory to code.
This is a pure function: no file IO except loading the bundled vocabulary once.
"""
from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any, Optional

import yaml

EVALUATOR_VERSION = "prompt_lint/1.1"

CASE_CONFIGS: dict[str, dict[str, Any]] = {
    "1":  {"name": "Genesis (text-to-image)",  "budget": (75, 130), "requires_negative": True},
    "2":  {"name": "Anchor (image with refs)", "budget": (75, 130), "requires_negative": True},
    "3a": {"name": "I2V FF only",              "budget": (50, 90),  "requires_negative": True},
    "3b": {"name": "I2V FF + LF",              "budget": (50, 90),  "requires_negative": True},
    "3c": {"name": "I2V motion control",       "budget": (50, 90),  "requires_negative": True},
    "4":  {"name": "Video with dialogue",      "budget": (75, 130), "requires_negative": True},
}

VALID_CASES = tuple(CASE_CONFIGS.keys())

DIRECTIONAL_PREPOSITIONS = [
    "away from", "toward", "towards", "off", "over", "behind",
    "in front of", "across", "past", "from her", "from his",
    "onto", "into", "above", "below", "beside",
]

OVERRIDE_PATTERN = re.compile(
    r"OVERRIDE\s*:\s*(?P<term>[^\-\n]+?)\s*[\-]+\s*(?P<reason>[^\n]+)",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def load_vocab() -> dict[str, Any]:
    """Load the bundled vocabulary YAML (cached). Editable by research updates."""
    with resources.files("aurora.data").joinpath("prompt_lint_vocab.yaml").open(
        "r", encoding="utf-8"
    ) as fh:
        return yaml.safe_load(fh) or {}


def normalize_tag(tag: str) -> str:
    m = re.match(r"^([A-Z]+)\d*$", tag.strip())
    return m.group(1) if m else tag


def covered_categories(refs: list[dict[str, Any]]) -> set[str]:
    cats: set[str] = set()
    for ref in refs or []:
        for tag in ref.get("tags", []) or []:
            cats.add(normalize_tag(str(tag)))
    return cats


def split_main_and_negative(prompt: str) -> tuple[str, str]:
    parts = re.split(r"(?i)\bnegative\s*:", prompt, maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _word_count(text: str) -> int:
    return len(text.split())


def find_term_in_text(term: str, text: str) -> list[tuple[int, int]]:
    text_lower, term_lower = text.lower(), term.lower()
    spans: list[tuple[int, int]] = []
    if " " in term_lower:
        start = 0
        while True:
            idx = text_lower.find(term_lower, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(term_lower)))
            start = idx + 1
    else:
        for m in re.finditer(r"\b" + re.escape(term_lower) + r"\b", text_lower):
            spans.append((m.start(), m.end()))
    return spans


def is_in_motion_context(text: str, span: tuple[int, int], motion_prefixes: list[str]) -> bool:
    start = max(0, span[0] - 60)
    window_full = text[start:span[1]].lower()
    window_before = text[start:span[0]].lower()
    for prefix in motion_prefixes:
        pat = r"\b" + re.escape(prefix.lower()) + r"\b[^.]{0,50}$"
        if re.search(pat, window_full):
            return True
    for prep in DIRECTIONAL_PREPOSITIONS:
        pat = r"\b" + re.escape(prep) + r"\s+(?:her\s+|his\s+|the\s+)?$"
        if re.search(pat, window_before):
            return True
    return False


def parse_overrides(user_message: str) -> list[dict[str, str]]:
    overrides: list[dict[str, str]] = []
    for m in OVERRIDE_PATTERN.finditer(user_message or ""):
        term = m.group("term").strip().strip('"\'')
        reason = m.group("reason").strip()
        is_cat = bool(re.match(r"^[A-Z]{1,2}\d*$", term))
        overrides.append({
            "term": term,
            "category": normalize_tag(term) if is_cat else "",
            "reason": reason,
            "source_text": m.group(0),
        })
    return overrides


def _override_matches(v: dict[str, str], overrides: list[dict[str, str]]) -> Optional[dict[str, str]]:
    for ovr in overrides:
        if ovr["term"].lower() == v["term"].lower():
            return ovr
        if ovr["category"] and ovr["category"] == v["category"]:
            return ovr
    return None


def normalize_platform_case_key(platform: str, case_type: str) -> str:
    p = platform.strip().lower().replace("-", "_").replace(" ", "_").replace(".", "_")
    p = re.sub(r"_(\d+)_(\d+)", r"_\1.\2", p)
    return f"{p}__{case_type}"


def _validate_sections(prompt_main: str, platform: str, case_type: str,
                       vocab: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    sections_db = vocab.get("REQUIRED_SECTIONS_BY_PLATFORM_CASE", {}) or {}
    key = normalize_platform_case_key(platform, case_type)
    section_specs = sections_db.get(key)
    if section_specs is None:
        return [], [], []
    required, present, missing = list(section_specs.keys()), [], []
    main_lower = prompt_main.lower()
    for section_name, patterns in section_specs.items():
        if any(str(pat).lower() in main_lower for pat in patterns):
            present.append(section_name)
        else:
            missing.append(section_name)
    return required, present, missing


def lint(
    prompt: str,
    case: str,
    platform: str = "",
    refs: Optional[list[dict[str, Any]]] = None,
    overrides_text: str = "",
    sports_broadcast: bool = False,
    vocab: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run the 3-layer deterministic lint. Returns a dict with status PASS/FAIL,
    violations, warnings, suggestions, and a human-readable report."""
    vocab = vocab if vocab is not None else load_vocab()
    refs = refs or []
    config = CASE_CONFIGS.get(case)
    if not config:
        return {
            "status": "FAIL", "case_type": case, "platform": platform,
            "word_count": 0, "word_budget": [0, 0], "covered_categories": [],
            "sections_required": [], "sections_present": [], "sections_missing": [],
            "violations": [], "overrides_accepted": [], "warnings": [],
            "suggestions": [], "report": f"ERROR: Unknown case_type {case}",
        }

    overrides = parse_overrides(overrides_text)
    main, negative = split_main_and_negative(prompt or "")
    cats = covered_categories(refs)
    motion_prefixes = vocab.get("ALLOWED_MOTION_PREFIXES", []) or []

    violations: list[dict[str, str]] = []
    overrides_accepted: list[dict[str, str]] = []
    overrides_used: set[str] = set()
    warnings: list[str] = []

    def _consume(v: dict[str, str]) -> None:
        ovr = _override_matches(v, overrides)
        if ovr:
            if ovr["source_text"] not in overrides_used:
                overrides_accepted.append(ovr)
                overrides_used.add(ovr["source_text"])
        else:
            violations.append(v)

    # Layer 1: refs redundancy
    for cat in sorted(cats):
        for term in vocab.get(cat, []) or []:
            for span in find_term_in_text(term, main):
                if is_in_motion_context(main, span, motion_prefixes):
                    continue
                _consume({"term": term, "category": cat,
                          "reason": f"Static descriptor of category {cat} (covered by refs)"})
                break

    # Layer 2: required sections by platform+case
    sec_req, sec_pres, sec_miss = _validate_sections(main, platform, case, vocab)
    if not sec_req and platform:
        warnings.append(
            f"No required-sections snapshot for platform '{platform}' + case '{case}'. "
            f"Update prompt_lint_vocab.yaml REQUIRED_SECTIONS_BY_PLATFORM_CASE."
            f"{normalize_platform_case_key(platform, case)}")
    for ms in sec_miss:
        _consume({"term": ms, "category": "SECTION",
                  "reason": f"Required section '{ms}' for platform '{platform}' case {case} not detected in MAIN"})

    # Layer 3a: banned vocab in MAIN
    for term in vocab.get("BANNED", []) or []:
        if find_term_in_text(term, main):
            _consume({"term": term, "category": "BANNED",
                      "reason": "Cross-platform banned vocab in main prompt"})

    # Layer 3b: word count
    wc_main = _word_count(main)
    if wc_main > config["budget"][1]:
        violations.append({"term": f"word_count={wc_main}", "category": "STRUCTURE",
                           "reason": f"Above HARD MAX {config['budget'][1]} (Regla 10 v6.1)"})
    elif wc_main < config["budget"][0]:
        warnings.append(
            f"Word count {wc_main} below soft min {config['budget'][0]} (compression OK if intentional)")

    # Layer 3c: negative prompt
    if config["requires_negative"] and not negative.strip():
        violations.append({"term": "negative_prompt", "category": "STRUCTURE",
                           "reason": "Negative prompt block required"})

    # Layer 3d: sports broadcast
    if sports_broadcast:
        for kw in vocab.get("REQUIRED_SPORTS_BROADCAST", []) or []:
            if kw.lower() not in main.lower():
                violations.append({"term": kw, "category": "REQUIRED",
                                   "reason": "Required keyword for sports broadcast (Regla 26 v6.1)"})

    status = "PASS" if not violations else "FAIL"
    suggestions = _build_suggestions(violations, platform, case)
    report = _build_report(
        case, config, platform, wc_main, negative, cats, sports_broadcast,
        sec_req, sec_pres, violations, warnings, overrides_accepted, suggestions, status,
    )

    return {
        "status": status, "case_type": case, "platform": platform,
        "word_count": wc_main, "word_budget": list(config["budget"]),
        "covered_categories": sorted(cats),
        "sections_required": sec_req, "sections_present": sec_pres,
        "sections_missing": sec_miss, "violations": violations,
        "overrides_accepted": overrides_accepted, "warnings": warnings,
        "suggestions": suggestions, "report": report,
    }


def _build_suggestions(violations: list[dict[str, str]], platform: str, case: str) -> list[str]:
    if not violations:
        return []
    cat_vio: dict[str, list[str]] = {}
    for v in violations:
        cat_vio.setdefault(v["category"], []).append(v["term"])
    suggestions: list[str] = []
    for cat, terms in cat_vio.items():
        if cat in ("P", "O", "L", "PR", "S"):
            suggestions.append(f"Strip from MAIN: {terms} (category {cat} already covered by refs)")
        elif cat == "SECTION":
            suggestions.append(f"Add sections to MAIN: {terms} (required by platform '{platform}' case {case})")
        elif cat == "BANNED":
            suggestions.append(f"Move to NEGATIVE block: {terms}")
        elif cat == "STRUCTURE":
            suggestions.append(f"Fix structure: {terms}")
        elif cat == "REQUIRED":
            suggestions.append(f"Add to MAIN: {terms}")
    return suggestions


def _build_report(case, config, platform, wc_main, negative, cats, sports_broadcast,
                  sec_req, sec_pres, violations, warnings, overrides_accepted,
                  suggestions, status) -> str:
    L = [
        "=" * 64,
        "AURORA PROMPT LINTER REPORT v1.1",
        "=" * 64,
        f"Case: {case} ({config['name']})",
        f"Platform: {platform if platform else '(none specified)'}",
        f"Word count (MAIN): {wc_main} / budget {config['budget']}",
        f"Negative prompt: {'present' if negative.strip() else 'MISSING'}",
        f"Categories covered by refs: {sorted(cats) if cats else '(none)'}",
        f"Sports broadcast mode: {'on' if sports_broadcast else 'off'}",
        "",
    ]
    if sec_req:
        L.append(f"REQUIRED SECTIONS for {platform} case {case}:")
        for s in sec_req:
            L.append(f"  {'PRESENT' if s in sec_pres else 'MISSING'} {s}")
        L.append("")
    if violations:
        L.append(f"VIOLATIONS ({len(violations)}):")
        for v in violations:
            L.append(f"  FAIL [{v['category']}] '{v['term']}' - {v['reason']}")
    else:
        L.append("VIOLATIONS: none")
    if warnings:
        L.append("")
        L.append(f"WARNINGS ({len(warnings)}) non-blocking:")
        for w in warnings:
            L.append(f"  WARN {w}")
    if overrides_accepted:
        L.append("")
        L.append(f"OVERRIDES ACCEPTED ({len(overrides_accepted)}):")
        for o in overrides_accepted:
            L.append(f"  OK '{o['term']}' - {o['reason'][:100]}")
    if suggestions:
        L.append("")
        L.append("SUGGESTIONS:")
        for s in suggestions:
            L.append(f"  -> {s}")
    L.append("")
    L.append(f"STATUS: {status}")
    L.append("Delivery BLOCKED. Iterate or grant OVERRIDE in current turn."
             if status == "FAIL" else "Delivery PERMITTED.")
    L.append("=" * 64)
    return "\n".join(L)

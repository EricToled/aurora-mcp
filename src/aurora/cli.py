"""AURORA command-line interface (Sprint 1).

Lets the aurora skill drive AURORA through the terminal in environments where a
local MCP server cannot be registered (e.g. the Cowork / Claude Code desktop
build). Every subcommand prints a JSON result to stdout.

Usage:
    python -m aurora.cli classify --text "8s hero ad for Sports World"
    python -m aurora.cli parse-bypass --text "OVERRIDE: gate_step_0 - reason"
    python -m aurora.cli validate-packet --json-file packet.json
    python -m aurora.cli create-brief --json-file brief.json
    python -m aurora.cli log-bypass --component gate_step_0 --reason "rapid proto"

JSON inputs may be passed via --json-file PATH, --json '<inline>', or piped on
stdin (use "-" or omit the input flag).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import bypass_handler, db, theme_resolver
from .gates import gate_preproduction_packet
from .models import VideoBrief

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "aurora.db"


def _emit(obj: Any) -> None:
    # Force UTF-8 so non-ASCII (em-dashes, accents) render on any console codepage.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _load_json(args: argparse.Namespace) -> Any:
    if getattr(args, "json_file", None):
        return json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    if getattr(args, "json", None):
        return json.loads(args.json)
    data = sys.stdin.read()
    if not data.strip():
        raise SystemExit("error: no JSON provided (use --json-file, --json, or stdin)")
    return json.loads(data)


def _ensure_db() -> None:
    if not DB_PATH.exists():
        db.init_db(DB_PATH)


def cmd_classify(args: argparse.Namespace) -> int:
    _emit(theme_resolver.classify_intent(args.text))
    return 0


def cmd_parse_bypass(args: argparse.Namespace) -> int:
    directive = bypass_handler.parse_bypass(args.text)
    _emit(directive.model_dump() if directive else None)
    return 0


def cmd_validate_packet(args: argparse.Namespace) -> int:
    packet = _load_json(args)
    result = gate_preproduction_packet.validate_packet(packet)
    _emit(result.model_dump())
    # Non-zero exit when the gate fails, so the caller can branch on it.
    return 0 if result.passed else 2


def cmd_create_brief(args: argparse.Namespace) -> int:
    _ensure_db()
    brief_data = _load_json(args)
    try:
        brief = VideoBrief(**brief_data)
    except Exception as exc:  # pydantic ValidationError or bad input
        _emit({"ok": False, "errors": str(exc)})
        return 2
    brief_id = db.insert_brief(brief.model_dump(mode="json"), db_path=str(DB_PATH))
    _emit({"ok": True, "brief_id": brief_id})
    return 0


def cmd_log_bypass(args: argparse.Namespace) -> int:
    _ensure_db()
    if args.component not in bypass_handler.BYPASSABLE_COMPONENTS:
        _emit({"ok": False, "reason": f"unknown component: {args.component}"})
        return 2
    if not args.reason or not args.reason.strip():
        _emit({"ok": False, "reason": "empty reason rejected"})
        return 2
    directive = bypass_handler.BypassDirective(
        component=args.component,
        reason=args.reason,
        scope=args.scope,
        detected_in_text=args.text or f"{args.component} - {args.reason}",
    )
    bypass_id = bypass_handler.log_bypass(directive, db_path=str(DB_PATH))
    _emit({"ok": True, "bypass_id": bypass_id})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aurora", description="AURORA Sprint 1 CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("classify", help="classify operator intent")
    sp.add_argument("--text", required=True)
    sp.set_defaults(func=cmd_classify)

    sp = sub.add_parser("parse-bypass", help="detect/parse an operator bypass")
    sp.add_argument("--text", required=True)
    sp.set_defaults(func=cmd_parse_bypass)

    sp = sub.add_parser("validate-packet", help="run the preproduction gate")
    sp.add_argument("--json-file")
    sp.add_argument("--json")
    sp.set_defaults(func=cmd_validate_packet)

    sp = sub.add_parser("create-brief", help="validate + persist a video brief")
    sp.add_argument("--json-file")
    sp.add_argument("--json")
    sp.set_defaults(func=cmd_create_brief)

    sp = sub.add_parser("log-bypass", help="register a bypass in bypass_log")
    sp.add_argument("--component", required=True)
    sp.add_argument("--reason", required=True)
    sp.add_argument(
        "--scope",
        default="current_turn",
        choices=["current_turn", "persist", "all_session"],
    )
    sp.add_argument("--text", default="")
    sp.set_defaults(func=cmd_log_bypass)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

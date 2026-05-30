"""STUB — Sprint 4 implementation.

Full version is an empirically-validated routing matrix deciding, per platform
feature, whether to drive it via MCP or via UI instructions. Sprint 1 just loads
a YAML capability file and returns the raw dict with no routing logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def route(capability_yaml_path: str | Path) -> dict[str, Any]:
    """STUB: load YAML and return raw dict. TODO: Sprint 4 — real routing matrix."""
    path = Path(capability_yaml_path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"raw": data}

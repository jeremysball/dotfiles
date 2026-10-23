#!/usr/bin/env python3
"""check-mcp-parity.py: kilo and opencode declare the same MCP servers.

The belief this check names:

    Every MCP server is defined twice, once in .config/kilo/kilo.jsonc and
    once in .config/opencode/opencode.jsonc. Nothing keeps the two blocks
    equal, and drift is silent: a version pin bumped in one harness leaves
    the other launching the old package, and a flag added on one side is
    invisible on the other.

Exit codes:
  0  both blocks exist and are equal
  1  drift (missing server, different pin/flag/url/enabled state)
  2  a file could not be read or its mcp block could not be parsed

Usage:
  scripts/check-mcp-parity.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = (
    ".config/kilo/kilo.jsonc",
    ".config/opencode/opencode.jsonc",
)


def load_brace_scanner():
    """Reuse the JSONC-aware brace matcher from the fleet cap check."""
    path = ROOT / "scripts" / "check-fleet-context-cap.py"
    spec = importlib.util.spec_from_file_location("fleet_context_cap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._scan_forward


def mcp_block(text: str, label: str, scan) -> dict:
    match = re.search(r'"mcp"\s*:\s*\{', text)
    if not match:
        raise ValueError(f'{label}: no "mcp" object')
    start = text.index("{", match.start())
    end = scan(text, start)
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}: mcp block is not plain JSON: {exc}") from exc


def main() -> int:
    scan = load_brace_scanner()
    blocks = {}
    try:
        for rel in CONFIGS:
            blocks[rel] = mcp_block((ROOT / rel).read_text(), rel, scan)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    first_rel, first = next(iter(blocks.items()))
    for rel, block in list(blocks.items())[1:]:
        if block == first:
            continue
        print(f"DRIFT: mcp blocks differ: {first_rel} vs {rel}", file=sys.stderr)
        for name in sorted(set(first) | set(block)):
            if first.get(name) != block.get(name):
                print(f"  {name}:", file=sys.stderr)
                print(
                    f"    {first_rel}: {json.dumps(first.get(name), sort_keys=True)}",
                    file=sys.stderr,
                )
                print(
                    f"    {rel}: {json.dumps(block.get(name), sort_keys=True)}",
                    file=sys.stderr,
                )
        return 1

    print(f"OK: mcp parity across {len(blocks)} configs ({', '.join(sorted(first))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

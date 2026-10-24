#!/usr/bin/env python3
"""check-fleet-context-cap.py: every dispatch route is capped at 200k, with
declared exceptions from ROUTE_CAP_OVERRIDES.

The belief this check names:

    A configured route with no limit.context inherits its provider's native
    window, up to 1,050,000 tokens. A session on one of those routes therefore
    sails past the fleet's 200k budget and never triggers compaction, which is
    how the 2026-10-18 burn reached 661,706 tokens per step with zero
    compaction events.

A configured limit is what makes the harness compact. The harness merges the
provider catalog over the config at runtime, so every route a provider serves
is dispatchable whether or not the config names it. Every one of them needs a
declared limit, and none may exceed the cap except a route listed in
ROUTE_CAP_OVERRIDES.

The gateway catalog is the canonical source for which routes exist and for
their native windows. The config files are where the cap is applied.

Exit codes:
  0  every checked route is capped
  1  a route is not capped (drift)
  2  a fact could not be determined (the catalog is unreachable and no cache
     was usable), or --apply refused to lower a declared override

Usage:
  scripts/check-fleet-context-cap.py             # verify, exit 1 on drift
  scripts/check-fleet-context-cap.py --apply     # rewrite the fleet configs to the cap
  scripts/check-fleet-context-cap.py --offline   # check the configured routes only
  scripts/check-fleet-context-cap.py --verbose   # print every route it checked
  scripts/check-fleet-context-cap.py --catalog PATH   # read the catalog from this file
  scripts/check-fleet-context-cap.py --apply --cap N --allow-override-lowering
                                                 # rewrite a declared override downward
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

FLEET_CAP = 200_000
DEFAULT_OUTPUT = 32_000
CATALOG_URL = "https://api.llmgateway.io/v1/models"

# The trigger the 2026-10-24 directive preserves for every declared override.
# A declared override is exact: parity and native windows cannot lower it, and
# each active compaction block must put its trigger here. See
# docs/things-that-look-like-bugs.md for the rationale.
OVERRIDE_TRIGGER = 175_000

# Route-specific caps above the fleet default. The check enforces each value in
# every fleet config, so the table and the configs cannot diverge silently.
ROUTE_CAP_OVERRIDES = {
    ("llmgateway", "deepseek-v4.1-flash-1017"): 220_000,
}


def route_cap(
    provider_id: str,
    model_id: str,
    fleet_cap: int,
    *,
    use_overrides: bool,
) -> int:
    """Return the cap for one route.

    A declared override applies unless use_overrides is false. An explicit
    --cap sets use_overrides false for validation; --apply refuses to lower a
    declared override without --allow-override-lowering.
    """
    if not use_overrides:
        return fleet_cap
    return ROUTE_CAP_OVERRIDES.get((provider_id, model_id), fleet_cap)


def route_target(
    provider_id: str,
    model_id: str,
    fleet_cap: int,
    parity_cap: dict[tuple[str, str], int] | None,
    *,
    use_overrides: bool,
    native: int | None = None,
) -> int:
    """Resolve the target cap for one route.

    A declared override is exact, so neither a sibling's lower value nor the
    native window may drag it down. Other routes take the lower of the fleet
    cap, the sibling parity floor, and the native window.
    """
    key = (provider_id, model_id)
    cap = route_cap(provider_id, model_id, fleet_cap, use_overrides=use_overrides)
    if use_overrides and key in ROUTE_CAP_OVERRIDES:
        return cap
    if parity_cap is not None:
        cap = min(cap, parity_cap.get(key, cap))
    if native is not None:
        cap = min(cap, native)
    return cap


# Every fleet config that can carry a dispatch route, with the providers it is
# expected to declare. The opencode catalog file holds the display-name
# llmgateway catalog; the two .jsonc files hold the routes the fleet actually
# dispatches on top of it.
FLEET_CONFIGS = [
    (".config/opencode/opencode.json", ("llmgateway",)),
    (".config/opencode/opencode.jsonc", ("llmgateway", "openai")),
    (".config/kilo/kilo.jsonc", ("llmgateway", "openai")),
]

# The providers the ferry fleet dispatches on. Every route either provider
# declares must carry a limit at or below the cap, and the named routes must
# exist at all.
DISPATCH_PROVIDERS = ("llmgateway", "openai")

# Routes that must exist with a cap. gpt-6-luna had no override at all, so it
# ran at whatever window the provider's catalog reports.
REQUIRED_ROUTES = {
    "openai": ("gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-sol-fast"),
}

# Providers that are not dispatch routes keep their own windows. Their
# over-cap routes are reported, never clamped: the decision-model paths that
# use them chose those windows on purpose. One exception is parity: when a
# sibling config already caps the same route at the fleet cap, this config is
# clamped to match, because two copies of one route disagreeing about its
# window is how the uncapped route got missed in the first place.

# Keys that mark a block as a provider block rather than an agent block.
_PROVIDER_MARKERS = ('"models"', '"npm"', '"options"', '"baseURL"')


class CatalogUnavailable(Exception):
    """The catalog could not be read and no usable cache existed."""


def cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "llmgateway", "models.json")


# --------------------------------------------------------------------------
# brace matching that ignores strings and comments
# --------------------------------------------------------------------------

def _scan_forward(text: str, start: int) -> int:
    """Return the index of the '}' matching the '{' at start.

    Skips string literals, line comments, and block comments.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated block comment")
            i = end + 2
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced braces")


def _last_code_index(text: str) -> int:
    """Index of the last character that is code, not a comment or a string."""
    i = 0
    n = len(text)
    last = -1
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        last = i
        i += 1
    return last


def _split_trailing_comment(text: str) -> tuple[str, str]:
    """Split text into (code, trailing comment).

    A splice that appends a comma must put it before a trailing comment, not
    after: a comma behind a comment is swallowed by the comment and the file
    stops parsing. Both comment styles count, because a JSONC file may carry
    either, and a "//" inside a string literal is not a comment at all.
    """
    last = _last_code_index(text)
    if last < 0:
        return text, ""
    code = text[: last + 1].rstrip()
    rest = text[last + 1 :]
    stripped = rest.lstrip()
    if stripped.startswith("//"):
        idx = rest.index("//")
        return code, rest[idx:]
    if stripped.startswith("/*"):
        idx = rest.index("/*")
        end = rest.find("*/", idx)
        if end >= 0:
            return code, rest[idx : end + 2]
    return code, rest


def provider_models_span(text: str, provider_id: str) -> tuple[int, int] | None:
    """Return (start, end) of the provider's "models" object, or None."""
    pid = re.search(rf'"{re.escape(provider_id)}"\s*:\s*\{{', text)
    if not pid:
        return None
    provider_open = text.index("{", pid.start())
    provider_close = _scan_forward(text, provider_open)
    provider_text = text[provider_open : provider_close + 1]
    models = re.search(r'"models"\s*:\s*\{', provider_text)
    if not models:
        return None
    models_open = provider_open + models.end() - 1
    return models_open, _scan_forward(text, models_open)


def model_entries(text: str, span: tuple[int, int]) -> list[tuple[str, int, int]]:
    """Return [(model_id, entry_open_brace, entry_close_brace)] inside the models block."""
    start, end = span
    entry_re = re.compile(r'"([A-Za-z0-9._\-:/]+)"\s*:\s*\{')
    out: list[tuple[str, int, int]] = []
    i = start
    while True:
        m = entry_re.search(text, i, end)
        if not m:
            return out
        if m.group(1) in ("limit", "models", "options", "settings"):
            i = m.end()
            continue
        open_brace = text.index("{", m.start())
        close = _scan_forward(text, open_brace)
        if close > end:
            return out
        out.append((text[m.start(1) : m.end(1)], open_brace, close))
        i = close + 1


def provider_blocks(text: str):
    """Yield (provider_id, block_text) for each provider block in a config."""
    for m in re.finditer(r'^\s+"([a-z0-9\-]+)": \{', text, re.M):
        pid = m.group(1)
        open_brace = text.index("{", m.start())
        try:
            close = _scan_forward(text, open_brace)
        except ValueError:
            continue
        block = text[open_brace : close + 1]
        if not any(marker in block for marker in _PROVIDER_MARKERS):
            continue  # an agent or hook block, not a provider
        yield pid, block


# --------------------------------------------------------------------------
# limit rewriting
# --------------------------------------------------------------------------

def _indent_of_line(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos]


def _insert_limit(entry: str, context: int, output: int, input_limit: int | None = None) -> str:
    """Return the entry with a limit added, preserving its layout."""
    inner = entry[1:-1]
    parts = [f'"context": {context}']
    if input_limit is not None:
        parts.insert(1, f'"input": {input_limit}')
    parts.append(f'"output": {output}')
    limit = '"limit": { ' + ", ".join(parts) + " }"
    if "\n" in inner:
        body = inner.rstrip()
        trailing = inner[len(body) :]
        if not body.strip():
            return "{ " + limit + " }"
        last_prop = body.split("\n")[-1]
        indent = _indent_of_line(last_prop, len(last_prop) - len(last_prop.lstrip()))
        sep = "" if body.endswith(",") else ","
        return "{" + body + sep + "\n" + indent + limit + trailing + "}"
    stripped = inner.strip()
    if not stripped:
        return "{ " + limit + " }"
    sep = "" if stripped.endswith(",") else ", "
    return "{ " + stripped + sep + limit + " }"


def _clamp_context(entry: str, cap: int, native: int | None) -> tuple[str, bool]:
    """Clamp an existing limit.context to the cap. Returns (entry, changed).

    The input field is clamped too: kilo's config sets it explicitly because
    compaction uses it when it is present, so leaving it at the old value
    would keep the route over the budget in the path that matters most.
    """
    m = re.search(r'"context"\s*:\s*(\d+)', entry)
    if not m:
        return entry, False
    current = int(m.group(1))
    target = min(cap, native) if native else cap
    if current <= target:
        return entry, False
    new_entry = entry[: m.start(1)] + str(target) + entry[m.end(1) :]
    mi = re.search(r'"input"\s*:\s*(\d+)', new_entry)
    if mi and int(mi.group(1)) > target:
        new_entry = new_entry[: mi.start(1)] + str(target) + new_entry[mi.end(1) :]
    return new_entry, True


def _set_context(entry: str, target: int) -> tuple[str, bool]:
    """Set an existing limit.context to target, raising or lowering it.

    A declared override must be restored, not just clamped, so --apply can
    repair a lagging sibling instead of lowering the rest of the fleet.
    """
    m = re.search(r'"context"\s*:\s*(\d+)', entry)
    if not m:
        return entry, False
    current = int(m.group(1))
    if current == target:
        return entry, False
    new_entry = entry[: m.start(1)] + str(target) + entry[m.end(1) :]
    mi = re.search(r'"input"\s*:\s*(\d+)', new_entry)
    if mi and int(mi.group(1)) > target:
        new_entry = new_entry[: mi.start(1)] + str(target) + new_entry[mi.end(1) :]
    return new_entry, True


def _entry_style(entry: str) -> str:
    """Return 'inline' or 'block' for the layout of a models entry."""
    return "inline" if "\n" not in entry else "block"


def _render_entry(model_id: str, display_name: str, context: int, output: int, style: str, indent: str) -> str:
    if style == "inline":
        return (
            f'{indent}"{model_id}": {{ "name": "{display_name}", '
            f'"limit": {{ "context": {context}, "output": {output} }} }}'
        )
    return (
        f'{indent}"{model_id}": {{\n'
        f'{indent}  "name": "{display_name}",\n'
        f'{indent}  "limit": {{ "context": {context}, "output": {output} }}\n'
        f"{indent}}}"
    )


def _remove_entry(text: str, open_brace: int, close_brace: int) -> str:
    """Remove one models entry, key and object, without leaving a dangling comma.

    The key sits before the opening brace, so cutting from the brace leaves
    "id": behind. A trailing comma before the closing brace is invalid in
    plain JSON, so it goes too when the removed entry was the last one.
    """
    key_start = open_brace
    i = open_brace - 1
    while i >= 0 and text[i] in " \t\r\n":
        i -= 1
    if i >= 0 and text[i] == ":":
        i -= 1
    while i >= 0 and text[i] in " \t\r\n":
        i -= 1
    if i >= 0 and text[i] == '"':
        # that quote closes the key; its opening quote is the one before it
        opening = text.rfind('"', 0, i)
        if opening >= 0:
            key_start = opening
    end = close_brace + 1
    j = end
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j < len(text) and text[j] == ",":
        end = j + 1
    out = text[:key_start] + text[end:]
    # a comma now directly before the closing brace would be invalid
    head = out[:key_start].rstrip()
    if head.endswith(","):
        rest = out[key_start:]
        probe = rest.lstrip()
        if probe.startswith("}") or probe.startswith("]"):
            out = head[:-1].rstrip() + rest
    return out


def _splice_entries(text: str, models_close: int, addition: list[str]) -> str:
    """Insert rendered entries at the end of a models block.

    One implementation for both splice sites: the closing comma goes on the
    last line of code, before any trailing comment, so a // comment can never
    swallow it.
    """
    head_all = text[:models_close]
    code, comment = _split_trailing_comment(head_all)
    sep = "" if code.rstrip().endswith(",") else ","
    block = ",\n".join(addition)
    return code.rstrip() + sep + "\n" + block + "\n" + comment + text[models_close:]


def _limit_shape(entry: str) -> str | None:
    """Return the entry's "limit": { ... } text, or None."""
    m = re.search(r'"limit"\s*:\s*\{[^{}]*\}', entry)
    return m.group(0) if m else None


def _shape_with_cap(shape: str, context: int) -> str:
    """Return the limit shape with its context (and input) clamped."""
    out = re.sub(r'"context"\s*:\s*\d+', f'"context": {context}', shape)
    out = re.sub(r'"input"\s*:\s*(\d+)', lambda m: f'"input": {context}', out)
    return out


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------

def fetch_catalog_raw() -> str:
    """Fetch the catalog body.

    The request carries the gateway key. Without it the endpoint answers with
    a wider list that includes embedding, tts and video models, which carry no
    context window and are not chat routes.
    """
    token = os.environ.get("LLM_GATEWAY_API_KEY", "")
    req = urllib.request.Request(CATALOG_URL + "?detailed=true")
    req.add_header("User-Agent", "check-fleet-context-cap/1")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def load_catalog(path: str | None, offline: bool) -> tuple[dict[str, int], dict[str, str], str]:
    """Return ({id: context}, {id: display name}, source description).

    In --offline mode no catalog is read at all, from the network or from a
    cache: the check then covers only the routes the configs declare.
    """
    names: dict[str, str] = {}
    if path:
        with open(path, encoding="utf-8") as handle:
            return _catalog_from(handle.read(), path, names)
    if offline:
        return {}, names, "offline (configured routes only)"
    try:
        raw = fetch_catalog_raw()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        cache = cache_path()
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as handle:
                return _catalog_from(handle.read(), f"cached catalog ({cache}), live fetch failed: {exc}", names)
        raise CatalogUnavailable(
            f"the gateway catalog could not be read ({exc}) and no cache exists at {cache}"
        ) from exc
    cache = cache_path()
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as handle:
        handle.write(raw)
    return _catalog_from(raw, f"live catalog (cached at {cache})", names)


def _catalog_from(raw: str, source: str, names: dict[str, str]) -> tuple[dict[str, int], dict[str, str], str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogUnavailable(f"{source}: not valid JSON ({exc})") from exc
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        data = payload["data"]
    elif isinstance(payload, list):
        data = payload
    else:
        raise CatalogUnavailable(
            f"{source}: not a gateway catalog dump (expected a list of models or a 'data' list)"
        )
    contexts: dict[str, int] = {}
    for model in data:
        if not isinstance(model, dict):
            raise CatalogUnavailable(f"{source}: catalog entry is not an object: {model!r}")
        mid = model.get("id")
        ctx = model.get("context_length")
        if mid and isinstance(ctx, int) and ctx > 0:
            contexts[mid] = ctx
        if mid:
            names[mid] = model.get("display_name") or model.get("name") or mid
    return contexts, names, source


# --------------------------------------------------------------------------
# the summarizer window
# --------------------------------------------------------------------------

def _top_level_indent(text: str) -> str:
    """Return the indentation of the file's outermost keys."""
    best: int | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue
        m = re.match(r'^(\s*)"[^"]+"\s*:', line)
        if m:
            width = len(m.group(1))
            if best is None or width < best:
                best = width
    return " " * (best or 0)


def _top_level_string(text: str, key: str) -> str | None:
    """Return a top-level string value, matched only at the file's own indent.

    The config's own keys sit at the outermost indent level. A nested block
    that happens to carry the same key (an MCP server with a "buffer", an
    agent with a "model") must not be mistaken for it.
    """
    indent = re.escape(_top_level_indent(text))
    m = re.search(rf'^{indent}"{re.escape(key)}"\s*:\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


def _top_level_number(text: str, key: str) -> int | None:
    indent = re.escape(_top_level_indent(text))
    m = re.search(rf'^{indent}"{re.escape(key)}"\s*:\s*(\d+)', text, re.M)
    return int(m.group(1)) if m else None


def _summarizer_route(text: str) -> tuple[str, str] | None:
    """Return (provider, model) of the route that summarizes the context.

    kilo uses small_model for housekeeping. opencode uses a summarizer agent.
    """
    small = _top_level_string(text, "small_model")
    if small:
        provider, _, model = small.partition("/")
        return provider, model
    m = re.search(r'"summarizer"\s*:\s*\{[^{}]*?"model"\s*:\s*"([^"]+)"', text, re.S)
    if m:
        provider, _, model = m.group(1).partition("/")
        return provider, model
    m = re.search(
        r'"summarizer"\s*:\s*\{[^{}]*?"model"\s*:\s*\{\s*"providerID"\s*:\s*"([^"]+)"\s*,\s*"model"\s*:\s*"([^"]+)"',
        text,
        re.S,
    )
    if m:
        return m.group(1), m.group(2)
    return None


def _compaction_buffer(text: str) -> int:
    """The compaction headroom the config declares, in tokens.

    The buffer lives inside the compaction block, not at the file's top level,
    so it is read from that block: "buffer" is the current knob name and
    "reserved" the older one.
    """
    m = re.search(r'"compaction"\s*:\s*\{', text)
    if not m:
        return 0
    open_brace = text.index("{", m.start())
    try:
        close = _scan_forward(text, open_brace)
    except ValueError:
        return 0
    block = text[open_brace : close + 1]
    mb = re.search(r'"buffer"\s*:\s*(\d+)', block)
    if mb:
        return int(mb.group(1))
    mr = re.search(r'"reserved"\s*:\s*(\d+)', block)
    if mr:
        return int(mr.group(1))
    return 0


def check_summarizer_window(text: str, rel: str, problems: list[str]) -> None:
    """The summarizer must be able to hold what it will summarize.

    Compaction fires at (limit.context - buffer). If the summarizer's own
    window is smaller than that, every compaction attempt overflows and the
    session dies with "Compaction exhausted" instead of compacting.

    Every dispatch route is checked, not just the default: a per-route override
    can move the highest trigger away from the default route.
    """
    route = _summarizer_route(text)
    if not route:
        return
    buffer_val = _compaction_buffer(text)
    if buffer_val == 0:
        # The opencode catalog file carries no compaction block; its effective
        # session config merges the sibling .jsonc block.
        return
    small_provider, small_model = route
    small_limit = _model_limit(text, small_provider, small_model)
    if small_limit is None:
        problems.append(f"{rel}: the summarizer {small_provider}/{small_model} has no configured limit.context")
        return

    for provider_id, _blk in provider_blocks(text):
        if provider_id not in DISPATCH_PROVIDERS:
            continue
        span = provider_models_span(text, provider_id)
        if span is None:
            continue
        for model_id, open_brace, close in model_entries(text, span):
            entry = text[open_brace : close + 1]
            m = re.search(r'"context"\s*:\s*(\d+)', entry)
            if not m:
                continue
            context = int(m.group(1))
            trigger = context - buffer_val
            if small_limit < trigger:
                problems.append(
                    f"{rel}: {provider_id}/{model_id} compaction fires at {trigger} tokens "
                    f"(context {context} - buffer {buffer_val}) but the summarizer "
                    f"{small_provider}/{small_model} only has a {small_limit} token window, "
                    "so every compaction attempt would overflow"
                )


def _model_limit(text: str, provider_id: str, model_id: str) -> int | None:
    """Return the configured limit.context for one route, or None."""
    span = provider_models_span(text, provider_id)
    if span is None:
        return None
    for mid, open_brace, close in model_entries(text, span):
        if mid != model_id:
            continue
        entry = text[open_brace : close + 1]
        m = re.search(r'"context"\s*:\s*(\d+)', entry)
        return int(m.group(1)) if m else None
    return None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="rewrite the configs to the cap")
    ap.add_argument("--offline", action="store_true", help="check the configured routes only")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--cap",
        type=int,
        default=None,
        help=(
            "use this cap instead of the fleet default; cancels route overrides. "
            "--apply refuses to lower a declared override without --allow-override-lowering"
        ),
    )
    ap.add_argument(
        "--allow-override-lowering",
        action="store_true",
        help="with --apply, allow an explicit --cap below a declared override to rewrite it down",
    )
    ap.add_argument("--catalog", help="read the catalog from this file instead of the live endpoint")
    args = ap.parse_args()

    explicit_cap = args.cap is not None
    use_overrides = not explicit_cap
    if args.cap is None:
        args.cap = FLEET_CAP

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    config_texts: dict[str, str] = {}
    for rel, _expected in FLEET_CONFIGS:
        if os.path.exists(rel):
            config_texts[rel] = open(rel, encoding="utf-8").read()

    if args.apply and explicit_cap and not args.allow_override_lowering:
        for rel, text in config_texts.items():
            for (provider_id, model_id), _cap in ROUTE_CAP_OVERRIDES.items():
                current = _model_limit(text, provider_id, model_id)
                if current is not None and current > args.cap:
                    print(
                        f"REFUSING: {rel}: {provider_id}/{model_id} is {current}; "
                        f"--cap {args.cap} would lower a declared override. "
                        "Pass --allow-override-lowering to do that.",
                        file=sys.stderr,
                    )
                    return 2

    try:
        catalog, names, source = load_catalog(args.catalog, args.offline)
    except CatalogUnavailable as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        print(
            "The check could not compare against the provider catalog, so it cannot "
            "prove every served route is capped. Re-run when the gateway is reachable, "
            "or pass --catalog with a saved dump.",
            file=sys.stderr,
        )
        return 2
    print(f"catalog source: {source} ({len(catalog)} routes)")

    problems: list[str] = []
    changed: list[str] = []
    reports: list[str] = []

    # Parity: the lowest cap any fleet config declares for a route wins, so two
    # copies of one route cannot disagree about its window. A declared override
    # is exempt from the floor and enforced by its own exact-value check.
    parity_cap: dict[tuple[str, str], int] = {}
    config_buffers: dict[str, int] = {}
    for rel, _expected in FLEET_CONFIGS:
        text = config_texts.get(rel)
        if text is None:
            continue
        buffer_val = _compaction_buffer(text)
        if buffer_val:
            config_buffers[rel] = buffer_val
        for provider_id, blk in provider_blocks(text):
            span_p = provider_models_span(text, provider_id)
            if span_p is None:
                continue
            for model_id, open_b, close_b in model_entries(text, span_p):
                entry = text[open_b : close_b + 1]
                m = re.search(r'"context"\s*:\s*(\d+)', entry)
                if not m:
                    continue
                key = (provider_id, model_id)
                prior = parity_cap.get(key)
                if prior is None or int(m.group(1)) < prior:
                    parity_cap[key] = int(m.group(1))

    if len(set(config_buffers.values())) > 1:
        rendered = ", ".join(f"{rel}={cap}" for rel, cap in sorted(config_buffers.items()))
        problems.append(f"compaction buffers disagree across the active configs: {rendered}")

    for rel, expected_providers in FLEET_CONFIGS:
        original = config_texts.get(rel)
        if original is None:
            problems.append(f"{rel}: file is missing")
            continue
        text = original

        for provider_id in expected_providers:
            span = provider_models_span(text, provider_id)
            if span is None:
                problems.append(f"{rel}: no {provider_id} provider block")
                continue

            entries = model_entries(text, span)
            if not entries:
                problems.append(f"{rel}: {provider_id} models block is empty")
                continue

            if provider_id == "llmgateway":
                check_summarizer_window(text, rel, problems)

            # llmgateway merges the gateway catalog over the config at runtime,
            # so every catalog route is dispatchable and every one of them needs
            # a cap. The openai provider is a built-in catalog, so only the
            # routes the fleet names are required to carry one.
            cap_every_entry = provider_id == "llmgateway"
            required = REQUIRED_ROUTES.get(provider_id, ())

            style = "inline"
            indent = "        "
            sibling_input = None
            for model_id, open_brace, close in entries:
                entry = text[open_brace : close + 1]
                if '"input"' in entry:
                    sibling_input = True
                if '"limit"' not in entry:
                    style = _entry_style(entry)
                    line_start = text.rfind("\n", 0, open_brace) + 1
                    line = text[line_start:]
                    indent = line[: len(line) - len(line.lstrip())]
                    break

            # rewrite back to front so earlier offsets stay valid
            for model_id, open_brace, close in reversed(entries):
                entry = text[open_brace : close + 1]
                native = catalog.get(model_id)
                has_limit = '"limit"' in entry
                key = (provider_id, model_id)
                declared_override = use_overrides and key in ROUTE_CAP_OVERRIDES
                target_cap = route_target(
                    provider_id,
                    model_id,
                    args.cap,
                    parity_cap,
                    use_overrides=use_overrides,
                )
                if args.apply:
                    if has_limit:
                        if declared_override:
                            new_entry, did_change = _set_context(entry, target_cap)
                        else:
                            new_entry, did_change = _clamp_context(entry, target_cap, native)
                        # kilo's compaction uses the input limit when it is
                        # present, so a block whose siblings set it sets it
                        # on every entry.
                        if sibling_input and '"input"' not in new_entry:
                            m = re.search(r'"context"\s*:\s*(\d+)', new_entry)
                            if m:
                                new_entry = re.sub(
                                    r'("limit"\s*:\s*\{)',
                                    lambda mm: f'{mm.group(1)} "input": {m.group(1)},',
                                    new_entry,
                                    count=1,
                                )
                                did_change = True
                        if did_change:
                            text = text[:open_brace] + new_entry + text[close + 1 :]
                            changed.append(f"{rel}: {provider_id}/{model_id}")
                    elif cap_every_entry or model_id in required:
                        target = min(target_cap, native) if native else target_cap
                        output = DEFAULT_OUTPUT if not native else min(DEFAULT_OUTPUT, max(4096, native // 10))
                        new_entry = _insert_limit(entry, target, output, sibling_input)
                        text = text[:open_brace] + new_entry + text[close + 1 :]
                        changed.append(f"{rel}: {provider_id}/{model_id}")
                else:
                    if not has_limit:
                        if cap_every_entry or model_id in required:
                            problems.append(f"{rel}: {provider_id}/{model_id} has no limit.context")
                        continue
                    m = re.search(r'"context"\s*:\s*(\d+)', entry)
                    if not m:
                        problems.append(f"{rel}: {provider_id}/{model_id} has a limit with no context value")
                        continue
                    ctx = int(m.group(1))
                    if sibling_input and '"input"' not in entry:
                        problems.append(
                            f"{rel}: {provider_id}/{model_id} sets no input limit although its "
                            "siblings do, and kilo's compaction reads the input limit when present"
                        )
                    if not declared_override and ctx > target_cap:
                        problems.append(
                            f"{rel}: {provider_id}/{model_id} context {ctx} exceeds its {target_cap} cap"
                        )
                    if native and native < ctx:
                        problems.append(
                            f"{rel}: {provider_id}/{model_id} is capped at {ctx} but the provider only serves {native}"
                        )
                    if args.verbose:
                        print(f"  {rel}: {provider_id}/{model_id} context={ctx} native={native}")

            if args.apply and provider_id == "llmgateway" and catalog:
                # The three fleet configs declare the same provider block. A
                # route the gateway no longer serves is stale: the harness
                # cannot reach it, so the entry is removed and the three
                # files end up declaring the same set.
                span2 = provider_models_span(text, provider_id)
                assert span2
                entries2 = model_entries(text, span2)
                stale = []
                for model_id, open_b, close_b in reversed(entries2):
                    if model_id not in catalog:
                        stale.append(model_id)
                        text = _remove_entry(text, open_b, close_b)
                for model_id in stale:
                    changed.append(f"{rel}: {provider_id}/{model_id} (stale, removed)")

                # add any catalog route the config never declared: the harness
                # merges the catalog at runtime, so an undeclared route is still
                # dispatchable, just uncapped.
                span3 = provider_models_span(text, provider_id)
                assert span3
                configured = {mid for mid, _, _ in model_entries(text, span3)}
                missing = sorted(set(catalog) - configured)
                if missing:
                    addition = []
                    for model_id in missing:
                        native = catalog[model_id]
                        target = route_target(
                            provider_id,
                            model_id,
                            args.cap,
                            parity_cap,
                            use_overrides=use_overrides,
                            native=native,
                        )
                        output = min(DEFAULT_OUTPUT, max(4096, native // 10))
                        addition.append(
                            _render_entry(model_id, names.get(model_id, model_id), target, output, style, indent)
                        )
                    text = _splice_entries(text, span3[1], addition)
                    for model_id in missing:
                        changed.append(f"{rel}: {provider_id}/{model_id} (declared)")

            if args.apply and required:
                # a required route the config never declared: add it, capped,
                # in the same shape as its siblings in this block.
                span2 = provider_models_span(text, provider_id)
                assert span2
                entries2 = model_entries(text, span2)
                configured = {mid for mid, _, _ in entries2}
                absent = [mid for mid in required if mid not in configured]
                if absent:
                    shape = None
                    for mid, open_b, close_b in entries2:
                        candidate = _limit_shape(text[open_b : close_b + 1])
                        if candidate:
                            shape = candidate
                    addition = []
                    for model_id in absent:
                        native = catalog.get(model_id)
                        target = route_target(
                            provider_id,
                            model_id,
                            args.cap,
                            parity_cap,
                            use_overrides=use_overrides,
                            native=native,
                        )
                        limit = _shape_with_cap(shape, target) if shape else f'"limit": {{ "context": {target}, "output": {DEFAULT_OUTPUT} }}'
                        addition.append(f'{indent}"{model_id}": {{ {limit} }}')
                    text = _splice_entries(text, span2[1], addition)
                    for model_id in absent:
                        changed.append(f"{rel}: {provider_id}/{model_id} (declared)")

            if not args.apply:
                span3 = provider_models_span(text, provider_id)
                if span3:
                    configured = {mid for mid, _, _ in model_entries(text, span3)}
                    for model_id in required:
                        if model_id not in configured:
                            problems.append(
                                f"{rel}: {provider_id}/{model_id} is a dispatch route but no config declares it"
                            )

        # A provider the fleet does not dispatch on keeps its own windows, but
        # two copies of one route cannot disagree: where a sibling config
        # already caps the route lower, this config is held to the same number.
        # Routes with no limit at all are reported, since an uncapped route is
        # the failure this check exists for.
        for provider_id, blk in provider_blocks(text):
            if provider_id in DISPATCH_PROVIDERS:
                continue
            span_p = provider_models_span(text, provider_id)
            if span_p is None:
                continue
            for model_id, open_b, close_b in model_entries(text, span_p):
                entry = text[open_b : close_b + 1]
                m = re.search(r'"context"\s*:\s*(\d+)', entry)
                target_cap = parity_cap.get(
                    (provider_id, model_id),
                    route_cap(provider_id, model_id, args.cap, use_overrides=False),
                )
                if m:
                    if int(m.group(1)) > target_cap:
                        if not args.apply:
                            problems.append(
                                f"{rel}: {provider_id}/{model_id} context {m.group(1)} exceeds the "
                                f"{target_cap} its sibling config declares"
                            )
                        else:
                            new_entry, _ = _clamp_context(entry, target_cap, None)
                            text = text[:open_b] + new_entry + text[close_b + 1 :]
                            changed.append(f"{rel}: {provider_id}/{model_id}")
                    elif int(m.group(1)) > args.cap:
                        reports.append(
                            f"{rel}: {provider_id}/{model_id} context {m.group(1)} (left alone: not a dispatch provider)"
                        )
                elif '"name"' in entry:
                    reports.append(
                        f"{rel}: {provider_id}/{model_id} has no limit.context (left alone: not a dispatch provider)"
                    )

        if args.apply and text != original:
            open(rel, "w", encoding="utf-8").write(text)

    if not args.apply and catalog:
        for rel, _expected in FLEET_CONFIGS:
            text = config_texts.get(rel)
            if text is None:
                continue
            span = provider_models_span(text, "llmgateway")
            if span is None:
                continue
            configured = {mid for mid, _, _ in model_entries(text, span)}
            for model_id in sorted(set(catalog) - configured):
                problems.append(
                    f"{rel}: the gateway serves {model_id} but no fleet config declares it"
                )
            for model_id in sorted(configured - set(catalog)):
                problems.append(
                    f"{rel}: declares {model_id}, which the gateway no longer serves"
                )

    if not args.apply and use_overrides:
        for (provider_id, model_id), cap in ROUTE_CAP_OVERRIDES.items():
            for rel, expected_providers in FLEET_CONFIGS:
                if provider_id not in expected_providers:
                    continue
                text = config_texts.get(rel)
                if text is None:
                    continue
                actual = _model_limit(text, provider_id, model_id)
                if actual is None:
                    problems.append(
                        f"{rel}: {provider_id}/{model_id} declares a {cap} override "
                        "but has no limit.context"
                    )
                    continue
                if actual != cap:
                    problems.append(
                        f"{rel}: {provider_id}/{model_id} context {actual} must be {cap} "
                        "(declared override)"
                    )
                    continue
                buffer_val = _compaction_buffer(text)
                trigger = actual - buffer_val
                if buffer_val and trigger != OVERRIDE_TRIGGER:
                    problems.append(
                        f"{rel}: {provider_id}/{model_id} compacts at {trigger} tokens "
                        f"(context {actual} - buffer {buffer_val}), but the declared "
                        f"override trigger is {OVERRIDE_TRIGGER}"
                    )

    # the fleet cap lives in more than one script; they have to agree
    for rel in ("scripts/sync-pi-nanogpt.py",):
        if os.path.exists(rel):
            other = open(rel, encoding="utf-8").read()
            m = re.search(r'^CONTEXT_CAP\s*=\s*(\d+)', other, re.M)
            if not m:
                problems.append(f"{rel}: no CONTEXT_CAP constant to compare against the fleet default")
            elif int(m.group(1)) != FLEET_CAP:
                problems.append(
                    f"{rel}: CONTEXT_CAP is {m.group(1)} but the fleet default is {FLEET_CAP}"
                )

    if args.apply:
        if changed:
            print(f"applied fleet context targets to {len(changed)} route(s):")
            for line in changed:
                print(f"  {line}")
        else:
            print("every route already carries a limit at or below its target cap")
        return 0

    if problems:
        print(f"FAIL: {len(problems)} fleet context problem(s):", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    if reports:
        print(f"routes left alone on providers the fleet does not dispatch on:")
        for line in reports:
            print(f"  {line}")

    if use_overrides and ROUTE_CAP_OVERRIDES:
        overrides = ", ".join(
            f"{provider_id}/{model_id} at {cap}"
            for (provider_id, model_id), cap in sorted(ROUTE_CAP_OVERRIDES.items())
        )
        print(
            f"OK: every dispatch route in the fleet configs is capped at {args.cap}, "
            f"except {overrides}"
        )
    else:
        print(f"OK: every dispatch route in the fleet configs is capped at {args.cap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

---
name: playwright-mcp
description: Browser automation via Playwright MCP server. Screenshots, forms, navigation.
---

# Playwright MCP

Browser automation using Playwright MCP server via `mcporter`.

## Setup

```bash
# 1. Install chromium (the server runs through npx, nothing global to install)
mise -C ~/.dotfiles/mise-en-system run install-chromium   # fish: mise-sys install-chromium

# 2. Configure ~/.config/mcporter/config.json (dotfiles tracks this file)
{
  "mcpServers": {
    "playwright-mcp": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest", "--config", "${HOME}/.config/playwright-mcp/config.json"]
    }
  }
}

# 3. Verify
mcporter list  # Should show playwright-mcp
```

## Usage

```bash
mcporter call playwright-mcp.<tool> param=value
```

**Key=value format only.** No JSON, no --flags.

```bash
# ✅ Correct
mcporter call playwright-mcp.browser_navigate url=https://example.com

# ❌ Wrong
mcporter call playwright-mcp.browser_navigate "https://example.com"
mcporter call playwright-mcp.browser_navigate --url="https://example.com"
```

## Common Tools

| Tool | Usage |
|------|-------|
| `browser_navigate` | `url=https://example.com` |
| `browser_screenshot` | `path=/workspace/shot.png fullPage=true` |
| `browser_click` | `selector="#submit"` |
| `browser_fill` | `selector="#email" value="test@example.com"` |
| `browser_get_text` | `selector="h1"` |
| `browser_wait_for_selector` | `selector=".loaded" timeout=5000` |
| `browser_evaluate` | `expression="document.title"` |

## Workflow Example

```bash
# Navigate
mcporter call playwright-mcp.browser_navigate url=http://localhost:3000

# Interact
mcporter call playwright-mcp.browser_fill selector="#email" value="test@test.com"
mcporter call playwright-mcp.browser_click selector="button[type='submit']"

# Wait & capture
mcporter call playwright-mcp.browser_wait_for_selector selector=".success" timeout=5000
mcporter call playwright-mcp.browser_screenshot path=/workspace/screenshots/result.png
```

## Best Practices

1. **Wait before acting** — Use `browser_wait_for_selector` or `browser_wait_for_load`
2. **Stable selectors** — Prefer `data-testid` over CSS classes
3. **Organize screenshots** — Use subdirectories by feature
4. **Full page for regression** — Use `fullPage=true` for visual diffs

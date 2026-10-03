# Playwright MCP Cheatsheet

## ⚠️ Important: mcporter Syntax

Arguments must be passed as `key=value` pairs:

```bash
# ✅ CORRECT:
mcporter call playwright-mcp.browser_navigate url=https://example.com
mcporter call playwright-mcp.browser_fill selector="#email" value="test@example.com"

# ❌ INCORRECT:
mcporter call playwright-mcp.browser_navigate "https://example.com"
mcporter call playwright-mcp.browser_navigate --url="https://example.com"
```

## Quick Setup

```bash
# Run setup script
/workspace/.pi/skills/playwright-mcp/setup.sh

# Or manually edit ~/.config/mcporter/config.json
```

## Most Common Commands

### Navigate
```bash
mcporter call playwright-mcp.browser_navigate url=https://example.com
```

### Screenshot
```bash
# Full page
mcporter call playwright-mcp.browser_screenshot path=/workspace/screenshots/page.png fullPage=true

# Element only
mcporter call playwright-mcp.browser_screenshot path=/workspace/screenshots/element.png selector="#my-element"
```

### Click
```bash
mcporter call playwright-mcp.browser_click selector="button#submit"
```

### Fill Form
```bash
mcporter call playwright-mcp.browser_fill selector="#email" value="test@example.com"
```

### Get Text
```bash
mcporter call playwright-mcp.browser_get_text selector="h1"
```

### Wait
```bash
mcporter call playwright-mcp.browser_wait_for_selector selector=".loaded" timeout=5000
```

### JavaScript
```bash
mcporter call playwright-mcp.browser_evaluate expression="document.title"
```

### PDF
```bash
mcporter call playwright-mcp.browser_pdf path=/workspace/screenshots/page.pdf
```

## Full Test Flow Example

```bash
#!/bin/bash
set -e

echo "🧪 Testing login flow..."

# Navigate
mcporter call playwright-mcp.browser_navigate url=http://localhost:3000/login

# Fill form
mcporter call playwright-mcp.browser_fill selector="#email" value="user@test.com"
mcporter call playwright-mcp.browser_fill selector="#password" value="password123"

# Submit
mcporter call playwright-mcp.browser_click selector="button[type='submit']"

# Wait for redirect
mcporter call playwright-mcp.browser_wait_for_selector selector=".dashboard" timeout=10000

# Verify
mcporter call playwright-mcp.browser_get_text selector=".welcome-message"

# Screenshot
mcporter call playwright-mcp.browser_screenshot path=/workspace/screenshots/login-success.png

echo "✅ Test passed!"
```

## Troubleshooting

```bash
# Check if configured
mcporter list | grep playwright

# Test basic connectivity
mcporter call playwright-mcp.browser_navigate url=https://example.com

# The server launches pacman's chromium (see ~/.config/playwright-mcp/config.json)
test -x /usr/bin/chromium || mise-sys install-chromium

# View logs (if any)
mcporter call playwright-mcp.browser_navigate url=https://example.com 2>&1
```

## Selector Tips

| Type | Example | Best For |
|------|---------|----------|
| ID | `#submit-button` | Unique elements |
| Class | `.btn-primary` | Styled elements |
| Attribute | `[data-testid="login"]` | **Recommended** - Stable |
| CSS | `nav > ul > li:first-child` | Complex queries |
| XPath | (use sparingly) | Complex DOM |

## Timeouts

Default: 30 seconds

Override per action:
```bash
mcporter call playwright-mcp.browser_wait_for_selector selector=".slow" timeout=60000
```

## File Locations

| Type | Default Path |
|------|--------------|
| Screenshots | `/workspace/screenshots/` |
| PDFs | `/workspace/screenshots/` |
| Config | `~/.config/mcporter/config.json` |
| Logs | Output to terminal |

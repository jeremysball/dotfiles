#!/bin/bash
# Playwright MCP Setup Script
# Run this to configure mcporter for Playwright MCP

set -e

MCP_CONFIG_DIR="${HOME}/.config/mcporter"
MCP_CONFIG_FILE="${MCP_CONFIG_DIR}/config.json"

echo "🎭 Setting up Playwright MCP..."
echo ""

# Create config directory if it doesn't exist
mkdir -p "$MCP_CONFIG_DIR"

# Check if config already exists
if [ -f "$MCP_CONFIG_FILE" ]; then
    echo "⚠️  Found existing mcporter config at $MCP_CONFIG_FILE"
    echo "   Backing up to ${MCP_CONFIG_FILE}.bak"
    cp "$MCP_CONFIG_FILE" "${MCP_CONFIG_FILE}.bak"
fi

# Create or update config. Same entry as the dotfiles-tracked
# ~/.config/mcporter/config.json. The quoted heredoc keeps ${HOME} literal;
# mcporter expands it at load time. --config points at
# ~/.config/playwright-mcp/config.json, which launches /usr/bin/chromium.
cat > "$MCP_CONFIG_FILE" << 'EOF'
{
  "mcpServers": {
    "playwright-mcp": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest", "--config", "${HOME}/.config/playwright-mcp/config.json"]
    }
  }
}
EOF

echo "✅ Configuration written to $MCP_CONFIG_FILE"
echo ""
echo "📋 Configuration:"
cat "$MCP_CONFIG_FILE"
echo ""
echo "🧪 Testing connection..."
echo ""

# Test the connection
if mcporter list 2>/dev/null | grep -q "playwright-mcp"; then
    echo "✅ Playwright MCP is configured and ready!"
    echo ""
    echo "🎯 Quick test:"
    echo "   mcporter call playwright-mcp.browser_navigate url=https://example.com"
else
    echo "⚠️  Configuration saved but mcporter may not detect it yet."
    echo "   Try running: mcporter list"
    echo ""
    echo "   The server runs through npx, so there is nothing to install"
    echo "   globally. Chromium comes from pacman: mise-sys install-chromium"
fi

echo ""
echo "📖 Next steps:"
echo "   1. Ensure chromium is installed: test -x /usr/bin/chromium"
echo "   2. Test with: mcporter call playwright-mcp.browser_navigate url=https://example.com"
echo "   3. Take a screenshot: mcporter call playwright-mcp.browser_screenshot path=/tmp/test.png"
echo ""
echo "   ⚠️  Remember: Arguments must use key=value format (NOT --key=value or JSON)"
echo ""
echo "   For full documentation, see:"
echo "   /workspace/.pi/skills/playwright-mcp/SKILL.md"

#!/usr/bin/env bash
# agent-bash-env.sh: mise activation for agent tool shells.
#
# Why: a kilo/opencode/claude bash call inherits a PATH frozen at harness
# launch (Claude Code even bakes it into its per-session shell snapshot,
# ~/.claude/shell-snapshots/snapshot-bash-*.sh). A frozen PATH resolves the
# global tool set but never the invoking directory's .mise.toml: wrong
# versions, missing project tools, no [env] table. That is what the
# `mise exec` workaround papers over.
#
# `eval "$(mise activate bash)"` re-resolves mise for the shell's own working
# directory at every spawn: tools, versions and [env] all come from the
# nearest .mise.toml, so a plain `node`/`uv`/`ast-grep` is the project's.
# Measured on this box (2026-10-18): ~0.3-0.4s per shell start, once per
# command. That beats the shims alternative (~0.2s per tool invocation), and
# full activation also exports [env] vars into the command, which shims only
# do for the tool process itself.
#
# Wired from:
#   .config/mise/agent-shell.sh        kilo/opencode `shell` wrapper
#   .config/mise/claude-bash-env.sh    Claude Code Bash tool (BASH_ENV)
# Interactive shells keep their own activation (fish conf.d/01-mise.fish,
# .bashrc `mise activate bash`); this file is only for non-interactive
# agent shells.
#
# Guarded: a box without mise still gets a working shell.
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi

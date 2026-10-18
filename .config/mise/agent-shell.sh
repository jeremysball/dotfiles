#!/usr/bin/env bash
# agent-shell.sh: `shell` executable for the kilo and opencode terminal and
# shell tools: a bash that is fully mise-activated before the command runs,
# so agent commands resolve the project's .mise.toml and never need the
# `mise exec` workaround. See agent-bash-env.sh alongside for the reasoning.
#
# The harness invokes `<shell> -c <command>` for tool calls and `<shell>`
# bare for the terminal tool (observed live via kilo, 2026-10-18); "$@"
# passes both shapes through untouched. Activation runs in the caller's
# working directory first, so the resolution target is whatever project the
# agent is working in.
. "${XDG_CONFIG_HOME:-$HOME/.config}/mise/agent-bash-env.sh"
exec bash "$@"

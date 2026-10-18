#!/usr/bin/env bash
# claude-bash-env.sh: BASH_ENV for the Claude Code Bash tool.
#
# Claude Code runs every Bash tool command as:
#   /bin/bash -c 'source ~/.claude/shell-snapshots/snapshot-bash-*.sh ... && eval "<command>"'
# (observed via /proc/$$/cmdline from inside the tool, 2026-10-18).
# BASH_ENV is read at bash startup, before that source, so a plain
# activation would run first and the snapshot's `export PATH='...'` would
# then put the frozen launch-time PATH back on top. That is why Claude Code
# inline commands kept resolving global tool versions even with
# agent-bash-env.sh wired: activation ran, then lost the race.
#
# The fix is the `source` override below: when the file being sourced is one
# of Claude Code's shell snapshots (and only then), mise is re-activated
# afterwards, so activation is the LAST thing to touch PATH. The snapshot is
# sourced before every Bash tool command, so this re-resolves the project's
# .mise.toml per command: the same semantics the kilo/opencode shell
# wrapper gives (see agent-shell.sh), for the harness that has no `shell`
# override of its own.
#
# Measured cost: ~0.3-0.4s per Bash tool call (one `mise activate bash`
# evaluation per command). Verified 2026-10-18 against a project pinning
# node = "24.21.0": `node -v` inside the tool answered v24.21.0 instead of
# the snapshot's v26.7.0.
#
# Behavior that looks like a bug but is deliberate: `source` is shadowed by
# a function in this shell. Every source() call goes through it, but the
# re-activation only fires for paths matching */shell-snapshots/*, so
# sourcing anything else behaves normally (plus one pattern match). See
# docs/things-that-look-like-bugs.md for the durable copy of this note.
. "${XDG_CONFIG_HOME:-$HOME/.config}/mise/agent-bash-env.sh"

source() {
  builtin source "$@"
  case "$1" in
    */shell-snapshots/*) . "${XDG_CONFIG_HOME:-$HOME/.config}/mise/agent-bash-env.sh" ;;
  esac
}

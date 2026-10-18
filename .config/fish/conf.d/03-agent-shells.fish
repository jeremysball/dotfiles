# 03-agent-shells.fish: mise-activated command env for agent harnesses.
#
# kilo and opencode tool commands run in plain bash whose PATH was frozen at
# harness launch (Claude Code additionally re-exports that frozen PATH from
# its per-session snapshot right after startup). The old workaround was
# wrapping every command in `mise exec`; these wrappers make each harness
# start from a bash that has already resolved the working directory's
# .mise.toml (tools, versions, [env]).
#
# kilo needs no wrapper here: its `shell` config key points at
# .config/mise/agent-shell.sh instead. opencode's shell tool ignores that
# key (verified 2026-10-18: commands run even with shell set to a
# nonexistent path) and ignores $SHELL, but its bash tool honors BASH_ENV,
# so this env export is the working lever. Claude Code honors BASH_ENV too,
# and its file adds the source() re-activation that its snapshot needs.
# Details: .config/mise/agent-bash-env.sh and .config/mise/claude-bash-env.sh.
#
# The pre-existing functions/claude.fish launches claude by absolute path
# ($HOME/.local/bin/claude). This startup time definition shadows it in every
# fish session, and `command claude` resolves the identical binary because
# 00-path.fish puts $HOME/.local/bin on PATH globally.

function opencode --wraps opencode
    env BASH_ENV="$HOME/.config/mise/agent-bash-env.sh" command opencode $argv
end

function claude --wraps claude
    env BASH_ENV="$HOME/.config/mise/claude-bash-env.sh" command claude $argv
end

#!/usr/bin/env bash
# install-githooks.sh <repo-path>...
#
# Wires a repo's .githooks/ so the global gates in ~/.config/git/hooks run
# even though the repo sets its own core.hooksPath.
#
# The problem this fixes: core.hooksPath is single-valued and repo-local
# config beats global config, with no merging. A repo that sets
# `core.hooksPath = .githooks` for portability (so a contributor's bare
# clone still gets hooks) silently disables every global hook on this
# machine. Measured 2026-09-01: sixteen repos set the local override and
# not one of them carried the global em-dash gate, so that gate had never
# fired on a commit in any of them.
#
# The fix is a shim. .githooks/<hook> becomes a two-step dispatcher:
#   1. run the global hook of the same name, if this machine has one
#   2. run the repo's own hook, moved aside to .githooks/<hook>.local
# A contributor without dotfiles skips step 1 and still gets step 2.
#
# GIT_HOOKS_CHAINED guards against a loop: the global pre-commit chains
# down to .githooks/<hook> itself, and would otherwise re-enter the shim.
#
# Idempotent. Re-running on an already-shimmed repo replaces the shim and
# leaves .local alone.

set -euo pipefail

HOOKS="pre-commit commit-msg pre-push post-checkout"
GLOBAL_HOOKS="${XDG_CONFIG_HOME:-$HOME/.config}/git/hooks"

die() { echo "install-githooks: $*" >&2; exit 1; }

SHIM_MARKER_RE='^# install-githooks-shim: v[0-9]+$'
is_shim() { [ -f "$1" ] && grep -qE "$SHIM_MARKER_RE" "$1" 2>/dev/null; }

write_shim() {
  cat > "$1" <<'SHIMEOF'
#!/usr/bin/env bash
# install-githooks-shim: v2
# Managed by `mise run install-githooks`. Do not edit.
# Repo-specific checks belong in the .local file this dispatches to.
set -euo pipefail

hook_name="$(basename "$0")"
# Fail open on the lookup, the way every hook in ~/.config/git/hooks already
# does (pre-commit's primary-checkout gate, pre-push:190, post-checkout:17).
# Under `set -e` the bare form aborts the shim, so a context where
# --show-toplevel legitimately fails turns a gate into a hard block: verified
# 2026-09-03 by pushing from a bare repo, where the bare form died `fatal:
# this operation must be run in a work tree` and refused the push while the
# global pre-push exited 0.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
global_hook="${XDG_CONFIG_HOME:-$HOME/.config}/git/hooks/$hook_name"
self_path="$(realpath "$0" 2>/dev/null || echo "$0")"

# 1. global gates (em dash, worktree budget, ...), when dotfiles are applied.
#    Skipped when the global hook is what invoked us, so we do not loop.
if [ -z "${GIT_HOOKS_CHAINED:-}" ] && [ -x "$global_hook" ]; then
  GIT_HOOKS_CHAINED=1 "$global_hook" "$@"
fi

# 2. this repo's own checks, if it has any.
#
# The realpath self-check matches the one in the global hooks, and for the
# same reason: a candidate that resolves back to this file re-enters the shim
# with the same $0 basename, so nothing ever terminates. Verified 2026-09-03
# on a scratch repo whose `hooks/pre-commit` symlinked to `.githooks/pre-commit`
# the commit hung until a 15s timeout killed it. (The `.local` name is
# self-limiting by accident, since re-entry through it changes the basename to
# `pre-commit.local` and the second pass finds nothing; the `hooks/` path has
# no such accident, and relying on one either way is not a guard.)
local_hook="$repo_root/.githooks/$hook_name.local"
alt_hook="$repo_root/hooks/$hook_name"
for candidate in "$local_hook" "$alt_hook"; do
  [ -f "$candidate" ] || continue
  candidate_real="$(realpath "$candidate" 2>/dev/null || echo "")"
  [ -n "$candidate_real" ] && [ "$candidate_real" != "$self_path" ] || continue
  # GIT_HOOKS_CHAINED propagates down, matching the exec block at the end of
  # pre-commit and pre-push:198. Not a bug fix: measured 2026-09-03, a .local
  # that is itself a shim copy already runs the global gates once either way,
  # because re-entry changes the basename to pre-commit.local and the global
  # lookup misses. That is the same accident the realpath check above refuses
  # to rely on, so state the invariant instead: once the gates have run,
  # nothing downstream runs them again.
  if [ -x "$candidate" ]; then
    exec env GIT_HOOKS_CHAINED=1 "$candidate" "$@"
  else
    exec env GIT_HOOKS_CHAINED=1 bash "$candidate" "$@"
  fi
done
SHIMEOF
  chmod +x "$1"
}

install_one() {
  local repo="$1" root prev
  root="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" \
    || die "$repo is not a git repository"

  # Refuse to clobber a hooksPath pointing somewhere this script does not
  # own. Rewriting it to .githooks orphans every hook in the old directory
  # whose name is not in $HOOKS: not moved aside to .local, not shimmed,
  # just silently stops running. Verified 2026-09-03 on a scratch repo with
  # `core.hooksPath = hooks` holding pre-commit and commit-msg: after the
  # install, commit-msg produced no output and no error. The three values
  # below are the ones this script can safely replace, because .githooks
  # ends up dispatching everything they held.
  # --local, not --get: the global config on this machine already sets
  # core.hooksPath to the global directory, and a plain --get would report
  # that inherited value for every repo that records nothing of its own.
  # Only a repo-local override is this script's business. Read from $root
  # rather than $repo so a linked worktree reads the shared repo config.
  if prev="$(git -C "$root" config --local --get core.hooksPath)"; then
    case "${prev/#\~\//$HOME/}" in
      .githooks|*/.githooks|"$GLOBAL_HOOKS") ;;
      *) die "$root records core.hooksPath=$prev, which this script does not own; resolve by hand" ;;
    esac
  fi

  # $HOOKS has to cover every hook the global directory ships, or pointing a
  # repo at .githooks drops the ones it misses. post-checkout is exactly how
  # that bites: it was absent from $HOOKS while ~/.config/git/hooks has had
  # it since 2026-08-23, so any repo whose hooksPath was the global
  # directory lost it on install. Fail loudly on the next such drift rather
  # than silently disabling a gate.
  local g
  for g in "$GLOBAL_HOOKS"/*; do
    [ -x "$g" ] || continue
    case " $HOOKS " in
      *" $(basename "$g") "*) ;;
      *) die "$GLOBAL_HOOKS/$(basename "$g") is executable but not in HOOKS; add it" ;;
    esac
  done

  mkdir -p "$root/.githooks"

  local installed=0 kept=0
  for hook in $HOOKS; do
    local target="$root/.githooks/$hook"

    # A pre-existing repo hook that is not already our shim gets moved aside
    # rather than overwritten, so no repo loses its own checks.
    if [ -e "$target" ] && ! is_shim "$target"; then
      if [ -e "$target.local" ]; then
        die "$root/.githooks/$hook.local already exists; resolve by hand"
      fi
      rel="${target#"$root"/}"
      if git -C "$root" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
        git -C "$root" mv "$rel" "$rel.local"
      else
        mv "$target" "$target.local"
      fi
      chmod +x "$target.local"
      kept=$((kept + 1))
    fi

    # Only install a shim where there is something for it to dispatch to:
    # the repo's own hook, or a global hook of that name.
    if [ -e "$target.local" ] || [ -x "$GLOBAL_HOOKS/$hook" ]; then
      write_shim "$target"
      installed=$((installed + 1))
    fi
  done

  # Always relative, even where the repo previously recorded an absolute
  # path. Git resolves a relative hooksPath per-worktree, so each worktree
  # runs its own .githooks; an absolute one pins every worktree to the
  # primary checkout's files. That difference is not cosmetic here. All work
  # in this setup happens in linked worktrees, so under an absolute path a
  # worktree that has the shim still commits through the primary checkout's
  # unshimmed hook, and the global gates never fire where the commits are
  # actually made. Verified 2026-09-03 on a scratch repo: identical shims,
  # em dash blocked under `.githooks`, committed clean under the absolute
  # form.
  #
  # $root, not the primary checkout. core.hooksPath is repo-wide config, and
  # `git -C <linked worktree> config` already writes to the shared config
  # file every worktree reads (verified: the write from a worktree lands in
  # <primary>/.git/config). Since the value is now the constant .githooks
  # rather than a path, there is no worktree path left to record wrongly.
  # Resolving the primary checkout as dirname(--git-common-dir) instead was
  # actively wrong: for a submodule it yields <super>/.git/modules, so the
  # write lands in the superproject's config and the submodule never gets
  # one; for --separate-git-dir and bare-repo worktrees it yields a
  # non-repository and the script dies under set -e after the shims are
  # already written. All three reproduced on scratch repos 2026-09-03.
  git -C "$root" config core.hooksPath .githooks

  echo "install-githooks: $root ($installed shim(s), $kept repo hook(s) preserved as .local)"
}

if [ $# -eq 0 ]; then
  install_one "."
else
  for repo in "$@"; do install_one "$repo"; done
fi

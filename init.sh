#!/usr/bin/env bash
set -euo pipefail

# Physical path (-P): mise reports each task's `source` with symlinks
# resolved, and the task filter below compares against it. A logical path
# through a symlinked checkout would match nothing and run zero tasks.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$REPO_DIR"

# mise's dotfiles.root setting defaults to ~/.dotfiles. Pointing it at
# REPO_DIR explicitly means dotfile sources resolve correctly even if the
# repo is cloned somewhere else. The `cd` above is separate and just as
# necessary: mise discovers .config/mise/config.toml itself (the [tools]
# and [dotfiles] tables) by walking up from the current directory, not from
# MISE_DOTFILES_ROOT, so running this script from outside the repo without
# the `cd` would silently find no config at all.
export MISE_DOTFILES_ROOT="$REPO_DIR"

# Pretty output helpers — use gum (charmbracelet) when available, otherwise
# plain echo. Helpers re-check `command -v gum` at call time so they work
# even if gum appears mid-run (after we install it FIRST below).
_has_gum() { command -v gum >/dev/null 2>&1; }
_gum_style() {
  if _has_gum; then
    gum style --border rounded --border-foreground 212 --padding "0 1" --margin "0 0 1 0" --bold "$@"
  else
    printf '━━ %s ━━\n' "$*"
  fi
}
_gum_log() {
  # $1 = level (info/error/warn), $2 = message
  if _has_gum; then
    gum log --level "$1" "$2"
  else
    printf 'init.sh: [%s] %s\n' "$1" "$2" >&2
  fi
}

# Ensure mise is available even on a truly fresh system where ~/.local/bin
# is not yet on PATH and mise has never been installed. Check the absolute
# location first so a reboot-fresh fish shell with a system-only PATH still
# finds it, then auto-install via the official installer if truly missing.
if ! command -v mise >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/mise" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  elif [ -x "/home/linuxbrew/.linuxbrew/bin/mise" ]; then
    export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"
  fi
fi
if ! command -v mise >/dev/null 2>&1; then
  _gum_log warn "mise not found, installing to ~/.local/bin/mise via https://mise.run ..."
  # Official installer respects MISE_INSTALL_PATH; default is ~/.local/bin/mise
  curl -fsSL https://mise.run | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v mise >/dev/null 2>&1; then
  _gum_log error "mise is still not installed after auto-install; install it manually, then re-run this script"
  exit 1
fi

# Install gum FIRST so even the first real step is pretty. On a fresh
# machine gum is not yet on PATH until after `mise install`, but `gum` is
# tiny (prebuilt binary, <10s) and defined in .config/mise/config.toml, so we
# can pull it alone before the heavy `mise install` of everything else. If
# this fails (no network), we fall back to plain echo for the rest.
if ! _has_gum; then
  printf '→ Installing gum for pretty output…\n' >&2
  mise install gum 2>&1 | tail -n 5 || true
fi
# mise shims may not be on PATH in this bash yet; add them explicitly. Later
# steps need tools from them too (jq for the task list below).
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"

# Every step below records its outcome instead of aborting the script, so
# one broken step (a flaky network fetch, a task that needs a human) never
# hides how the rest went. The report at the bottom is built from these
# arrays, and every step's full output lands in LOG_DIR.
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/init/$(date +%Y%m%dT%H%M%S)"
mkdir -p "$LOG_DIR"
R_NAME=()
R_STATUS=() # ok | failed | skipped
R_SECS=()
R_NOTE=()
_record() { # name status secs note
  R_NAME+=("$1")
  R_STATUS+=("$2")
  R_SECS+=("$3")
  R_NOTE+=("$4")
}
_fmt_secs() {
  if (($1 >= 60)); then printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); else printf '%ds' "$1"; fi
}

# Run a quiet step under a spinner, full output to its own log file. On
# failure, show the log's tail right away so the cause is on screen.
_step() { # name title cmd...
  local name="$1" title="$2"
  shift 2
  local log="$LOG_DIR/$name.log" start=$SECONDS rc=0
  if _has_gum; then
    gum spin --title "$title" -- bash -c '"$@" >"$0" 2>&1' "$log" "$@" || rc=$?
  else
    printf '→ %s\n' "$title" >&2
    "$@" >"$log" 2>&1 || rc=$?
  fi
  local secs=$((SECONDS - start))
  if ((rc == 0)); then
    _record "$name" ok "$secs" ""
    _gum_log info "✔ $name ($(_fmt_secs "$secs"))"
  else
    _record "$name" failed "$secs" "exit $rc, see $log"
    _gum_log error "✘ $name failed (exit $rc), last lines of $log:"
    tail -n 15 "$log" >&2
  fi
  return "$rc"
}

_gum_style "dotfiles bootstrap"

_step submodules "Initializing submodules (incl. mise-en-system)…" git submodule update --init --recursive || true
_step dotfiles "Applying dotfiles (mise bootstrap dotfiles apply)…" mise bootstrap dotfiles apply --yes || true
_step tools "Installing mise tools (this may take a minute)…" mise install || true

# Install/bootstrap tasks live in jeremysball/mise-en-system rather than in
# this repo's own [tasks] table (see the comment at the top of
# .config/mise/config.toml for why). It is checked out as the
# mise-en-system/ submodule, so the submodule step above already synced it.
MISE_SYSTEM_DIR="$REPO_DIR/mise-en-system"

if [ -f "$MISE_SYSTEM_DIR/mise.toml" ]; then
  # Trusting a config mise has already trusted is a no-op, so this is
  # safe on every run. Install mise-en-system's own [tools] up front rather
  # than letting the first task trigger an on-demand install: a failed
  # on-demand install would abort a task partway through instead of
  # failing cleanly here.
  _step system-tools "Installing mise-en-system tools…" \
    bash -c 'mise trust -q "$1/mise.toml" && mise -C "$1" install' _ "$MISE_SYSTEM_DIR" || true

  # Enumerate instead of naming tasks, so a task added to mise-en-system
  # runs here with no edit to this file. Filtering on `source` keeps out
  # tasks mise also picks up from this repo's own config while walking up
  # from mise-en-system/. Hidden tasks (`hide = true`) are omitted by
  # `tasks ls`: that is mise-en-system's marker for "never unattended".
  # A failed listing is recorded rather than read as "no tasks": an empty
  # report row set would look like a clean run.
  TASK_LINES=()
  HIDDEN_TASKS=()
  # jq output goes through variables, not `mapfile < <(jq ...)`: process
  # substitution drops jq's exit status, so a jq error would silently cut
  # the task list short.
  enum_log="$LOG_DIR/enumerate-tasks.log"
  jq_src=(--arg src "$MISE_SYSTEM_DIR/mise.toml")
  if tasks_json="$(mise -C "$MISE_SYSTEM_DIR" tasks ls --local --hidden --json 2>"$enum_log")" &&
    jq -e 'type == "array"' >/dev/null 2>>"$enum_log" <<<"$tasks_json" &&
    visible="$(jq -r "${jq_src[@]}" \
      '.[] | select(.source == $src and (.hide | not)) | "\(.name)\t\(.depends | map(tostring) | join(" "))"' \
      2>>"$enum_log" <<<"$tasks_json")" &&
    hidden="$(jq -r "${jq_src[@]}" '.[] | select(.source == $src and .hide) | .name' 2>>"$enum_log" <<<"$tasks_json")"; then
    [ -n "$visible" ] && mapfile -t TASK_LINES <<<"$visible"
    [ -n "$hidden" ] && mapfile -t HIDDEN_TASKS <<<"$hidden"
  else
    _record enumerate-tasks failed 0 "could not list mise-en-system tasks, see $LOG_DIR/enumerate-tasks.log"
  fi

  # Order by `depends` (Kahn's algorithm, ties in listing order). Each task
  # then runs alone with --skip-deps, so a shared dependency like
  # install-secrets runs once instead of once per dependent.
  declare -A DEPS=()
  ALL_TASKS=()
  for line in "${TASK_LINES[@]}"; do
    ALL_TASKS+=("${line%%$'\t'*}")
    DEPS["${line%%$'\t'*}"]="${line#*$'\t'}"
  done
  ORDER=()
  declare -A PLACED=()
  progress=1
  while ((${#ORDER[@]} < ${#ALL_TASKS[@]})) && ((progress)); do
    progress=0
    for t in "${ALL_TASKS[@]}"; do
      [ -n "${PLACED[$t]:-}" ] && continue
      ready=1
      for d in ${DEPS[$t]}; do
        # A dependency outside the list (hidden) cannot be ordered against.
        if [ -n "${DEPS[$d]+x}" ] && [ -z "${PLACED[$d]:-}" ]; then ready=0; fi
      done
      if ((ready)); then
        ORDER+=("$t")
        PLACED[$t]=1
        progress=1
      fi
    done
  done
  for t in "${ALL_TASKS[@]}"; do
    if [ -z "${PLACED[$t]:-}" ]; then
      _record "$t" failed 0 "dependency cycle in mise-en-system depends"
    fi
  done

  # Tasks stream their output instead of hiding behind a spinner: several
  # use sudo or may ask questions, and a prompt under a spinner is an
  # invisible hang. `script` gives each task a real terminal while still
  # logging it; a `| tee` pipe would take the TTY away, and without --raw
  # mise doesn't connect the task's stdin at all.
  declare -A TASK_STATUS=()
  i=0
  for t in "${ORDER[@]}"; do
    i=$((i + 1))
    blocked=""
    for d in ${DEPS[$t]}; do
      if [ "${TASK_STATUS[$d]:-}" = failed ] || [ "${TASK_STATUS[$d]:-}" = skipped ]; then blocked="$d"; fi
    done
    if [ -n "$blocked" ]; then
      # Same rule mise applies itself: a dependent never runs after its
      # dependency failed.
      TASK_STATUS[$t]=skipped
      _record "$t" skipped 0 "dependency $blocked did not succeed"
      _gum_log warn "⊘ $t skipped: dependency $blocked did not succeed"
      continue
    fi
    if _has_gum; then
      gum style --foreground 212 --bold "▸ [$i/${#ORDER[@]}] $t"
    else
      printf '▸ [%d/%d] %s\n' "$i" "${#ORDER[@]}" "$t"
    fi
    log="$LOG_DIR/task-$t.log"
    start=$SECONDS
    rc=0
    script -qefc "$(printf '%q ' mise -C "$MISE_SYSTEM_DIR" run --raw --skip-deps "$t")" "$log" || rc=$?
    secs=$((SECONDS - start))
    if ((rc == 0)); then
      TASK_STATUS[$t]=ok
      _record "$t" ok "$secs" ""
      _gum_log info "✔ $t ($(_fmt_secs "$secs"))"
    else
      TASK_STATUS[$t]=failed
      _record "$t" failed "$secs" "exit $rc, see $log"
      _gum_log error "✘ $t failed (exit $rc)"
    fi
  done
else
  HIDDEN_TASKS=()
  _record mise-en-system skipped 0 "$MISE_SYSTEM_DIR/mise.toml missing, submodule step did not check it out"
fi

# Weekly mise auto-upgrade (bump script), best-effort. On WSL without
# systemd there is nothing to enable; on a real Arch host it enables the
# timer that was just symlinked via `mise bootstrap dotfiles apply` above.
if systemctl --user list-units >/dev/null 2>&1; then
  _step upgrade-timer "Enabling weekly mise upgrade timer…" \
    bash -c 'systemctl --user daemon-reload && systemctl --user enable --now mise-upgrade.timer' || true
else
  _record upgrade-timer skipped 0 "no systemd user instance; enable later: systemctl --user enable --now mise-upgrade.timer"
fi

# Report. A markdown table through `gum format` when gum is around, aligned
# plain text otherwise. Exit status is 1 if anything failed, so a caller
# (or CI) can tell a partial bootstrap from a clean one.
n_ok=0 n_failed=0 n_skipped=0
for s in "${R_STATUS[@]}"; do
  case "$s" in
  ok) n_ok=$((n_ok + 1)) ;;
  failed) n_failed=$((n_failed + 1)) ;;
  skipped) n_skipped=$((n_skipped + 1)) ;;
  esac
done

report="## Bootstrap report

| | Step | Time | Notes |
|---|---|---|---|
"
for idx in "${!R_NAME[@]}"; do
  case "${R_STATUS[$idx]}" in
  ok) icon="✔" ;;
  failed) icon="✘" ;;
  *) icon="⊘" ;;
  esac
  report+="| $icon | \`${R_NAME[$idx]}\` | $(_fmt_secs "${R_SECS[$idx]}") | ${R_NOTE[$idx]} |
"
done
report+="
**$n_ok ok, $n_failed failed, $n_skipped skipped.** Full logs: \`$LOG_DIR\`
"
if ((${#HIDDEN_TASKS[@]})); then
  report+="
Not run (hidden in mise-en-system, manual only): $(printf '`%s` ' "${HIDDEN_TASKS[@]}"). Run one with \`mise-sys <task>\`.
"
fi
report+="
### Next steps

1. Run **\`secrets-unlock\`** (needs a real terminal, one pinentry prompt).
2. **\`exec fish\`** to switch shells.
3. Export \`SERPER_API_KEY\` before running \`serper-axi\`.
"
if ((n_failed)); then
  report+="4. Fix the failed steps above (each log path is in its row), then re-run \`./init.sh\`. Every step is idempotent, so a re-run only redoes what is missing.
"
fi

echo
if _has_gum; then
  gum format --type markdown <<<"$report"
else
  # Strip the markdown table syntax into aligned columns.
  printf 'init.sh: bootstrap report\n'
  for idx in "${!R_NAME[@]}"; do
    printf '  %-8s %-28s %7s  %s\n' "${R_STATUS[$idx]}" "${R_NAME[$idx]}" "$(_fmt_secs "${R_SECS[$idx]}")" "${R_NOTE[$idx]}"
  done
  printf '\n%d ok, %d failed, %d skipped. Full logs: %s\n' "$n_ok" "$n_failed" "$n_skipped" "$LOG_DIR"
  if ((${#HIDDEN_TASKS[@]})); then
    printf 'Not run (hidden, manual only): %s. Run one with mise-sys <task>.\n' "${HIDDEN_TASKS[*]}"
  fi
  printf "Next: run 'secrets-unlock' (real terminal, one pinentry prompt), then 'exec fish'. Export SERPER_API_KEY before running serper-axi.\n"
fi

((n_failed == 0))

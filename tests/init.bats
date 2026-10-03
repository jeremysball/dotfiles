#!/usr/bin/env bats
# Regression tests for init.sh's task runner and report.
#
# Each test copies init.sh into a throwaway git repo next to a stub
# mise-en-system/mise.toml, then runs it with:
#   - HOME and XDG_STATE_HOME pointed into the sandbox,
#   - a `mise` stub that no-ops `bootstrap` and `install` (so nothing touches
#     real dotfiles or downloads tools) and passes everything else through,
#   - a `systemctl` stub that fails, so the timer step records "skipped",
#   - gum removed from PATH, so output takes the plain-printf branch and the
#     assertions don't depend on gum's table wrapping. One test puts it back.
#
# Run with `mise run test`, which provides bats, jq, and gum. INIT_SH
# overrides which init.sh is under test, e.g. to confirm a test goes red
# against an older revision:
#   git show <rev>:init.sh >/tmp/old-init.sh && INIT_SH=/tmp/old-init.sh mise run test

# Writes stdin to an executable in the sandbox's bin, which is first on PATH.
stub() {
  cat >"$SANDBOX/bin/$1"
  chmod +x "$SANDBOX/bin/$1"
}

setup() {
  SANDBOX="$BATS_TEST_TMPDIR"
  REPO="$SANDBOX/repo"
  mkdir -p "$REPO/mise-en-system" "$SANDBOX/bin" "$SANDBOX/home" "$SANDBOX/state"
  cp "${INIT_SH:-$BATS_TEST_DIRNAME/../init.sh}" "$REPO/init.sh"
  git -C "$REPO" init -q

  # Stubs reach the real tools through these.
  REAL_MISE="$(command -v mise)"
  REAL_JQ="$(command -v jq)"
  export REAL_MISE REAL_JQ

  # MISE_STUB_FAIL=<word> fails any mise call with that argument
  # (`bootstrap` for the dotfiles step, `tasks` for the task listing).
  # MISE_STUB_TASKS_JSON replaces what `mise tasks ls` prints.
  stub mise <<'SH'
#!/usr/bin/env bash
if [ -n "${MISE_STUB_FAIL:-}" ] && [[ " $* " == *" $MISE_STUB_FAIL "* ]]; then
  echo "mise: simulated $MISE_STUB_FAIL failure" >&2
  exit 3
fi
if [ -n "${MISE_STUB_TASKS_JSON:-}" ] && [[ " $* " == *" tasks ls "* ]]; then
  printf '%s\n' "$MISE_STUB_TASKS_JSON"
  exit 0
fi
for a in "$@"; do case "$a" in bootstrap | install) exit 0 ;; esac; done
exec "$REAL_MISE" "$@"
SH
  stub systemctl <<'SH'
#!/bin/sh
exit 1
SH

  local dir path=""
  GUM_DIR=""
  IFS=: read -ra dirs <<<"$PATH"
  for dir in "${dirs[@]}"; do
    if [ -x "$dir/gum" ]; then
      GUM_DIR="${GUM_DIR:-$dir}"
    else
      path+="${path:+:}$dir"
    fi
  done

  # Tools stay where they're installed; only trust state and HOME move.
  export MISE_DATA_DIR="${MISE_DATA_DIR:-$HOME/.local/share/mise}"
  export MISE_CACHE_DIR="${MISE_CACHE_DIR:-$HOME/.cache/mise}"
  export MISE_STATE_DIR="$SANDBOX/mise-state"
  export MISE_TRUSTED_CONFIG_PATHS="$SANDBOX"
  export HOME="$SANDBOX/home"
  export XDG_STATE_HOME="$SANDBOX/state"
  export PATH="$SANDBOX/bin:$path"
}

tasks() { cat >"$REPO/mise-en-system/mise.toml"; }

one_task() {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
TOML
}

# Whole-line match. mise echoes each task's command line before running it
# ("[a] $ echo RAN-a"), so a substring match would pass on that echo alone
# even when the task never printed anything.
has_line() { grep -qxF "$1" <<<"$output"; }
# A function, not `! has_line`: bats only fails a test on a negated command
# when it's the test's last line.
lacks_line() { ! grep -qxF "$1" <<<"$output"; }
# Number of output lines matching an extended regex.
count_matching() { grep -cE "$1" <<<"$output" || true; }

# Runs init.sh from DIR (default: the sandbox repo) with no stdin, through
# bats' `run`, so $status is its exit code. $output and $lines come back
# with ANSI escapes and carriage returns (from script's pty) stripped.
run_init() {
  run bash "${1:-$REPO}/init.sh" </dev/null
  output="$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' <<<"$output")"
  mapfile -t lines <<<"$output"
}

@test "a clean run executes every task, reports every step, and exits 0" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
[tasks.b]
depends = ["a"]
run = 'echo RAN-b'
TOML
  run_init
  has_line RAN-a
  has_line RAN-b
  [ "$(count_matching '^  ok +(submodules|dotfiles|tools|system-tools|a|b) +[0-9]+s  $')" -eq 6 ]
  [ "$(count_matching '^  skipped +upgrade-timer +0s  no systemd user instance')" -eq 1 ]
  logdir="$(sed -n 's/^6 ok, 0 failed, 1 skipped\. Full logs: //p' <<<"$output")"
  [[ "$logdir" == "$XDG_STATE_HOME/dotfiles/init/"* ]]
  [ -s "$logdir/task-b.log" ]
  [ "$status" -eq 0 ]
}

@test "runs tasks when init.sh is invoked through a symlinked checkout" {
  one_task
  ln -s "$REPO" "$SANDBOX/link"
  run_init "$SANDBOX/link"
  has_line RAN-a
}

@test "tasks get a terminal on stdin and stdout" {
  tasks <<'TOML'
[tasks.a]
run = 'if [ -t 0 ] && [ -t 1 ]; then echo TTY-YES; else echo TTY-NO; fi'
TOML
  run_init
  has_line TTY-YES
}

@test "a task whose dependency failed is skipped, and the run exits 1" {
  tasks <<'TOML'
[tasks.b]
run = 'echo RAN-b; exit 7'
[tasks.c]
depends = ["b"]
run = 'echo RAN-c'
TOML
  run_init
  # Prove b ran before asserting c didn't.
  has_line RAN-b
  lacks_line RAN-c
  [[ "$output" == *"c skipped: dependency b did not succeed"* ]]
  [ "$status" -eq 1 ]
}

@test "a failed task prints the tail of its log" {
  tasks <<'TOML'
[tasks.b]
run = 'echo CAUSE-LINE; exit 7'
TOML
  run_init
  [[ "$output" == *"b failed (exit "*"), last lines of "*"/task-b.log:"* ]]
  # Once streamed live, once more from the log tail.
  [ "$(count_matching '^CAUSE-LINE$')" -ge 2 ]
}

@test "a failed setup step is recorded with its log tail, and the run continues" {
  one_task
  export MISE_STUB_FAIL=bootstrap
  run_init
  [[ "$output" == *"dotfiles failed (exit 3), last lines of "*"/dotfiles.log:"* ]]
  has_line "mise: simulated bootstrap failure"
  [ "$(count_matching '^  failed +dotfiles +[0-9]+s  exit 3, see .*/dotfiles\.log$')" -eq 1 ]
  has_line RAN-a
  [ "$status" -eq 1 ]
}

@test "a dependency cycle names its members and skips what depends on it" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
[tasks.x]
depends = ["y"]
run = 'echo RAN-x'
[tasks.y]
depends = ["x"]
run = 'echo RAN-y'
[tasks.z]
depends = ["x"]
run = 'echo RAN-z'
TOML
  run_init
  has_line RAN-a
  lacks_line RAN-x
  lacks_line RAN-y
  lacks_line RAN-z
  [ "$(count_matching '^  failed +[xy] .* dependency cycle among: x y$')" -eq 2 ]
  [ "$(count_matching '^  skipped +z .* depends on the dependency cycle among: x y$')" -eq 1 ]
  [ "$status" -eq 1 ]
}

@test "two separate dependency cycles are reported separately" {
  tasks <<'TOML'
[tasks.p]
depends = ["q"]
run = 'echo RAN-p'
[tasks.q]
depends = ["p"]
run = 'echo RAN-q'
[tasks.w]
depends = ["p", "x"]
run = 'echo RAN-w'
[tasks.x]
depends = ["y"]
run = 'echo RAN-x'
[tasks.y]
depends = ["x"]
run = 'echo RAN-y'
TOML
  run_init
  [ "$(count_matching '^  failed +[pq] .* dependency cycle among: p q$')" -eq 2 ]
  [ "$(count_matching '^  failed +[xy] .* dependency cycle among: x y$')" -eq 2 ]
  [ "$(count_matching '^  skipped +w .* depends on the dependency cycles among: p q; x y$')" -eq 1 ]
  [ "$status" -eq 1 ]
}

@test "hidden tasks never run, and neither do tasks that depend on them" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
[tasks.h]
hide = true
run = 'echo RAN-h'
[tasks.v]
depends = ["h"]
run = 'echo RAN-v'
TOML
  run_init
  has_line RAN-a
  lacks_line RAN-h
  lacks_line RAN-v
  [ "$(count_matching '^  skipped +v +0s  depends on hidden task h, which never runs unattended$')" -eq 1 ]
  has_line "Not run (hidden, manual only): h. Run one with mise-sys <task>."
  [ "$status" -eq 0 ]
}

@test "a missing mise-en-system checkout is reported as skipped, not failed" {
  # No tasks file: the submodule step left mise-en-system/ empty.
  run_init
  [ "$(count_matching '^  skipped +mise-en-system +0s  .*/mise-en-system/mise\.toml missing')" -eq 1 ]
  [ "$status" -eq 0 ]
}

@test "with systemd available, the upgrade timer is reloaded and enabled" {
  one_task
  export SYSTEMCTL_LOG="$SANDBOX/systemctl.log"
  stub systemctl <<'SH'
#!/bin/sh
echo "$*" >>"$SYSTEMCTL_LOG"
SH
  run_init
  grep -qxF -e "--user daemon-reload" "$SYSTEMCTL_LOG"
  grep -qxF -e "--user enable --now mise-upgrade.timer" "$SYSTEMCTL_LOG"
  [ "$(count_matching '^  ok +upgrade-timer ')" -eq 1 ]
  [ "$status" -eq 0 ]
}

@test "two runs started in the same second get separate log directories" {
  one_task
  REAL_DATE="$(command -v date)"
  export REAL_DATE
  stub date <<'SH'
#!/usr/bin/env bash
[ "$1" = +%Y%m%dT%H%M%S ] && { echo 20260101T000000; exit 0; }
exec "$REAL_DATE" "$@"
SH
  run_init
  run_init
  run ls "$XDG_STATE_HOME/dotfiles/init"
  [ "${#lines[@]}" -eq 2 ]
  for d in "${lines[@]}"; do
    [ -s "$XDG_STATE_HOME/dotfiles/init/$d/task-a.log" ]
  done
}

# Each listing failure must be recorded, not read as an empty task list.
assert_enumeration_recorded() {
  lacks_line RAN-a
  [ "$(count_matching '^  failed +enumerate-tasks +0s  could not list mise-en-system tasks, see .*/enumerate-tasks\.log$')" -eq 1 ]
  [ "$status" -eq 1 ]
}

# Fails only the jq call whose arguments contain $1; every other call works.
fail_jq_matching() {
  export JQ_STUB_FAIL="$1"
  stub jq <<'SH'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *"$JQ_STUB_FAIL"*) echo "jq: simulated error" >&2; exit 5 ;; esac
done
exec "$REAL_JQ" "$@"
SH
}

@test "a failing 'mise tasks ls' is recorded instead of running nothing" {
  one_task
  export MISE_STUB_FAIL=tasks
  run_init
  assert_enumeration_recorded
}

@test "a task listing that isn't a JSON array is recorded instead of running nothing" {
  one_task
  # {} passes every later query as an empty list; only the array check
  # stops it from reading as "no tasks".
  export MISE_STUB_TASKS_JSON='{}'
  run_init
  assert_enumeration_recorded
}

@test "a jq error in the runnable-task query is recorded instead of running nothing" {
  one_task
  fail_jq_matching '(.hide | not)'
  run_init
  assert_enumeration_recorded
}

@test "a jq error in the hidden-task query is recorded instead of running nothing" {
  one_task
  fail_jq_matching 'and .hide)'
  run_init
  assert_enumeration_recorded
}

@test "with gum on PATH, steps, task logs, and the report go through gum" {
  [ -n "$GUM_DIR" ] || skip "gum not on PATH (mise run test provides it)"
  one_task
  export PATH="$GUM_DIR:$PATH"
  # A failing step proves gum spin passes the exit code and the log through.
  export MISE_STUB_FAIL=bootstrap
  run_init
  has_line RAN-a
  [[ "$output" == *"dotfiles failed (exit 3), last lines of "*"/dotfiles.log:"* ]]
  has_line "mise: simulated bootstrap failure"
  [[ "$output" == *"Bootstrap report"* ]]
  [[ "$output" == *"4 ok, 1 failed, 1 skipped."* ]]
  # gum format, not the plain-text fallback, rendered the report.
  lacks_line "init.sh: bootstrap report"
  [ "$status" -eq 1 ]
}

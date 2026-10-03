#!/usr/bin/env bats
# Regression tests for init.sh's task runner and report.
#
# Each test copies init.sh into a throwaway git repo next to a stub
# mise-en-system/mise.toml, then runs it with:
#   - HOME and XDG_STATE_HOME pointed into the sandbox,
#   - a `mise` shim that no-ops `bootstrap` and `install` (so nothing touches
#     real dotfiles or downloads tools) and passes everything else through,
#   - a `systemctl` shim that fails, so the timer step records "skipped",
#   - gum removed from PATH, so output takes the plain-printf branch and the
#     assertions don't depend on gum's table wrapping.
#
# INIT_SH overrides which init.sh is under test, e.g. to confirm a test goes
# red against an older revision:
#   git show <rev>:init.sh >/tmp/old-init.sh && INIT_SH=/tmp/old-init.sh bats tests

setup() {
  SANDBOX="$BATS_TEST_TMPDIR"
  REPO="$SANDBOX/repo"
  mkdir -p "$REPO/mise-en-system" "$SANDBOX/bin" "$SANDBOX/home" "$SANDBOX/state"
  cp "${INIT_SH:-$BATS_TEST_DIRNAME/../init.sh}" "$REPO/init.sh"
  git -C "$REPO" init -q

  local real_mise
  real_mise="$(command -v mise)"
  printf '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in bootstrap | install) exit 0 ;; esac; done\nexec %q "$@"\n' \
    "$real_mise" >"$SANDBOX/bin/mise"
  printf '#!/bin/sh\nexit 1\n' >"$SANDBOX/bin/systemctl"
  chmod +x "$SANDBOX/bin/"*

  local dir path=""
  IFS=: read -ra dirs <<<"$PATH"
  for dir in "${dirs[@]}"; do
    [ -x "$dir/gum" ] || path+="${path:+:}$dir"
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

# Whole-line match. mise echoes each task's command line before running it
# ("[a] $ echo RAN-a"), so a substring match would pass on that echo alone
# even when the task never printed anything.
has_line() { grep -qxF "$1" <<<"$output"; }
# A function, not `! has_line`: bats only fails a test on a negated command
# when it's the test's last line.
lacks_line() { ! grep -qxF "$1" <<<"$output"; }

# Runs init.sh from DIR (default: the sandbox repo) with no stdin. Output
# has ANSI escapes and carriage returns (from script's pty) stripped, and
# init.sh's own exit status lands in INIT_RC.
run_init() {
  local raw rc=0
  raw="$(bash "${1:-$REPO}/init.sh" </dev/null 2>&1)" || rc=$?
  output="$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' <<<"$raw")"
  INIT_RC=$rc
}

@test "a clean run executes every task and exits 0" {
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
  [ "$INIT_RC" -eq 0 ]
}

@test "runs tasks when init.sh is invoked through a symlinked checkout" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
TOML
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
  [ "$INIT_RC" -eq 1 ]
}

@test "a failed task prints the tail of its log" {
  tasks <<'TOML'
[tasks.b]
run = 'echo CAUSE-LINE; exit 7'
TOML
  run_init
  [[ "$output" == *"b failed (exit "*"), last lines of "*"/task-b.log:"* ]]
  # Once streamed live, once more from the log tail.
  [ "$(grep -c '^CAUSE-LINE$' <<<"$output")" -ge 2 ]
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
  [ "$(grep -cE '^  failed +[xy] .* dependency cycle among: x y$' <<<"$output")" -eq 2 ]
  [ "$(grep -cE '^  skipped +z .* depends on the dependency cycle among: x y$' <<<"$output")" -eq 1 ]
  [ "$INIT_RC" -eq 1 ]
}

@test "two runs started in the same second get separate log directories" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
TOML
  printf '#!/usr/bin/env bash\n[ "$1" = +%%Y%%m%%dT%%H%%M%%S ] && { echo 20260101T000000; exit 0; }\nexec %q "$@"\n' \
    "$(command -v date)" >"$SANDBOX/bin/date"
  chmod +x "$SANDBOX/bin/date"
  run_init
  run_init
  run ls "$XDG_STATE_HOME/dotfiles/init"
  [ "${#lines[@]}" -eq 2 ]
  for d in "${lines[@]}"; do
    [ -s "$XDG_STATE_HOME/dotfiles/init/$d/task-a.log" ]
  done
}

@test "a jq error while listing tasks is recorded instead of running nothing" {
  tasks <<'TOML'
[tasks.a]
run = 'echo RAN-a'
TOML
  # Fail only the query that lists runnable tasks; every other jq call works.
  printf '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in *"(.hide | not)"*) echo "jq: simulated error" >&2; exit 5 ;; esac; done\nexec %q "$@"\n' \
    "$(command -v jq)" >"$SANDBOX/bin/jq"
  chmod +x "$SANDBOX/bin/jq"
  run_init
  lacks_line RAN-a
  [[ "$output" == *"enumerate-tasks"*"could not list mise-en-system tasks"* ]]
  [ "$INIT_RC" -eq 1 ]
}

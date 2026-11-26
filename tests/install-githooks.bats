#!/usr/bin/env bats

setup() {
  command -v realpath >/dev/null || skip "the generated shim requires realpath"
  command -v timeout >/dev/null || skip "the recursion tests bound themselves with GNU timeout"
  export HOME="$BATS_TEST_TMPDIR/home" XDG_CONFIG_HOME="$BATS_TEST_TMPDIR/config"
  export REPO="$BATS_TEST_TMPDIR/repo" LOG="$BATS_TEST_TMPDIR/log"
  mkdir -p "$HOME" "$XDG_CONFIG_HOME/git/hooks" "$REPO/.githooks" "$BATS_TEST_TMPDIR/bin"
  git -C "$REPO" init -q
  cat > "$REPO/.githooks/pre-commit" <<'SH'
#!/usr/bin/env bash
printf 'local:%s:%s\n' "$GIT_HOOKS_CHAINED" "$1" >> "$LOG"
SH
  cat > "$XDG_CONFIG_HOME/git/hooks/pre-commit" <<'SH'
#!/usr/bin/env bash
printf 'global:%s:%s\n' "$GIT_HOOKS_CHAINED" "$1" >> "$LOG"
SH
  chmod +x "$XDG_CONFIG_HOME/git/hooks/pre-commit"
  bash "$BATS_TEST_DIRNAME/../scripts/install-githooks.sh" "$REPO"
  export REAL_REALPATH="$(command -v realpath)"
  cat > "$BATS_TEST_TMPDIR/bin/realpath" <<'SH'
#!/usr/bin/env bash
case "${FAIL_RESOLUTION:-}:$1" in
  self:.githooks/pre-commit|self:*/.githooks/pre-commit|candidate:*/.githooks/pre-commit.local) exit 1 ;;
esac
exec "$REAL_REALPATH" "$@"
SH
  chmod +x "$BATS_TEST_TMPDIR/bin/realpath"
  export PATH="$BATS_TEST_TMPDIR/bin:$PATH"
}

@test "failed self resolution blocks the hook" {
  export FAIL_RESOLUTION=self
  run bash -c 'cd "$REPO" && .githooks/pre-commit arg'
  [ "$status" -ne 0 ]
}

@test "failed candidate resolution blocks after the global hook" {
  export FAIL_RESOLUTION=candidate
  run bash -c 'cd "$REPO" && .githooks/pre-commit arg'
  [ "$(cat "$LOG")" = 'global:1:arg' ]
  [ "$status" -ne 0 ]
}

@test "normal chaining runs global and local hooks with arguments" {
  run bash -c 'cd "$REPO" && .githooks/pre-commit arg'
  [ "$status" -eq 0 ]
  [ "$(cat "$LOG")" = $'global:1:arg\nlocal:1:arg' ]
}

@test "self-referencing candidate is skipped without recursion" {
  rm "$REPO/.githooks/pre-commit.local"
  ln -s pre-commit "$REPO/.githooks/pre-commit.local"
  run timeout 5 bash -c 'cd "$REPO" && .githooks/pre-commit arg'
  [ "$status" -eq 0 ]
  [ "$(cat "$LOG")" = 'global:1:arg' ]
}

# The .local case above terminates by accident: re-entry changes the basename
# to pre-commit.local. The hooks/ alt path keeps the basename, so only the
# realpath self-check stops it. Without that check this test times out.
@test "self-referencing alt candidate is skipped without recursion" {
  rm "$REPO/.githooks/pre-commit.local"
  mkdir -p "$REPO/hooks"
  ln -s ../.githooks/pre-commit "$REPO/hooks/pre-commit"
  run timeout 5 bash -c 'cd "$REPO" && .githooks/pre-commit arg'
  [ "$status" -eq 0 ]
  [ "$(cat "$LOG")" = 'global:1:arg' ]
}

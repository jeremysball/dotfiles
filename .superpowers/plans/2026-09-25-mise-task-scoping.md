# Mise Task Scoping and Bootstrap Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` through taskferry, or `superpowers:executing-plans` for inline execution. Complete the checkboxes task by task.

**Goal:** Keep dotfiles-specific Mise tasks out of Mise's global task list and make initial system bootstrap use one ordered task from `mise-en-system`.

**Architecture:** Keep `[tools]`, `[settings]`, `[bootstrap.repos]`, and `[dotfiles]` in `.config/mise/config.toml`. Move the seven dotfiles-owned tasks into a root `.mise.toml`, preserving `install-worktree-githooks` as the only intentional global task. Add an ordered `bootstrap` aggregate to `mise-en-system` and have `init.sh` call it.

**Tech Stack:** mise 2026.9.12, TOML, Bash, fish.

**Spec:** Source requirements in `.config/mise/config.toml:19-32,127-133,335-547`, `TODO.md`, `init.sh:97-115`, and `README.md:21-34`.

## Global Constraints

- Never run every local task during bootstrap. The system repository contains unrelated package, service, and maintenance installers.
- Preserve the existing setup order, then run `install-emacs` and `install-fortune` as part of bootstrap.
- Remove the `install-bifrost` task definition and all references to that task from `mise-en-system`.
- Keep `mise-sys secrets-sync` as the secret-refresh command. Bootstrap continues to use `install-secrets` only for initial setup.
- Keep `install-worktree-githooks` globally callable unless the owner changes that requirement.
- Invoke dotfiles-local tasks with `mise -C "$DOTFILES_ROOT" run <task>`.
- Use a dedicated worktree for each repository touched by implementation.

---

## Approach

Three options fit the bootstrap change. The static list ships fastest and is safe, but keeps two sources of truth. Dynamic task enumeration removes that duplication, but can run installers with unrelated system effects. A Mise aggregate adds one task and keeps the allow-list in the system-task repo. It adds no runtime dependency or custom parser, so use the aggregate.

Do not parse the output of `mise tasks --local --json` and run every result. The current local task list includes `install-doom-emacs`, `doom-emacs-extras`, and `secrets-sync`, which do not belong in initial bootstrap. `install-bifrost` is removed entirely.

## File Map

- Create `.mise.toml` in the dotfiles root for the seven repo-scoped tasks.
- Modify `.config/mise/config.toml` to remove those seven definitions and keep `install-worktree-githooks` global.
- Modify `mise-en-system/mise.toml` in its own worktree to add `bootstrap`, remove `install-bifrost`, and remove the duplicate global task.
- Modify `init.sh` to invoke `mise -C "$MISE_SYSTEM_DIR" run bootstrap`.
- Update `README.md`, task help and error text in `scripts/`, and task command examples in `.config/kilo/kilo.jsonc` and `.config/opencode/opencode.jsonc`.
- Remove the completed migration items from `TODO.md`.

## Tasks

### Task 1: Add the ordered system bootstrap task

**Files:** Modify `mise-en-system/mise.toml` in a dedicated worktree. Its local `main` is one commit behind `origin/main`.

- [ ] Run `git mainsync main` in the `mise-en-system` primary checkout. If it fast-forwards, branch from `main`. If it is blocked by local changes, leave them untouched and create the worktree from a freshly fetched `origin/main` as an explicit temporary base.
- [ ] Add this task with the current setup order:

```toml
[tasks.bootstrap]
description = "Run the initial system setup tasks in dependency order."
run = '''
mise run -j 1 \
  install-secrets ::: \
  install-dotclaude ::: \
  install-serper-axi ::: \
  install-emacs ::: \
  install-fortune
'''
```

- [ ] Remove the duplicate local `install-worktree-githooks` task so the global dotfiles definition remains canonical.
- [ ] Delete the complete `[tasks.install-bifrost]` definition from `mise-en-system/mise.toml`.
- [ ] Run `mise -C "$MISE_SYSTEM_DIR" tasks validate`. Expected: exit 0.
- [ ] Run `mise -C "$MISE_SYSTEM_DIR" run --dry-run bootstrap`. Expected: it shows `install-secrets`, `install-dotclaude`, `install-serper-axi`, `install-emacs`, then `install-fortune`, without running them.
- [ ] Confirm `mise -C "$MISE_SYSTEM_DIR" tasks --local --name-only` includes `bootstrap`, `install-emacs`, and `install-fortune`, but not `install-bifrost`.
- [ ] Run `rg -n "install-bifrost" "$MISE_SYSTEM_DIR"`. Expected: no matches.
- [ ] Commit as `feat(bootstrap): add ordered system bootstrap task`.

### Task 2: Switch `init.sh` to the aggregate

**Files:** Modify `init.sh`.

- [ ] Replace the three named tasks with:

```bash
_gum_spin "Running system bootstrap tasks..." mise -C "$MISE_SYSTEM_DIR" run bootstrap
```

- [ ] Keep `mise install` and the repository-sync steps in their current order.
- [ ] Remove the temporary task-enumeration comment.
- [ ] Run `bash -n init.sh`. Expected: exit 0.
- [ ] Do not execute `./init.sh` as a test. It installs tools, clones repositories, configures secrets, and changes user state.
- [ ] Commit as `refactor(bootstrap): delegate setup task order to mise-en-system`.

### Task 3: Scope dotfiles tasks to the repository

**Files:** Create `.mise.toml`; modify `.config/mise/config.toml`.

- [ ] Move these seven task definitions without changing their behavior: `check-adhd-themes`, `sync-fleet-skills`, `check-fleet-skills`, `check-mise-secrets`, `install-githooks`, `sync-git-bin`, and `check-claude-md`.
- [ ] Keep only `install-worktree-githooks` in the global `[tasks]` table.
- [ ] Resolve each task's script path from the selected dotfiles checkout. Preserve the `MISE_DOTFILES_ROOT` and `DOTFILES_ROOT` overrides, then fall back to `git rev-parse --show-toplevel`. This lets `mise -C` target the current linked worktree.
- [ ] Run `mise -C "$DOTFILES_ROOT" tasks validate`. Expected: exit 0.
- [ ] Confirm `mise -C "$DOTFILES_ROOT" tasks --local --name-only` lists all seven moved tasks.
- [ ] From the system-repository worktree, run `mise -C "$MISE_SYSTEM_DIR" tasks --global --name-only`. Expected: only `install-worktree-githooks` remains global.
- [ ] Commit as `refactor(mise): scope dotfiles tasks to the repository`.

### Task 4: Update task references and docs

**Files:** Modify `.mise.toml`, `README.md`, `scripts/sync-fleet-skills.sh`, `scripts/check-adhd-themes.sh`, `scripts/install-githooks.sh`, `scripts/git-lane`, `.config/kilo/kilo.jsonc`, and `.config/opencode/opencode.jsonc`.

- [ ] Document that dotfiles-local tasks run with `mise -C ~/.dotfiles run <task>`. In shell messages, use the resolved `DOTFILES_ROOT` variable.
- [ ] Update the moved task descriptions in `.mise.toml` to show the scoped invocation.
- [ ] Update the setup section to say `init.sh` invokes `mise-en-system`'s `bootstrap` task, which runs the five selected tasks in order.
- [ ] Keep `install-bifrost` out of the README and task documentation.
- [ ] Keep `mise-sys <task>` examples for `mise-en-system` tasks and preserve the `secrets-sync` guidance for secret refreshes.
- [ ] Search each moved task name with `rg` and verify no stale global invocation remains.
- [ ] Remove both completed migration items from `TODO.md`.
- [ ] Commit as `docs(mise): document scoped task invocation`.

### Task 5: Verify task visibility and bootstrap behavior

**Files:** No new files. Run checks from both repository worktrees.

- [ ] Run `mise -C "$DOTFILES_ROOT" tasks --local --name-only` and confirm the seven dotfiles tasks appear.
- [ ] Run `mise -C "$MISE_SYSTEM_DIR" tasks --local --name-only` and confirm `bootstrap` appears with the system tasks.
- [ ] Run `mise -C "$MISE_SYSTEM_DIR" run --dry-run bootstrap` and confirm all five tasks appear in order without execution.
- [ ] From outside the dotfiles directory, run `mise -C "$DOTFILES_ROOT" run check-adhd-themes`. Expected: it resolves its script in the selected checkout and exits 0.
- [ ] Run `bash -n "$DOTFILES_ROOT/init.sh"` and `mise tasks validate` in both repositories. Expected: all exit 0.
- [ ] Do not execute the bootstrap aggregate or any installer as verification. Use its dry run; this includes `install-emacs` and `install-fortune`.

## Open Decision

The dotfiles config says `install-worktree-githooks` must remain globally available. The current `mise-en-system` `origin/main` also adds a local definition of that task in commit `a345946`. This plan recommends keeping the global definition and removing the local duplicate. Confirm that choice before executing Task 1.

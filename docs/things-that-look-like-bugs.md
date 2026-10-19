# Things that look like bugs

Working-as-designed behavior that reads as broken. A real bug belongs in the
issue tracker; a shipped feature belongs in the release notes.

## The pre-commit primary-checkout gate does not fire in some repos

**What you will observe.** `~/.config/git/hooks/pre-commit` refuses commits
made from a repo's primary checkout, but in a handful of repos a commit lands
there with no complaint at all.

**Why it is deliberate.** Those repos carry `git config worktree.requireLinked
false`. Some repos are not worktree-shaped: a tool owns the repo and shells out
to `git commit` against the one checkout it knows about, so "make the change in
a linked worktree" is not advice anyone can act on. `pass` is the standing
example. Without a way to declare that once, the only route is bypassing on
every commit, and a bypass used that often is reflex rather than a decision,
which leaves the gate protecting nothing anywhere.

The opt-out is explicit rather than inferred on purpose. Auto-detecting it from
"this repo has no linked worktrees" would disable the gate for every repo until
someone happened to create a worktree, and that is the ordinary case the gate
exists to catch.

**When it becomes a real bug.** If a repo that does have a normal worktree
workflow carries the config key, or if the key is ever set globally rather than
per repo. Check with `git config --get worktree.requireLinked` in the repo, and
`git config --global --get worktree.requireLinked`, which should be empty.

### The exemption does not survive a fresh clone

`git config worktree.requireLinked false` writes to `.git/config`, which git
never tracks, so a re-clone of an exempt repo comes back with the gate on.
That is the same property every repo-local git setting has, not a bug in this
hook. For the pass store, mise-en-system's `exempt-tool-owned-repos` task
sets it again: init.sh runs it after `install-secrets` clones the store, and
`secrets-sync` runs it when it clones the store itself. It only exempts a repo
that has `.gpg-id` at its top level. Any other tool-owned repo needs its own
entry in that task. It would only become a real bug if the hook started
reading the key from a tracked file and still lost it.

## A SKIP_* variable does nothing anymore, and no blocked message offers one

**What you will observe.** `SKIP_DASH_CHECK=1 git commit`,
`SKIP_PRIMARY_CHECK=1 git commit`, `GIT_REQUIRE_LINKED_WORKTREE=0 git commit`,
and `SKIP_WORKTREE_BUDGET=1 git push` all behave exactly as if the variable
were unset. No gate prints `git commit --no-verify` as a suggestion either.
A gate blocks, and what it prints is how to fix the cause.

**Why it is deliberate.** Each of those variables used to return early, and two
of the three gates printed the variable in their own error text. A probe on
2026-10-11 handed six agents a routine commit task with no gate firing: three
reached for `SKIP_PRIMARY_CHECK` because the hook's own error had offered it,
and one set it defensively before anything had failed. A bypass that the error
message advertises is not a decision, it is a reflex, and a reflex stops
meaning anything. Removing the variable rather than hiding the message is what
makes that impossible: there is nothing left to reach for.

Turning a gate off is still possible where it is honestly off, and only there.
A repo a tool owns sets `git config worktree.requireLinked false` (the section
above). A repo that genuinely runs wide raises the worktree cap with
`worktree.maxOpen` or `GIT_MAX_WORKTREES`, which still evaluates the gate
instead of skipping it. Everything else is a worktree.

**When it becomes a real bug.** If any of those variables changes a gate's exit
code, if a blocked message names an escape hatch again, or if a gate blocks a
commit with no way to tell what to do next. `python3
scripts/check-hook-knobs.py` covers all three.

## The dash gate lets a dash through in code, but not in a comment

**What you will observe.** The pre-commit dash gate blocks an em dash or a
spaced double hyphen in a markdown file, a TOML file, or a shell comment, but
lets the same characters through in a shell command, a JSON string, or a CSS
class name. An em dash inside a Python string literal also passes.

**Why it is deliberate.** In code, a double hyphen is usually syntax: the
end-of-options marker after `gum spin` or fish's `string escape`, a BEM
modifier, a decrement. Checking whole lines blocked those, and the only way
past was a bypass, used often enough that it stopped meaning anything. So
`.config/git/hooks/dash-gate.py` asks ast-grep which parts of a code file are
comments and checks only those. Prose in a comment is still prose. A string
literal is not checked, because telling a user-facing string from a format
string or a test fixture needs more than a parser.

A file ast-grep cannot parse (markdown, TOML, an unknown extension) is checked
line by line, as before. Unknown means strict, never skipped.

**When it becomes a real bug.** If a comment with an em dash gets through, or
if a code file is checked line by line again. `python3
scripts/check-dash-gate.py` covers both directions.

## The first commit of a fish file pauses to compile something

**What you will observe.** The first time a `.fish` file is staged on a
machine, the pre-commit hook prints `dash-gate: building tree-sitter-fish`
and takes a few seconds longer. It needs network access and a C compiler. If
either is missing, the commit fails with `dash gate could not run`.

**Why it is deliberate.** ast-grep has no built-in fish grammar, so the gate
compiles tree-sitter-fish from a pinned commit into
`$XDG_CACHE_HOME/dash-gate/`. The build is one `cc` call, and building from
source matches this repo's standing order. If the build fails, the commit
stops. Falling back to the line-by-line check would quietly bring back the
false positives the parser exists to remove. To use a prebuilt parser instead,
set `DASH_GATE_FISH_PARSER` or `git config dashgate.fishParser` to its path.

**When it becomes a real bug.** If the build runs on every fish commit instead
of once, or if a failed build lets the commit through.

## commit-msg lets non-Conventional subjects through in a password store

**What you will observe.** `~/.config/git/hooks/commit-msg` rejects any subject
that is not Conventional Commits, but `~/.password-store` fills up with commits
like "Add given password for X to store." and "Edit password for Y using vi."

**Why it is deliberate.** pass writes those subjects itself and has no option to
change them, the same position git is in with "Merge", "Revert", and the
`fixup!`/`squash!`/`amend!` subjects of `git commit --fixup`, which the hook also
lets through. Without the carve-out every `pass insert`, `pass edit`, and docker
credential-helper write fails, and leaves its change staged but uncommitted. The
repo's top level has to hold the `.gpg-id` that `pass init` creates, and the
subject has to match one of the pass 1.7.4 shapes. Most shapes carry fixed
wording ("Add given password for X to store."), but "Remove X.", "Rename X to
Y.", and "Copy X to Y." interpolate only a path, so any hand-written subject of
that shape passes too. The AI-trailer check runs before every carve-out, git's
included. `mise run check-hook-knobs` checks one subject per shape, the
`.gpg-id` baseline, and a few pass-shaped subjects that must still block.

**This alone does not make pass commit.** pass commits from the store's own
primary checkout, so pre-commit's primary-checkout gate blocks it too until the
store carries `git config worktree.requireLinked false`. That exemption is the
user's to set, per store, the same as for any repo with no worktree workflow.

**When it becomes a real bug.** If a repo without a `.gpg-id` accepts one of
these subjects, or a fixed-wording shape (Deinitialize, Signing, Set GPG id)
accepts a subject pass would never produce. A newer pass that changes its
wording will show up as a blocked pass command; at that point, add the new shape
to the pattern list and to `PASS_SUBJECTS` instead of loosening it.

## pre-commit's gates ignore a repo's diff drivers

**What you will observe.** A repo that sets a textconv driver (pass sets
`diff.gpg.textconv` to `gpg -d`) shows decrypted text in `git diff`, but the dash
and abs-path gates never see that text. A dash inside a decrypted secret does
not block the commit.

**Why it is deliberate.** The gates check the bytes going into the commit, and
those are the ciphertext. Running the driver would decrypt secrets into a
hook's scan, and with no pinentry tty it fails outright: the dash gate used to
block every pass commit on coding-workspace this way. Both gates pass
`--no-textconv` and `--no-ext-diff`, and `check-dash-gate` stages files behind a
driver that always fails.

**When it becomes a real bug.** If a gate is meant to judge rendered content
rather than stored bytes, or a new gate adds a `git diff` without both flags.

## `source` is a function in Claude Code Bash tool shells

**What you will observe.** Inside a Claude Code Bash tool call, `type source`
reports a function rather than the builtin, and sourcing a file under
`~/.claude/shell-snapshots/` runs `mise activate bash` again right after it.

**Why it is deliberate.** Claude Code runs every Bash tool command as
`/bin/bash -c 'source ~/.claude/shell-snapshots/snapshot-bash-*.sh ... && eval
"<command>"'` (observed via /proc/$$/cmdline from inside the tool, 2026-10-18).
BASH_ENV is read at bash startup, before that source, so the snapshot's
`export PATH` would otherwise overwrite mise activation with the frozen
launch-time PATH on every inline command. `~/.config/mise/claude-bash-env.sh`
(the BASH_ENV file) therefore shadows `source` and re-activates only after a
snapshot source, making activation the last thing to touch PATH. Without it,
`node -v` in a project pinning node = "24.21.0" answers the snapshot's
v26.7.0; with it, the project pin. The kilo and opencode equivalents do not
need this because their `shell` config key points at a wrapper
(`~/.config/mise/agent-shell.sh`) instead of a bare bash.

**When it becomes a real bug.** If the re-activation ever fires for files
outside */shell-snapshots/*, or if Claude Code stops sourcing the snapshot via
`source` (then activation would run before the snapshot again and the frozen
PATH would silently win; the symptom is `node -v` reporting the global version
inside a project pin).

## The commit-boundary checks are machine-wide, not repo-scoped

**What you will observe.** Every commit in a repo with no `mise` check task
prints `pre-commit: no check task declared; repo-local hooks may still run.`
Staging `.gitmodules` or a `skills/` gitlink in an unrelated repo runs
`check-index.py` against `~/.claude/skills` and can print warnings about skills
that repo does not contain.

**Why it is deliberate.** The hook is global, and both checks guard a
machine-wide invariant: a repo's own gate, and the development-skill index.
The index check only fires when the commit changes the skill topology, and it
is warn-only. The notice is one line on stderr because silence is how a repo
with no gate stays invisible.

`mise run check` evaluates the working tree, not the staged index. A partly
staged commit can therefore pass a check the index would fail, and unrelated
worktree edits can block a clean commit. That is the task's own behavior; a
staged-only gate would need a temporary index or worktree.

**When it becomes a real bug.** If the index check blocks a commit, if the
notice appears in a repo that does declare a check task, or if a warning names
a repo-relative path as missing when the path exists in `~/.claude/skills`.

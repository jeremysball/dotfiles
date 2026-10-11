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
hook. Re-run the one command after cloning. It would only become a real bug if
the hook started reading the key from a tracked file and still lost it.

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

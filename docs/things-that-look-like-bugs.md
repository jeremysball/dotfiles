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

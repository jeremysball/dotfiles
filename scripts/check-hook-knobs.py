#!/usr/bin/env python3
"""Assert the global git hooks honor no bypass knob and advertise none.

The dash gate, the primary-checkout gate, and the pre-push worktree-budget
gate each shipped an env knob, and two of the three printed that knob (or
--no-verify) in their own blocked message. A RED/GREEN probe on 2026-10-11
found three of six unguided agents reached for SKIP_PRIMARY_CHECK when
handed a routine commit task, because the hook's own error offered it; one
of those had set it defensively on a commit where no gate had even fired.
A hook that advertises its own escape hatch teaches it to anything that
reads the output, so the knobs are gone and the messages no longer name
one. This script is what keeps them gone.

Two layers of guard, because they fail differently:

  * a source scan for the functional knob pattern (a shell parameter
    expansion that reads the env var) and for the three phrases a hook can
    use to hand out a bypass. Comments naming a removed knob are expected
    and allowed, so the scan matches the expansion, not the bare name. The
    scan reads the whole hooks directory rather than a list of files: a
    hand-listed tuple shipped in the first version missed
    abs-path-gate.py, whose "Skip once with --no-verify" stayed live in the
    very message this file exists to end, and the scan reported the
    directory clean. A guard that can only see what it was told to see is
    a guard that will be wrong again.
  * behavioral runs of the real hooks over throwaway repos, asserting that
    a knob cannot buy a pass and that a blocked message stays clean.

Every behavioral check first proves its gate blocks with no knob set. A knob
check that passes because the gate never fired is a hollow check, and the
baseline is what makes that visible.

Exits non-zero listing every mismatch.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".config", "git", "hooks")
PRE_COMMIT = os.path.join(HOOKS, "pre-commit")
COMMIT_MSG = os.path.join(HOOKS, "commit-msg")
PRE_PUSH = os.path.join(HOOKS, "pre-push")


def hook_sources():
    """Every file in the hooks directory, in a stable order.

    Scanned as a directory rather than a hand-listed tuple on purpose. The
    tuple missed abs-path-gate.py, which kept its "Skip once with
    --no-verify" advertisement while the guard reported the directory
    clean. A new gate file arrives here automatically instead of needing to
    be added to two places. Editor leftovers are skipped: they are not
    deployed, so they cannot advertise anything to a reader.
    """
    skip = (".swp", ".swo", "~")
    return sorted(
        os.path.join(HOOKS, name)
        for name in os.listdir(HOOKS)
        if not name.startswith(".")
        and not name.endswith(skip)
        and os.path.isfile(os.path.join(HOOKS, name))
    )

LOCALES = ("en_US.UTF-8", "C")
EM = chr(0x2014)
EM_NAME = "em dash"

# The functional knob: a shell parameter expansion that reads the env var.
# Bare knob names in comments are expected (they document the removal), so
# match the expansion and not the name.
KNOB_RE = re.compile(
    r"\$\{?(SKIP_[A-Z0-9_]+|GIT_REQUIRE_LINKED_WORKTREE)")
# The three phrases a hook can use to hand out a bypass. All three shipped
# at some point, and all three taught the escape hatch to whatever read the
# output. Matched case-insensitively and forbidden outright, including in
# comments, so "we removed --no-verify" cannot reintroduce the string a
# later edit might mistake for a live instruction.
AD_RE = re.compile(r"no-verify|bypass once|override once", re.IGNORECASE)
# Knob names, for asserting a blocked message does not point at one.
NAME_RE = re.compile(r"SKIP_[A-Z0-9_]+|GIT_REQUIRE_LINKED_WORKTREE")

# Each knob paired with a value that used to buy a pass. SKIP_* names meant
# skip, so "1" was the bypass; GIT_REQUIRE_LINKED_WORKTREE fed a boolean the
# gate tested for falsey, so "0" was the bypass. Recorded per knob because
# the old semantics differed, and testing the wrong value would pass
# vacuously: a knob that was never consulted returns the same code either
# way. The accidental-off direction is included too, since the old emptiness
# test meant SKIP_PRIMARY_CHECK=0, which plainly reads as "do not skip",
# turned the gate off.
BYPASS_VALUES = (
    ("SKIP_DASH_CHECK", "1"),
    ("SKIP_EMDASH_CHECK", "1"),
    ("SKIP_EMDASH", "1"),
    ("SKIP_PRIMARY_CHECK", "1"),
    ("SKIP_PRIMARY_CHECK", "0"),
    ("GIT_REQUIRE_LINKED_WORKTREE", "0"),
    ("GIT_REQUIRE_LINKED_WORKTREE", "false"),
    ("SKIP_WORKTREE_BUDGET", "1"),
)
DASH_KNOBS = ("SKIP_DASH_CHECK", "SKIP_EMDASH_CHECK", "SKIP_EMDASH")
PRIMARY_KNOBS = ("SKIP_PRIMARY_CHECK", "GIT_REQUIRE_LINKED_WORKTREE")


def scratch_env(locale=LOCALES[0]):
    # GIT_CONFIG_NOSYSTEM keeps a throwaway repo off any system-level
    # config, so a stray worktree.maxOpen or core.hooksPath on this machine
    # cannot change what these runs measure.
    return dict(
        os.environ,
        LC_ALL=locale,
        LANG=locale,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="hook-knob-test",
        GIT_AUTHOR_EMAIL="hook-knob-test@invalid",
        GIT_COMMITTER_NAME="hook-knob-test",
        GIT_COMMITTER_EMAIL="hook-knob-test@invalid",
    )


def exempt_scratch(work, env):
    """Exempt a scratch repo from the primary-checkout gate.

    A scratch repo is its own primary checkout, so without this the gate
    blocks every run before the gate under test ever fires. This is the one
    documented way to do it: the repo-local config key, not an env knob
    (docs/things-that-look-like-bugs.md). Used only by the dash checks, where
    the primary gate is not the subject.
    """
    subprocess.run(["git", "-C", work, "config", "worktree.requireLinked",
                    "false"], env=env, check=True)


def init_repo(work, env, exempt=True):
    subprocess.run(["git", "init", "-q", work], env=env, check=True)
    # Point hooksPath at a path that does not exist and sign off. This
    # machine's global config sets core.hooksPath at the real global hooks,
    # so without this a scratch repo would run the live gate on its own seed
    # commit. Every hook under test is invoked explicitly below, never by
    # git, so nothing is lost.
    subprocess.run(["git", "-C", work, "config", "core.hooksPath",
                    os.path.join(work, "no-hooks")], env=env, check=True)
    subprocess.run(["git", "-C", work, "config", "commit.gpgsign", "false"],
                   env=env, check=True)
    if exempt:
        exempt_scratch(work, env)


def stage(work, env, text, name="f.txt"):
    path = os.path.join(work, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    subprocess.run(["git", "-C", work, "add", name], env=env, check=True)


def run(hook, env, cwd, stdin=None, args=()):
    return subprocess.run(["bash", hook] + list(args), cwd=cwd, env=env,
                          input=stdin, capture_output=True, text=True)


def advertises(stderr):
    """Return the first bypass phrase or knob name found in a message."""
    hit = AD_RE.search(stderr)
    if hit:
        return "message still offers a bypass (%r)" % hit.group(0)
    hit = NAME_RE.search(stderr)
    if hit:
        return "message still advertises the %s knob" % hit.group(0)
    return None


def check_source_scan():
    """No hook source expands a bypass knob, and none prints one."""
    problems = []
    for path in hook_sources():
        with open(path, encoding="utf-8") as fh:
            for lineno, text in enumerate(fh, 1):
                rel = os.path.relpath(path, ROOT)
                hit = KNOB_RE.search(text)
                if hit:
                    problems.append("%s:%d still expands %s"
                                    % (rel, lineno, hit.group(1)))
                hit = AD_RE.search(text)
                if hit:
                    problems.append("%s:%d still advertises %r"
                                    % (rel, lineno, hit.group(0)))
    if problems:
        return "\n    ".join(problems)
    return None


def check_dash_knobs():
    """Dash-gate knobs must not buy a pass on a flagged line."""
    work = tempfile.mkdtemp()
    try:
        env = scratch_env()
        init_repo(work, env)
        stage(work, env, "prose " + EM + " more")
        base = run(PRE_COMMIT, env, work)
        if base.returncode == 0:
            return "dash gate let a flagged line through unflagged"
        for knob in DASH_KNOBS:
            done = run(PRE_COMMIT, dict(env, **{knob: "1"}), work)
            if done.returncode == 0:
                return "%s=1 still bypasses the dash gate" % knob
            bad = advertises(done.stderr)
            if bad:
                return "%s=1 blocked, but %s" % (knob, bad)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_primary_knobs():
    """Primary-gate knobs must not buy a pass, and its block must be clean.

    Deliberately NOT exempt: the scratch repo carries no requireLinked key,
    so the primary-checkout gate blocks. That blocked state is exactly what
    SKIP_PRIMARY_CHECK and GIT_REQUIRE_LINKED_WORKTREE used to override.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env()
        init_repo(work, env, exempt=False)
        stage(work, env, "clean prose\n")
        base = run(PRE_COMMIT, env, work)
        if base.returncode == 0:
            return ("primary gate passed an unlinked checkout unflagged; the "
                    "knob checks below would prove nothing")
        for knob, value in (("SKIP_PRIMARY_CHECK", "1"),
                            ("SKIP_PRIMARY_CHECK", "0"),
                            ("GIT_REQUIRE_LINKED_WORKTREE", "0"),
                            ("GIT_REQUIRE_LINKED_WORKTREE", "false")):
            done = run(PRE_COMMIT, dict(env, **{knob: value}), work)
            if done.returncode == 0:
                return "%s=%s still bypasses the primary gate" % (knob, value)
            bad = advertises(done.stderr)
            if bad:
                return "%s=%s blocked, but %s" % (knob, value, bad)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


# The auditor stub. pre-push calls it as `bash "$auditor" --no-content
# "$primary"` and parses the result as prose bucketed by heading, taking
# only lines under safe-to-clean and needs-triage that carry a
# "(worktree: <path>)" annotation. A stub rather than the real skill script
# so the test is machine-independent: it depends only on git being able to
# list a worktree, not on whatever this machine's worktrees look like.
AUDITOR_STUB = """#!/usr/bin/env bash
cat <<REPORT
scratch repo report
  needs-triage:
    probe-branch (worktree: %s) [idle 1d] unmerged, SCORED 0
REPORT
"""


def budget_scratch():
    """A scratch repo with one linked worktree, plus a stub auditor.

    Returns (work, env) with GIT_MAX_WORKTREES=0 and GIT_WORKTREE_AUDIT_BIN
    pointing at the stub, so the one registered worktree puts the count at
    1 against a cap of 0 and the budget gate must block. Caller removes the
    work dir.
    """
    work = tempfile.mkdtemp()
    env = scratch_env()
    init_repo(work, env, exempt=False)
    stage(work, env, "seed\n")
    subprocess.run(["git", "-C", work, "commit", "-q", "-m",
                    "seed"], env=env, check=True)
    linked = os.path.join(work, "wt")
    subprocess.run(["git", "-C", work, "worktree", "add", "-q", "-b",
                    "probe", linked], env=env, check=True)
    stub = os.path.join(work, "auditor.sh")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(AUDITOR_STUB % linked)
    env = dict(env, GIT_MAX_WORKTREES="0", GIT_WORKTREE_AUDIT_BIN=stub)
    return work, env


REF_LINE = "refs/heads/main 0000000000000000000000000000000000000000 " \
           "0000000000000000000000000000000000000000\n"

# Assembled rather than written out. This file is a code file, and the
# abs-path gate scans added lines of code files, so a literal home
# directory in this source would block the very commit that adds the guard
# for that message. Same reason check-dash-gate.py builds its dashes from
# codepoints.
ABS_PATH_LITERAL = "BASE = /" + "/".join(("home", "example", "app"))


def check_abs_path_message():
    """The abs-path gate must block, and its message must name no way out.

    No env knob here; this check exists because the gate's blocked message
    shipped the last surviving "Skip once with --no-verify" in the hooks
    directory, on a day when the source scan above had already been
    merged, passed, and reported the directory clean. It had missed the
    file because it scanned a hand-listed tuple of four names.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env()
        init_repo(work, env)
        stage(work, env, ABS_PATH_LITERAL, name="f.py")
        done = run(PRE_COMMIT, env, work)
        if done.returncode == 0:
            return "abs-path gate let a hardcoded path through unflagged"
        if "hardcoded absolute path" not in done.stderr:
            return "abs-path gate did not fire; something else blocked first"
        bad = advertises(done.stderr)
        if bad:
            return "abs-path gate blocked, but %s" % bad
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_push_budget_knobs():
    """The pre-push budget knob must not buy a pass, and its block is clean."""
    work, env = budget_scratch()
    try:
        base = run(PRE_PUSH, env, work, stdin=REF_LINE)
        if base.returncode == 0:
            return ("budget gate passed with 1 worktree against a cap of 0; "
                    "the knob checks below would prove nothing")
        for knob, value in (("SKIP_WORKTREE_BUDGET", "1"),):
            done = run(PRE_PUSH, dict(env, **{knob: value}), work,
                       stdin=REF_LINE)
            if done.returncode == 0:
                return "%s=%s still bypasses the worktree budget" % (knob, value)
            bad = advertises(done.stderr)
            if bad:
                return "%s=%s blocked, but %s" % (knob, value, bad)
        # The blocked message must still be actionable: it names the repo,
        # the cap, and the debt. A gate that says nothing is its own bug.
        for want in ("worktree budget exceeded", "repo:", "Raise the cap"):
            if want not in base.stderr:
                return "blocked message lost %r" % want
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


NON_CONVENTIONAL = "no conventional prefix here\n"
BANNED_TRAILER = "\n\nCo-Authored-By: Claude\n"


def commit_msg(work, env, text):
    """Run the real commit-msg hook on text; return the CompletedProcess."""
    msg = os.path.join(work, "msg")
    with open(msg, "w", encoding="utf-8") as fh:
        fh.write(text)
    return run(COMMIT_MSG, env, work, stdin="", args=[msg])


def check_commit_msg_clean():
    """commit-msg must enforce its rules without naming an escape hatch.

    Two rules, two failure paths, because each carried its own message. The
    trailer rule also covers the subjects git generates, which skip the
    Conventional Commits rule.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env()
        init_repo(work, env)
        cases = [("bad subject", NON_CONVENTIONAL),
                 ("banned trailer", "feat: fine subject" + BANNED_TRAILER)]
        cases += [("banned trailer on %r" % s, s + BANNED_TRAILER)
                  for s in ("Merge branch 'x'", 'Revert "feat: x"',
                            "fixup! feat: x")]
        for name, text in cases:
            done = commit_msg(work, env, text)
            if done.returncode == 0:
                return "%s passed a commit-msg hook that should have blocked" % name
            bad = advertises(done.stderr)
            if bad:
                return "%s: %s" % (name, bad)
        for subject in ("Merge branch 'x'", "fixup! feat: x", "squash! feat: x",
                        "amend! feat: x"):
            if commit_msg(work, env, subject + "\n").returncode != 0:
                return "git-generated subject %r blocked" % subject
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


# One subject per alternative in the hook's pass pattern, each copied from a
# git_commit/git_add_file call in pass 1.7.4, so a regex edit that drops a
# shape shows up here. Deinit's reencrypt subject has an empty id list.
PASS_SUBJECTS = (
    "Add given password for docker-credential-helpers/x/check to store.",
    "Add password for global/env using vi.",
    "Edit password for global/env using vi.",
    "Add generated password for web/site.",
    "Replace generated password for web/site.",
    "Remove web/site from store.",
    "Remove web/a.",
    "Rename web/a to web/b.",
    "Copy web/a to web/b.",
    "Add current contents of password store.",
    "Configure git repository for gpg file diff.",
    "Set GPG id to ABCDEF.",
    "Set GPG id to ABCDEF (sub).",
    "Signing new GPG id with ABCDEF.",
    "Reencrypt password store using new GPG id ABCDEF.",
    "Reencrypt password store using new GPG id .",
    "Deinitialize /srv/store//.gpg-id.",
    "Deinitialize /srv/store/sub/.gpg-id (sub).",
)

# Pass-shaped but not something pass writes: the tightened alternatives must
# still block these in a store.
NOT_PASS_SUBJECTS = (
    "Deinitialize my weekend.",
    "Add given password for x to store",
)


def check_commit_msg_pass_store():
    """pass's own subjects pass in a password store, and only there.

    Baseline first: the same subjects must block in a repo with no .gpg-id,
    or the store case would pass for the wrong reason. The trailer rule still
    applies inside a store.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env()
        init_repo(work, env)

        def verdict(text):
            return commit_msg(work, env, text).returncode

        for subject in PASS_SUBJECTS:
            if verdict(subject + "\n") == 0:
                return "%r passed outside a password store" % subject
        with open(os.path.join(work, ".gpg-id"), "w", encoding="utf-8") as fh:
            fh.write("ABCDEF\n")
        for subject in PASS_SUBJECTS:
            if verdict(subject + "\n") != 0:
                return "%r blocked inside a password store" % subject
        for subject in NOT_PASS_SUBJECTS + (NON_CONVENTIONAL.rstrip("\n"),):
            if verdict(subject + "\n") == 0:
                return "%r passed inside a password store" % subject
        if verdict(PASS_SUBJECTS[0] + BANNED_TRAILER) == 0:
            return "a banned trailer passed on a pass subject"
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


CHECKS = (
    ("no knob expanded in hook source", check_source_scan),
    ("dash knobs inert", check_dash_knobs),
    ("primary-gate knobs inert", check_primary_knobs),
    ("worktree-budget knob inert", check_push_budget_knobs),
    ("commit-msg block clean", check_commit_msg_clean),
    ("commit-msg passes pass subjects in a store only",
     check_commit_msg_pass_store),
    ("abs-path block clean", check_abs_path_message),
)


def main():
    for hook in (PRE_COMMIT, COMMIT_MSG, PRE_PUSH):
        if not os.path.isfile(hook):
            print("check-hook-knobs: no hook at %s" % hook, file=sys.stderr)
            return 2
    failures = 0
    for name, check in CHECKS:
        problem = check()
        failures += problem is not None
        print("%-4s %s%s" % ("ok" if problem is None else "FAIL", name,
                             "" if problem is None else ": " + problem))
    if failures:
        print("\ncheck-hook-knobs: %d failure(s)" % failures, file=sys.stderr)
        return 1
    print("\ncheck-hook-knobs: %d hook sources clean, %d knobs inert across "
          "the dash, primary, and worktree-budget gates, and every blocked "
          "message names no escape hatch" % (len(hook_sources()),
                                             len(BYPASS_VALUES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
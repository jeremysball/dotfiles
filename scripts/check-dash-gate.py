#!/usr/bin/env python3
"""Exercise the global pre-commit dash gate against a block/pass matrix.

Runs the real hook over a real staged diff in a scratch repo, once per locale,
rather than matching the regex in isolation. Exits non-zero on any mismatch.

Every banned sequence below is built from codepoints instead of written out,
so this file can itself be committed through the gate it tests.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".config", "git", "hooks", "pre-commit",
)
LOCALES = ("en_US.UTF-8", "C")

EM, EN, BAR = chr(0x2014), chr(0x2013), chr(0x2015)
NBSP, NNBSP, FIGSP = chr(0x00A0), chr(0x202F), chr(0x2007)
DD = "-" * 2

CASES = [
    ("block", "em dash",            "prose " + EM + " more"),
    ("block", "en dash",            "prose " + EN + " more"),
    ("block", "horizontal bar",     "prose " + BAR + " more"),
    ("block", "space on both sides", "prose " + DD + " more"),
    ("block", "tight between words", "prose word" + DD + "more"),
    ("block", "nbsp flanked",       "prose" + NBSP + DD + NBSP + "more"),
    ("block", "narrow nbsp flanked", "prose" + NNBSP + DD + NNBSP + "more"),
    ("block", "figure space flanked", "prose" + FIGSP + DD + FIGSP + "more"),
    ("block", "tab flanked",        "prose\t" + DD + "\tmore"),
    ("block", "markdown + bullet",  "+ bullet " + EM + " text"),
    ("pass",  "long option",        "run " + DD + "flag now"),
    ("pass",  "space on the left only", "prose " + DD + "more"),
    ("pass",  "nothing on the right", "prose word" + DD + " "),
    ("pass",  "decrement",          "i" + DD),
    ("pass",  "horizontal rule",    "-" * 3),
    ("pass",  "table separator",    "| " + "-" * 3 + " | " + "-" * 3 + " |"),
    ("pass",  "html comment",       "<!" + DD + " a comment " + DD + ">"),
    ("pass",  "hyphenated word",    "well-known thing"),
    ("pass",  "plain prose",        "nothing to see here"),
]

# Code files: only comment text is checked, and ast-grep says what a comment
# is. Each case is (want, name, filename, content).
CODE_CASES = [
    ("pass",  "shell end-of-options", "a.sh", 'gum spin ' + DD + ' "$@"'),
    ("block", "shell comment",      "a.sh", "true  # a " + DD + " b"),
    ("pass",  "shell option in string", "a.sh", 'echo "x ' + DD + ' y"'),
    ("pass",  "fish end-of-options", "a.fish",
     "set -l x (string escape " + DD + " (commandline -ct))"),
    ("block", "fish comment",       "a.fish", "# a " + EM + " b"),
    ("pass",  "bats end-of-options", "a.bats",
     '@test "x" {\n  run foo ' + DD + ' bar\n}'),
    ("block", "jsonc comment",      "a.jsonc", '{\n  // a ' + EM + ' b\n  "k": 1\n}'),
    ("pass",  "jsonc string",       "a.jsonc", '{ "k": "a ' + DD + ' b" }'),
    ("pass",  "css BEM class",      "a.css", ".block" + DD + "mod { color: red; }"),
    ("pass",  "python string",      "a.py", 'x = "a ' + EM + ' b"'),
    ("block", "python comment",     "a.py", "x = 1  # a" + DD + "b"),
    ("pass",  "shebang shell, no extension", "run",
     "#!/usr/bin/env bash\nexec foo " + DD + ' "$@"'),
    ("block", "toml stays prose",   "a.toml", 'x = 1 # a ' + DD + ' b'),
    ("block", "markdown stays prose", "a.md", "run foo " + DD + " bar"),
]

# Verbatim legal text is not authored prose. A license's punctuation belongs
# to its licensor, and the SIL OFL requires its text travel with the fonts it
# licenses, while its own wording carries the double-hyphen shape this gate
# exists to block. Rewriting legal text is a worse outcome than not checking
# the file, so a file whose name names a legal document is taken at its word.
# Name-scoped, not content-scoped.
#
# The boundary the name has to clear: a legal token ends the name, or is
# followed only by versions, document extensions, and license identifiers or
# the words that qualify them. Anything before the token is allowed
# (font-LICENSE.txt, ThirdPartyNotices.txt, LICENSES/Apache-2.0.txt); an
# ordinary word after it is not (ofl-README, NOTICE-rules.txt,
# license-notes.md). A bare name of identifiers is a license file too
# (GPL-3.0.txt, CC-BY-4.0.txt), while a bare name of only qualifiers is not
# (or-later.txt). The block cases pin the contrast with authored prose of the
# same shape, and the code cases pin that the exemption is prose-only: a
# comment in a legal-named code file is still checked, because a comment is
# authored whatever the file is called.
LICENSE_CASES = [
    ("pass", "license keeps the upstream shape", "LICENSE.txt",
     "or substituting " + DD + " in part " + DD + " whole"),
    ("pass", "licence spelling", "LICENCE",
     "deleting " + DD + " or " + DD + " components"),
    ("pass", "bare copying name", "COPYING",
     "redistribute " + EM + " verbatim " + EM + " text"),
    ("pass", "notice with extension", "NOTICE.txt",
     "attributed " + EN + " as " + EN + " required"),
    ("pass", "version in the name", "OFL-1.1.txt",
     "components " + BAR + " changed " + BAR + " or"),
    ("pass", "dual-license variant", "LICENSE-APACHE",
     "punctuation " + DD + " kept " + DD + " verbatim"),
    ("pass", "inside a vendor tree", "vendor/foo/LICENSE.md",
     "upstream " + DD + " wording " + DD + " kept"),
    ("pass", "unlicense stem", "UNLICENSE",
     "this is free and unencumbered " + DD + " released"),
    ("pass", "copyright stem", "COPYRIGHT",
     "all rights reserved " + DD + " per year"),
    ("pass", "plural stem under a licences directory", "LICENSES/Apache-2.0.txt",
     "Licensed under the Apache License " + DD + " Version 2.0"),
    ("pass", "identifier before the stem", "MIT-LICENSE.txt",
     "Permission is hereby granted " + DD + " free of charge"),
    ("pass", "identifier after the stem, underscore", "LICENSE_APACHE",
     "Licensed under the Apache License " + DD + " Version 2.0"),
    ("pass", "underscore separator", "OFL_1.1.txt",
     "the Font Software " + DD + " modified " + DD + " version"),
    ("pass", "gnu lesser name", "COPYING.LESSER",
     "Additional permissions under the GNU Lesser " + EM + " License"),
    ("pass", "gnu version glued to the stem", "COPYINGv3",
     "under the terms of version 3 " + DD + " or later"),
    ("pass", "camel case notices bundle", "ThirdPartyNotices.txt",
     "This product includes software developed by " + DD + " others"),
    ("pass", "spdx identifier name", "CC-BY-4.0.txt",
     "Creative Commons Attribution 4.0 " + DD + " public"),
    ("pass", "spdx identifier with a qualifier", "GPL-3.0-or-later.txt",
     "either version 3 of the License " + DD + " or any later"),
    ("pass", "spdx expression with a clause word", "BSD-3-Clause.txt",
     "Redistributions of source code " + DD + " retain this notice"),
    ("pass", "unambiguous identifier alone", "MIT.txt",
     "Permission is hereby granted " + DD + " free of charge"),
    ("pass", "identifier with a version", "Apache-2.0.md",
     "Licensed under the Apache License " + DD + " Version 2.0"),
    ("block", "two modifier words are not a license name", "or-later.txt",
     "prose " + DD + " text " + DD + " here"),
    ("block", "cc modifiers alone are not a license name", "by-sa.txt",
     "prose " + DD + " text " + DD + " here"),
    ("block", "authored notes under a legal name", "license-notes.md",
     "quoted " + DD + " terms " + DD + " kept"),
    ("block", "authored readme under an ofl name", "ofl-README",
     "prose " + DD + " text " + DD + " here"),
    ("block", "authored rules under a notice name", "NOTICE-rules.txt",
     "prose " + DD + " text " + DD + " here"),
    ("block", "authored generator under a notice name", "notice-generator.py",
     'print("x")  # a ' + DD + " b"),
    ("block", "authored check under a license name", "license-check.sh",
     "true  # a " + EM + " b"),
    ("block", "one weak identifier word is not a legal name", "gpl.md",
     "prose " + DD + " text " + DD + " here"),
    ("block", "same shape in authored prose", "f.txt",
     "or substituting " + DD + " in part " + DD + " whole"),
    ("block", "stem glued to a word is not a legal name", "noticeable.md",
     "prose " + DD + " text " + DD + " here"),
    ("block", "comment in a legal-named code file", "license.py",
     "x = 1  # a" + DD + "b"),
    ("block", "comment in a legal-named shell file", "ofl.sh",
     "true  # a " + EM + " b"),
    ("pass", "code in a legal-named file is not a comment", "notice.py",
     'x = "a ' + DD + ' b"'),
]


def scratch_env(locale):
    # GIT_CONFIG_NOSYSTEM keeps the scratch repo off any system-level config.
    # The scratch repo is its own primary checkout, so the hook's
    # primary-checkout gate would block every case before the dash gate ran.
    # The removed SKIP_PRIMARY_CHECK knob is gone, so the scratch repo
    # declares itself exempt the one documented way: the repo-local
    # worktree.requireLinked config key (docs/things-that-look-like-bugs.md),
    # written in stage_and_run right after init.
    return dict(
        os.environ,
        LC_ALL=locale,
        LANG=locale,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="dash-gate-test",
        GIT_AUTHOR_EMAIL="dash-gate-test@invalid",
        GIT_COMMITTER_NAME="dash-gate-test",
        GIT_COMMITTER_EMAIL="dash-gate-test@invalid",
    )


def exempt_scratch(work, env):
    """Exempt a scratch repo from the primary-checkout gate.

    The scratch repo is its own primary checkout, so without this the gate
    blocks every case before the dash gate runs. This is the one documented
    way: the repo-local config key (docs/things-that-look-like-bugs.md). The
    SKIP_PRIMARY_CHECK knob that used to do this job was removed 2026-10-11.
    """
    subprocess.run(["git", "-C", work, "config", "worktree.requireLinked",
                    "false"], env=env, check=True)


def stage_and_run(line, locale, name="f.txt"):
    """Stage `line` as file `name` in a throwaway repo, return the hook's exit code."""
    work = tempfile.mkdtemp()
    try:
        env = scratch_env(locale)
        subprocess.run(["git", "init", "-q", work], env=env, check=True)
        exempt_scratch(work, env)
        target = os.path.join(work, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(line + "\n")
        subprocess.run(["git", "-C", work, "add", name], env=env, check=True)
        done = subprocess.run(
            ["bash", HOOK], cwd=work, env=env, capture_output=True, text=True
        )
        return done.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)



def scratch_repo(lines, locale):
    """Return (work_dir, env) with `lines` staged. Caller removes the dir."""
    work = tempfile.mkdtemp()
    env = scratch_env(locale)
    subprocess.run(["git", "init", "-q", work], env=env, check=True)
    exempt_scratch(work, env)
    with open(os.path.join(work, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    subprocess.run(["git", "-C", work, "add", "f.txt"], env=env, check=True)
    return work, env


def check_fix_hint():
    """The sed the hook prints has to be runnable as written, and has to repair
    every shape the gate blocks. A hint that leaves the offending text alone
    puts the user in a loop."""
    offenders = ["a " + EM + " b", "foo" + DD + "bar", "x " + DD + " y"]
    work, env = scratch_repo(offenders, "en_US.UTF-8")
    try:
        blocked = subprocess.run(["bash", HOOK], cwd=work, env=env,
                                 capture_output=True, text=True)
        if blocked.returncode == 0:
            return "hook did not block the offending lines"
        printed = blocked.stdout.splitlines() + blocked.stderr.splitlines()
        hint = next((ln.strip() for ln in printed
                     if "sed -E" in ln), None)
        if hint is None:
            return "hook printed no sed hint"
        fixed = subprocess.run("%s f.txt" % hint, cwd=work, env=env,
                               shell=True, capture_output=True, text=True)
        if fixed.returncode != 0:
            return "printed sed failed: %s" % fixed.stderr.strip()
        with open(os.path.join(work, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write(fixed.stdout)
        subprocess.run(["git", "-C", work, "add", "f.txt"], env=env, check=True)
        again = subprocess.run(["bash", HOOK], cwd=work, env=env,
                               capture_output=True, text=True)
        if again.returncode != 0:
            return "gate still blocks after running its own hint"
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_gitlink():
    """A staged submodule pointer carries no prose; the gate must pass it.

    Exempt like every other scratch repo here. The throwaway repo is its own
    primary checkout, so the primary-checkout gate blocks first and this test
    would measure that gate instead of the dash gate. The exemption predates
    the knob this test was written against: when the knob still existed it was
    set, and the config key is the one supported way now.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env("en_US.UTF-8")
        subprocess.run(["git", "init", "-q", work], env=env, check=True)
        exempt_scratch(work, env)
        sha = "1" * 40
        subprocess.run(["git", "-C", work, "update-index", "--add",
                        "--cacheinfo", "160000,%s,sub" % sha], env=env, check=True)
        done = subprocess.run(["bash", HOOK], cwd=work, env=env,
                              capture_output=True, text=True)
        if done.returncode != 0:
            return "staged gitlink blocked: %s" % done.stderr.strip()[:200]
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_textconv():
    """pre-commit's gates scan committed bytes, never a textconv driver's output.

    pass sets diff.gpg.textconv to gpg -d, which fails with no pinentry tty
    and would otherwise feed decrypted secrets to the scan. A driver that
    always fails stands in for it: if the gate runs it, the commit blocks.
    """
    work = tempfile.mkdtemp()
    try:
        env = scratch_env("en_US.UTF-8")
        subprocess.run(["git", "init", "-q", work], env=env, check=True)
        exempt_scratch(work, env)
        subprocess.run(["git", "-C", work, "config", "diff.fail.textconv",
                        "false"], env=env, check=True)
        with open(os.path.join(work, ".gitattributes"), "w") as fh:
            fh.write("*.gpg diff=fail\n*.sh diff=fail\n")
        with open(os.path.join(work, "secret.gpg"), "wb") as fh:
            fh.write(b"\x85\x02\x0c\x03ciphertext\n")
        # A code file behind the same driver reaches the abs-path gate too.
        with open(os.path.join(work, "tool.sh"), "w") as fh:
            fh.write("echo ok\n")
        subprocess.run(["git", "-C", work, "add", ".gitattributes",
                        "secret.gpg", "tool.sh"], env=env, check=True)
        done = subprocess.run(["bash", HOOK], cwd=work, env=env,
                              capture_output=True, text=True)
        if done.returncode != 0:
            return "staged textconv file blocked: %s" % done.stderr.strip()[:200]
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if not os.path.isfile(HOOK):
        print("check-dash-gate: no hook at %s" % HOOK, file=sys.stderr)
        return 2
    failures = 0
    for locale in LOCALES:
        print("locale %s" % locale)
        for want, name, line in CASES:
            got = "block" if stage_and_run(line, locale) != 0 else "pass"
            ok = got == want
            failures += not ok
            print("  %-4s got=%-5s want=%-5s %s"
                  % ("ok" if ok else "FAIL", got, want, name))
    print("code files")
    for want, name, filename, content in CODE_CASES:
        got = "block" if stage_and_run(content, "en_US.UTF-8", filename) != 0 else "pass"
        ok = got == want
        failures += not ok
        print("  %-4s got=%-5s want=%-5s %s"
              % ("ok" if ok else "FAIL", got, want, name))
    print("verbatim legal names")
    for want, name, filename, content in LICENSE_CASES:
        got = "block" if stage_and_run(content, "en_US.UTF-8", filename) != 0 else "pass"
        ok = got == want
        failures += not ok
        print("  %-4s got=%-5s want=%-5s %s"
              % ("ok" if ok else "FAIL", got, want, name))
    for name, check in (("printed fix hint", check_fix_hint),
                        ("staged gitlink", check_gitlink),
                        ("textconv not run", check_textconv)):
        problem = check()
        failures += problem is not None
        print("%-4s %s%s" % ("ok" if problem is None else "FAIL", name,
                             "" if problem is None else ": " + problem))
    if failures:
        print("\ncheck-dash-gate: %d mismatch(es)" % failures, file=sys.stderr)
        return 1
    print("\ncheck-dash-gate: %d cases pass in %d locales, %d code-file cases, "
          "%d legal-name cases, plus the fix hint, staged-gitlink, and textconv "
          "cases. Knob inertness and bypass advertisements across all three hooks "
          "live in scripts/check-hook-knobs.py."
          % (len(CASES), len(LOCALES), len(CODE_CASES), len(LICENSE_CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

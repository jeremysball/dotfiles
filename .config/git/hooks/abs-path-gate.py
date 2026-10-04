#!/usr/bin/env python3
"""Refuse a commit that adds a hardcoded absolute path to a script.

Enforces ~/.claude/CLAUDE.md "Avoid hardcoded absolute paths": code meant to
run in more than one place or one session must not hardcode /home/...,
/workspace/..., a username, or a hostname.

Scans only staged code files, and only the lines this commit adds, so prose
naming an example path and a pre-existing violation in an unrelated file both
pass. A test asserting on a literal path is not a portability bug and is
skipped.
"""
import re
import subprocess
import sys

CODE = (".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".mjs", ".cjs", ".rb", ".pl")
VIOLATION = re.compile(r"(?<![\w$])/(?:home|workspace|Users|root)/[^\s\"'`]*")


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True).stdout


def staged_code_files():
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").split()
    return [p for p in out if p.endswith(CODE)]


def added_lines(path):
    """(file, text) for each '+' line this commit introduces in path."""
    rows, current = [], None
    for line in git("diff", "--cached", "-U0", "--", path).splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            rows.append((current or path, line[1:]))
    return rows


def is_fixture(path):
    name = path.rsplit("/", 1)[-1]
    return "/test" in path or "/tests" in path or name.startswith("test_") or "_test." in name


def main():
    bad = []
    for path in staged_code_files():
        if is_fixture(path):
            continue
        for where, text in added_lines(path):
            for m in VIOLATION.finditer(text):
                bad.append(f"{where}: {m.group(0)}")
    if bad:
        sys.exit(
            "hardcoded absolute path on an added code line:\n  "
            + "\n  ".join(sorted(set(bad)))
            + "\nMake it relative or resolve it from an env var."
              " Skip once with --no-verify if the literal is the point."
        )
    print("abs-path gate: clean")


if __name__ == "__main__":
    main()

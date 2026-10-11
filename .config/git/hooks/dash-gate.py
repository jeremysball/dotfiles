#!/usr/bin/env python3
"""Dash gate for the global pre-commit hook.

Blocks staged em/en dashes, the horizontal bar, and double hyphens standing in
for a dash. What gets checked depends on the file:

  prose (markdown, text, toml, anything unrecognised)
      every added line, exactly as before this script existed
  code ast-grep can parse (see LANGS, plus shebang detection)
      only the comment text on added lines. ast-grep decides what a comment
      is, so a shell end-of-options marker or a BEM modifier class in code
      no longer trips the gate, while the same shape in a comment still does

Unknown types default to strict on purpose: a file the gate cannot parse is
treated as prose rather than waved through.

Fish has no built-in ast-grep grammar. tree-sitter-fish is compiled from a
pinned commit the first time a fish file is staged, into the XDG cache. If
that build fails, the gate exits 2 rather than silently falling back.

Fish parser location, highest precedence first:
  --fish-parser PATH              flag
  DASH_GATE_FISH_PARSER=PATH      env var
  git config dashgate.fishParser  config key
  $XDG_CACHE_HOME/dash-gate/tree-sitter-fish-<rev>.so, built on demand
An explicit path is never built; if it is missing, the gate fails.

Exit codes: 0 clean, 1 dashes found, 2 the gate could not run.

Every banned sequence below is built from codepoints, so this file can itself
be committed through the gate.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

EM, EN, BAR = chr(0x2014), chr(0x2013), chr(0x2015)
NBSP, NNBSP, FIGSP = chr(0x00A0), chr(0x202F), chr(0x2007)
DD = "-" * 2

# Characters that render as a space but are not one. Folded to a plain space
# before matching, so padding a double hyphen with them is not an escape.
FAKE_SPACES = re.compile("[%s%s%s]" % (NBSP, NNBSP, FIGSP))
# ASCII-only classes, matching the bash gate's LC_ALL=C [[:space:]]/[[:alnum:]].
DASH_RE = re.compile(
    "[%s%s%s]|[ \t\r\f\v]%s[ \t\r\f\v]|[A-Za-z0-9]%s[A-Za-z0-9]"
    % (EM, EN, BAR, DD, DD)
)

FISH_REPO = "https://github.com/ram02z/tree-sitter-fish"
FISH_REV = "b7f1d682941e0c62dfcd6bf9ef481638351bab16"

# ast-grep language -> (extension ast-grep infers it from, comment node kinds)
COMMENT_KINDS = {
    "bash": ("sh", ["comment"]),
    "fish": ("fish", ["comment"]),
    "python": ("py", ["comment"]),
    "javascript": ("js", ["comment"]),
    "typescript": ("ts", ["comment"]),
    "tsx": ("tsx", ["comment"]),
    "json": ("json", ["comment"]),
    "yaml": ("yaml", ["comment"]),
    "go": ("go", ["comment"]),
    "rust": ("rs", ["line_comment", "block_comment"]),
    "lua": ("lua", ["comment"]),
    "nix": ("nix", ["comment"]),
    "css": ("css", ["comment"]),
    "html": ("html", ["comment"]),
    "c": ("c", ["comment"]),
    "cpp": ("cpp", ["comment"]),
    "java": ("java", ["comment"]),
    "ruby": ("rb", ["comment"]),
}

# File extension -> ast-grep language. jsonc parses as json (tree-sitter-json
# keeps comments). bats parses as bash: tree-sitter recovers around the
# `@test` lines, and comments still come back as comment nodes.
LANGS = {
    "sh": "bash", "bash": "bash", "bats": "bash",
    "fish": "fish",
    "py": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "javascript",
    "ts": "typescript", "mts": "typescript", "cts": "typescript",
    "tsx": "tsx",
    "json": "json", "jsonc": "json",
    "yml": "yaml", "yaml": "yaml",
    "go": "go", "rs": "rust", "lua": "lua", "nix": "nix", "css": "css",
    "html": "html", "htm": "html",
    "c": "c", "h": "c", "cc": "cpp", "cpp": "cpp", "hpp": "cpp",
    "java": "java", "rb": "ruby",
}

SHEBANGS = {
    "sh": "bash", "bash": "bash", "fish": "fish",
    "python": "python", "python3": "python", "node": "javascript",
}


class GateError(Exception):
    """The gate could not run. Never read as a pass."""


def git(*args):
    done = subprocess.run(["git", *args], capture_output=True)
    if done.returncode != 0:
        raise GateError("git %s failed: %s"
                        % (" ".join(args), done.stderr.decode(errors="replace").strip()))
    return done.stdout


def decode(raw):
    return raw.decode("utf-8", errors="surrogateescape")


def added_lines():
    """{path: {lineno: text}} for every line the index adds over HEAD."""
    diff = decode(git("-c", "core.quotePath=false", "diff", "--cached",
                      "--unified=0", "--no-color", "--no-ext-diff",
                      "--src-prefix=a/", "--dst-prefix=b/"))
    files, path, lineno = {}, None, 0
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
            if path is not None:
                files.setdefault(path, {})
        elif line.startswith("@@ "):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and path is not None:
            files[path][lineno] = line[1:]
            lineno += 1
    return {p: ls for p, ls in files.items() if ls}


def language_of(path, first_line):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    if ext in LANGS:
        return LANGS[ext]
    if not ext and first_line.startswith("#!"):
        words = first_line[2:].split()
        if words and os.path.basename(words[0]) == "env":
            words = [w for w in words[1:] if not w.startswith("-")]
        if words:
            return SHEBANGS.get(os.path.basename(words[0]))
    return None


def resolve_fish_parser(flag):
    explicit = flag or os.environ.get("DASH_GATE_FISH_PARSER")
    if not explicit:
        got = subprocess.run(["git", "config", "--get", "dashgate.fishParser"],
                             capture_output=True, text=True)
        explicit = got.stdout.strip() or None
    if explicit:
        path = os.path.expanduser(explicit)
        if not os.path.isfile(path):
            raise GateError("fish parser %s does not exist (set by flag, "
                            "DASH_GATE_FISH_PARSER, or dashgate.fishParser)" % path)
        return path
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(cache, "dash-gate", "tree-sitter-fish-%s.so" % FISH_REV[:12])
    if not os.path.isfile(path):
        build_fish_parser(path)
    return path


def build_fish_parser(dest):
    print("dash-gate: building tree-sitter-fish %s into %s (first fish file only)"
          % (FISH_REV[:12], dest), file=sys.stderr)
    cc = os.environ.get("CC", "cc")
    src = tempfile.mkdtemp(prefix="dash-gate-fish-")
    try:
        for cmd in (["git", "init", "-q", src],
                    ["git", "-C", src, "fetch", "-q", "--depth", "1", FISH_REPO, FISH_REV],
                    ["git", "-C", src, "checkout", "-q", "FETCH_HEAD"]):
            done = subprocess.run(cmd, capture_output=True, text=True)
            if done.returncode != 0:
                raise GateError("fetching tree-sitter-fish failed: %s" % done.stderr.strip())
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp%d" % os.getpid()
        done = subprocess.run(
            [cc, "-shared", "-fPIC", "-O2", "-I", "src", "src/parser.c",
             "src/scanner.c", "-o", tmp],
            cwd=src, capture_output=True, text=True)
        if done.returncode != 0:
            raise GateError("compiling tree-sitter-fish with %s failed: %s"
                            % (cc, done.stderr.strip()))
        os.replace(tmp, dest)
    except FileNotFoundError as exc:
        raise GateError("building tree-sitter-fish needs %s on PATH" % exc.filename)
    finally:
        shutil.rmtree(src, ignore_errors=True)


def comment_text(code_files, fish_parser_flag):
    """{path: {lineno: comment text on that line}} via one ast-grep scan.

    code_files is {path: (language, staged blob text)}."""
    if not shutil.which("ast-grep"):
        raise GateError("ast-grep is not on PATH; it is pinned in "
                        ".config/mise/config.toml (mise install)")
    work = tempfile.mkdtemp(prefix="dash-gate-")
    try:
        langs = sorted({lang for lang, _ in code_files.values()})
        config = []
        if "fish" in langs:
            config += ["customLanguages:", "  fish:",
                       "    libraryPath: %s" % json.dumps(resolve_fish_parser(fish_parser_flag)),
                       "    extensions: [fish]", "    expandoChar: _"]
        cfg = os.path.join(work, "sgconfig.yml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write("\n".join(config + ["ruleDirs: []"]) + "\n")
        rules = []
        for lang in langs:
            kinds = COMMENT_KINDS[lang][1]
            rule = {"kind": kinds[0]} if len(kinds) == 1 else {"any": [{"kind": k} for k in kinds]}
            rules.append(json.dumps({"id": "comment-" + lang, "language": lang, "rule": rule}))
        names = {}
        for i, (path, (lang, text)) in enumerate(sorted(code_files.items())):
            name = os.path.join(work, "f%d.%s" % (i, COMMENT_KINDS[lang][0]))
            with open(name, "w", encoding="utf-8", errors="surrogateescape") as fh:
                fh.write(text)
            names[name] = path
        done = subprocess.run(
            ["ast-grep", "scan", "-c", cfg, "--inline-rules", "\n---\n".join(rules),
             "--json=compact", *names],
            cwd=work, capture_output=True)
        try:
            matches = json.loads(decode(done.stdout))
        except ValueError:
            raise GateError("ast-grep scan failed (exit %d): %s"
                            % (done.returncode, decode(done.stderr).strip()))
        out = {path: {} for path in code_files}
        for m in matches:
            path = names.get(os.path.join(work, os.path.basename(m["file"])))
            if path is None:
                raise GateError("ast-grep reported an unexpected file %s" % m["file"])
            start = m["range"]["start"]["line"] + 1
            for offset, piece in enumerate(m["text"].split("\n")):
                line = out[path].setdefault(start + offset, "")
                out[path][start + offset] = (line + " " + piece) if line else piece
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def find_hits(fish_parser_flag=None):
    added = added_lines()
    code = {}
    for path, lines in added.items():
        blob = decode(git("show", ":" + path))
        lang = language_of(path, blob.split("\n", 1)[0])
        if lang is not None:
            code[path] = (lang, blob)
    comments = comment_text(code, fish_parser_flag) if code else {}
    hits = []
    for path in sorted(added):
        for lineno, text in sorted(added[path].items()):
            checked = comments[path].get(lineno, "") if path in code else text
            if DASH_RE.search(FAKE_SPACES.sub(" ", checked)):
                hits.append((path, lineno, path in code, text))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fish-parser", help="compiled tree-sitter-fish .so")
    args = ap.parse_args(argv)
    try:
        hits = find_hits(args.fish_parser)
    except GateError as exc:
        print("pre-commit: dash gate could not run: %s" % exc, file=sys.stderr)
        print("Bypass once: git commit --no-verify  or  SKIP_DASH_CHECK=1 git commit",
              file=sys.stderr)
        return 2
    if not hits:
        return 0
    err = sys.stderr
    print("pre-commit: dash blocked. Staged changes contain an em/en dash or a "
          "double-hyphen stand-in.", file=err)
    print("", file=err)
    for path, lineno, in_code, text in hits[:20]:
        print("  %s:%d%s: %s" % (path, lineno, " (comment)" if in_code else "",
                                 text.strip()), file=err)
    if len(hits) > 20:
        print("  ... and %d more" % (len(hits) - 20), file=err)
    print("", file=err)
    print("Replace it with a comma, period, or colon. Keep related words together.",
          file=err)
    if any(not in_code for _, _, in_code, _ in hits):
        # The fold has to lead. The gate normalises no-break spaces to a plain
        # space before matching, so a hint that skips that step leaves an
        # NBSP-padded double hyphen looking repaired and still blocked.
        print("For prose files, this rewrites every offending shape:", file=err)
        print('  LC_ALL=C sed -E "s/%s/ /g; s/%s/ /g; s/%s/ /g; s/ *[%s%s%s] */, /g; '
              's/[[:space:]]%s[[:space:]]/, /g; s/([[:alnum:]])%s([[:alnum:]])/\\1, \\2/g"'
              % (NBSP, NNBSP, FIGSP, EM, EN, BAR, DD, DD), file=err)
    if any(in_code for _, _, in_code, _ in hits):
        print("In code files only comment text is checked; edit those comments by hand.",
              file=err)
    print("", file=err)
    print("Prose rules still match a markdown table separator padded with spaces"
          " (| %s |). Bypass that." % DD, file=err)
    print("Bypass once: git commit --no-verify  or  SKIP_DASH_CHECK=1 git commit",
          file=err)
    return 1


if __name__ == "__main__":
    sys.exit(main())

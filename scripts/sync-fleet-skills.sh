#!/usr/bin/env bash
# sync-fleet-skills.sh: keep the fleet (opencode + kilo) pointed at the same
# skill registry Claude Code uses, and stop the plugin-skill symlinks from
# rotting on every plugin update.
#
# The problem this exists for:
#   Plugin skills do not live at a fixed path. They live behind a version:
#     ~/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/
#                                                                ^^^^^
#   When a plugin updates, Claude Code writes a NEW version directory and the
#   old one goes away. Anything that named the old path (a symlink, a config
#   key) silently dangles. That is exactly how ~/.config/opencode/skills/ ended
#   up with 25 dead links: 16 pinned to superpowers 6.1.1 (installed: 6.3.0)
#   and 9 pointing at /home/node/..., a container path from a machine that no
#   longer exists. opencode was loading 1 of 14 superpowers skills and 0 of the
#   115 personal ones.
#
# The fix, in two halves:
#   1. A stable directory, ~/.claude/fleet-skills/, holding one symlink per
#      plugin skill. The path has no version in it, so config files can name
#      it once and never change. This script rewrites the links inside it.
#   2. Both tools declare the registry in config via their native `skills.paths`
#      key (opencode and kilo share the same schema; kilo is an opencode fork):
#          "skills": { "paths": ["~/.claude/skills", "~/.claude/fleet-skills"] }
#      Personal skills need no symlinks at all, since ~/.claude/skills is
#      already a stable path.
#
# Why the links are RELATIVE and tracked:
#   ~/.claude is its own repo (jeremysball/dotclaude) and fleet-skills/ is
#   tracked in it. Git stores a symlink as its literal target string, so an
#   absolute target would commit "/home/jeremy/..." plus a pinned version into
#   a repo that clones onto other machines. Relative targets drop the username.
#   The version stays on purpose: the tracked links act as a lockfile, so a
#   plugin update shows up as a reviewable git diff in dotclaude and --check
#   reports the lockfile as stale.
#
# Source of truth for "which version is current" is the manifest Claude Code
# already maintains, ~/.claude/plugins/installed_plugins.json, never a glob of
# the cache directory (which keeps stale version directories around).
#
# Modes:
#   (no args)        Repair. Rewrite ~/.claude/fleet-skills/ to match the
#                    manifest, pruning links for skills that no longer exist.
#   --check          Alert only. Report every drift with its path, exit 1.
#                    Never writes. This is `mise run check-fleet-skills`.
#   --tracked-only   Alert only, for the global pre-commit hook and CI.
#                    Validates the two things a commit can break without any
#                    runtime state: the tracked kilo/opencode configs still
#                    declare both skill paths, and every committed fleet-skills
#                    link is relative and resolves.
#   --verbose / -v   Print each link as it is checked or written.
#
# Exit 0 = everything holds. Exit 1 = drift found (each one printed with its
# path and reason). Exit 2 = bad usage.
#
# Note on taskferry: ~/.claude is on taskferry's sandbox deny-list
# (src/sandbox.js defaultDenyList), masked with a tmpfs. A ferried worker
# sees none of this, symlink or not, because a symlink resolves against the
# sandbox namespace. Only the paths in .config/taskferry/config.json roBind
# are bound back; fleet-skills is not one of them.

set -euo pipefail

MODE="repair"
VERBOSE=false

for arg in "$@"; do
    case "$arg" in
        --check) MODE="check" ;;
        --tracked-only) MODE="tracked-only" ;;
        --verbose|-v) VERBOSE=true ;;
        --help|-h)
            sed -n '2,62p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

die() { echo "ERROR: $*" >&2; exit 1; }
log() { [ "$VERBOSE" = true ] && echo "  $*" >&2 || true; }

FAILURES=0
fail() { echo "  $*" >&2; FAILURES=$((FAILURES + 1)); }

CLAUDE_DIR="$HOME/.claude"
FLEET_DIR="$CLAUDE_DIR/fleet-skills"
MANIFEST="$CLAUDE_DIR/plugins/installed_plugins.json"
PERSONAL_PATH="~/.claude/skills"
FLEET_PATH="~/.claude/fleet-skills"

# --- locate the dotfiles repo root (for the config-file checks) ---
script_path="$(readlink -f "$0")"
case "$script_path" in
    */scripts/sync-fleet-skills.sh)
        DOTFILES_ROOT="${script_path%/scripts/sync-fleet-skills.sh}"
        ;;
    *)
        die "expected to live at <dotfiles-root>/scripts/sync-fleet-skills.sh; resolved to $script_path"
        ;;
esac

# --- config check ---------------------------------------------------------
# kilo.jsonc / opencode.jsonc are JSONC: both use // comments (including
# inside https:// URLs, which defeats a naive sed) and trailing commas. jq
# and node both reject that. Bun reads JSONC natively via require(), so the
# whole check is one expression rather than a hand-rolled parser. Bun is
# pinned in this repo's mise [tools] for exactly this reason.
config_declares_paths() {
    local file="$1"
    bun -e '
      // bun -e argv is [bunPath, ...args], so user args start at index 1
      // (node -e would start at 2).
      const [file, ...required] = process.argv.slice(1);
      let config;
      try {
        config = require(file);
      } catch (err) {
        console.log(`not valid JSONC: ${err.message}`);
        process.exit(1);
      }
      const paths = config?.skills?.paths;
      if (!Array.isArray(paths)) {
        console.log(`no "skills": {"paths": [...]} key`);
        process.exit(1);
      }
      const missing = required.filter((p) => !paths.includes(p));
      if (missing.length) {
        console.log(`skills.paths is missing ${missing.join(", ")} (has: ${paths.join(", ")})`);
        process.exit(1);
      }
    ' "$file" "$PERSONAL_PATH" "$FLEET_PATH"
}

check_configs() {
    local tool file reason
    command -v bun >/dev/null 2>&1 || die "bun is required to read the JSONC configs (it is pinned in this repo's mise [tools]; run \`mise install\`)"
    for tool in kilo opencode; do
        file="$DOTFILES_ROOT/.config/$tool/$tool.jsonc"
        if [ ! -f "$file" ]; then
            fail "$file: file missing (cannot verify $tool declares its skill paths)"
            continue
        fi
        if reason="$(config_declares_paths "$file")"; then
            log "$file (declares both skill paths)"
        else
            fail "$file: $reason"
        fi
    done
}

# --- link validation ------------------------------------------------------
# Belief: every entry under fleet-skills/ is a RELATIVE symlink that resolves.
# An absolute one means the sync ran with an older version of this script and
# a "/home/<user>/..." target is about to be committed; a dangling one means a
# plugin moved and the lockfile is stale.
check_links_shape() {
    [ -d "$FLEET_DIR" ] || return 0
    local entry name target
    for entry in "$FLEET_DIR"/*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        name="$(basename "$entry")"
        if [ ! -L "$entry" ]; then
            fail "$entry: not a symlink (fleet-skills/ holds generated links only; move a hand-written skill to ~/.claude/skills/)"
            continue
        fi
        target="$(readlink "$entry")"
        case "$target" in
            /*) fail "$entry: absolute target $target (must be relative so it survives a clone on another machine; re-run \`mise run sync-fleet-skills\`)" ;;
            *)
                if [ ! -e "$entry" ]; then
                    fail "$entry: dangling, target $target does not resolve (plugin moved or was removed; re-run \`mise run sync-fleet-skills\`)"
                else
                    log "$name -> $target"
                fi
                ;;
        esac
    done
}

# --- desired state from the plugin manifest -------------------------------
# Emits "<skill-name>\t<absolute-target>" per line. Deduplicates install paths
# because a plugin appears once per scope (user and project) in the manifest.
declare -A DESIRED=()

build_desired() {
    [ -f "$MANIFEST" ] || die "$MANIFEST not found (no Claude Code plugins installed?)"
    command -v jq >/dev/null 2>&1 || die "jq is required"

    local install_path skills_dir skill name
    while IFS= read -r install_path; do
        [ -n "$install_path" ] || continue
        skills_dir="$install_path/skills"
        [ -d "$skills_dir" ] || continue
        for skill in "$skills_dir"/*; do
            [ -f "$skill/SKILL.md" ] || continue
            name="$(basename "$skill")"
            if [ -n "${DESIRED[$name]:-}" ] && [ "${DESIRED[$name]}" != "$skill" ]; then
                die "two installed plugins both provide the skill \"$name\": ${DESIRED[$name]} and $skill. Uninstall one, or the fleet would silently load whichever the tool happens to scan first."
            fi
            DESIRED[$name]="$skill"
        done
    done < <(jq -r '.plugins | to_entries[] | .value[] | .installPath' "$MANIFEST" | sort -u)

    [ "${#DESIRED[@]}" -gt 0 ] || die "no plugin skills found via $MANIFEST; refusing to prune $FLEET_DIR to empty"
}

relative_target() {
    realpath --no-symlinks --relative-to="$FLEET_DIR" "$1"
}

sync_links() {
    local name target rel current
    mkdir -p "$FLEET_DIR"

    for name in "${!DESIRED[@]}"; do
        target="${DESIRED[$name]}"
        rel="$(relative_target "$target")"
        current="$(readlink "$FLEET_DIR/$name" 2>/dev/null || true)"
        if [ "$current" = "$rel" ]; then
            log "ok      $name -> $rel"
            continue
        fi
        if [ -e "$FLEET_DIR/$name" ] && [ ! -L "$FLEET_DIR/$name" ]; then
            die "$FLEET_DIR/$name is a real file or directory, not a generated link. Refusing to overwrite it."
        fi
        ln -sfn "$rel" "$FLEET_DIR/$name"
        echo "  linked  $name -> $rel"
    done

    local entry base
    for entry in "$FLEET_DIR"/*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        base="$(basename "$entry")"
        [ -n "${DESIRED[$base]:-}" ] && continue
        if [ ! -L "$entry" ]; then
            echo "  kept    $base (not a generated link; left alone)" >&2
            continue
        fi
        rm -f "$entry"
        echo "  pruned  $base (no installed plugin provides it)"
    done
}

check_links_current() {
    local name target rel current entry base
    for name in "${!DESIRED[@]}"; do
        target="${DESIRED[$name]}"
        rel="$(relative_target "$target")"
        current="$(readlink "$FLEET_DIR/$name" 2>/dev/null || true)"
        if [ -z "$current" ]; then
            fail "$FLEET_DIR/$name: missing (plugin provides it; run \`mise run sync-fleet-skills\`)"
        elif [ "$current" != "$rel" ]; then
            fail "$FLEET_DIR/$name: points at $current, expected $rel (plugin updated; run \`mise run sync-fleet-skills\`)"
        else
            log "$name -> $rel"
        fi
    done

    [ -d "$FLEET_DIR" ] || return 0
    for entry in "$FLEET_DIR"/*; do
        [ -L "$entry" ] || continue
        base="$(basename "$entry")"
        [ -n "${DESIRED[$base]:-}" ] && continue
        fail "$entry: stale (no installed plugin provides \"$base\"; run \`mise run sync-fleet-skills\`)"
    done
}

# --- dispatch -------------------------------------------------------------
case "$MODE" in
    tracked-only)
        echo "check: tracked kilo/opencode skill paths + fleet-skills link shape"
        check_configs
        check_links_shape
        ;;
    check)
        echo "check: fleet-skills links match installed plugins, configs declare both paths"
        build_desired
        check_configs
        check_links_shape
        check_links_current
        ;;
    repair)
        echo "sync: $FLEET_DIR from $MANIFEST"
        build_desired
        sync_links
        echo ""
        echo "check: tracked kilo/opencode skill paths"
        check_configs
        ;;
esac

if [ "$FAILURES" -gt 0 ]; then
    echo "" >&2
    echo "$FAILURES check(s) failed." >&2
    exit 1
fi

echo "all checks passed."

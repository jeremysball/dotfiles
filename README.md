# dotfiles

My dotfiles, managed with [mise](https://mise.jdx.dev/)'s built-in dotfiles
feature (`mise bootstrap dotfiles`).

The repo root mirrors `$HOME` directly: `.config/fish/config.fish` in this
repo ends up symlinked at `~/.config/fish/config.fish`. Every managed target
is declared as its own entry in the `[dotfiles]` table at the bottom of
`.config/mise/config.toml`. `mise bootstrap dotfiles apply` reads that table
and creates the symlinks. That is the whole idea.

## Setting up a fresh machine

```fish
git clone https://github.com/jeremysball/dotfiles ~/.dotfiles
cd ~/.dotfiles
./init.sh
exec fish
```

`init.sh` runs `mise bootstrap dotfiles apply` (creates the symlinks) and
then `mise install` (pulls down the tools). It also clones the separate
[jeremysball/mise-en-system](https://github.com/jeremysball/mise-en-system)
repo to `~/projects/mise-en-system` and runs its install tasks
(`install-secrets`, `install-dotclaude`, `install-serper-axi`). Those tasks
live there instead of in this repo's own `.config/mise/config.toml` because
that file is loaded globally (needed for `[tools]` to land on `PATH` from
any directory), and a global `[tasks]` table would leak into every other
project's `mise tasks` output. Run any of them again later with
`mise-sys <task>`, a fish function wrapping `mise -C ~/projects/mise-en-system
run <task>`. For secret updates after the first install, use
`mise-sys secrets-sync` (pulls both `secret-management` and `password-store`
and re-links) -- re-running `install-secrets` only clones when missing and
will not pick up new secrets.

`~/.dotfiles` is not an arbitrary choice: it is `dotfiles.root`'s default, the
setting mise consults to find where dotfile sources live. `init.sh` also
exports `MISE_DOTFILES_ROOT` pointing at wherever it actually lives, so
`./init.sh` itself works from any clone location — but that export only
covers `init.sh`'s own run. Any later ad-hoc `mise bootstrap dotfiles ...`
command, run from a plain shell after setup, still resolves sources under
whatever `dotfiles.root` actually is: the `~/.dotfiles` default unless you've
set it otherwise with `mise settings set -g dotfiles.root <path>`. Cloning to
`~/.dotfiles` means you never have to think about this again; cloning
elsewhere means setting that global setting once, not just relying on
`init.sh`'s export.

Two things about `mise bootstrap dotfiles apply` matter here and neither is
optional.

No target symlinks a whole directory wholesale unless nothing ever writes
into it at runtime. Symlinking `~/.config/fish` as one symlink into the repo
would mean anything that later writes into that directory is writing into
git — fish drops `fish_variables` there, fisher installs its plugin files
there, neither belongs in the repo. `fish/functions`, `fish/conf.d`, and
`fish/completions` instead use `mode = "symlink-each"`: mise symlinks only
the files that exist in the repo's copy of the directory, so the real
directory stays a real directory and anything fisher/tide writes straight
into it lands as a plain, gitignored file next to the symlinks. `.local/bin`
uses the same mode for a second reason below. Everything else not covered by
`symlink-each` or the four whole-directory submodule entries
(`alacritty-theme`, `zsh-autosuggestions`, `zsh-syntax-highlighting`,
`powerlevel10k` — nothing writes into an external theme/plugin checkout at
runtime) is a plain single-file entry. A plain `git clone` doesn't check
submodules out, so `init.sh` runs `git submodule update --init --recursive`
before applying anything — do the same by hand if you're applying without
`init.sh`.

If a live file already exists where `apply` wants to put a symlink and its
content doesn't match the tracked source, it refuses and tells you which
targets conflict. That is a feature. `--force` overwrites the live file with
the repo's version; that is the only direction `--force` goes. To pull an
existing live file into the repo instead (the opposite direction), use
`mise bootstrap dotfiles add <target>`, understanding what it does first: for
a target that isn't managed yet, it moves the live file into the repo as the
new source and symlinks back, so nothing is lost either direction. For a
target that's already managed, it instead overwrites the repo's tracked
source with whatever is currently live at that path — so run it on a clean
tree and check `git diff` before committing.

Simulate anything before you run it with `mise bootstrap dotfiles apply --dry-run`.
It prints every symlink it would create and touches nothing.

### `apply` is all-or-nothing for a plain `= {}` entry, but not for `symlink-each`

`mise bootstrap dotfiles apply` with no target arguments applies every entry
in `[dotfiles]` in one batch. For a plain single-file entry, if that one
target's source doesn't resolve, the whole run fails before touching
anything. A `symlink-each` entry doesn't share that failure mode: it skips
whichever of its own files don't resolve and still applies the rest.

That's the second reason `.local/bin` is `symlink-each` rather than one entry
per script: `gf2`, `libregate`, `pico8`, and `speedcat` are checked-in
symlinks to absolute paths on the machine those tools actually live on
(`/home/jeremy/tools/gf/gf2` and similar). On any other machine those four
just don't get created — `mise bootstrap dotfiles apply` (what `init.sh`
runs) still succeeds and links every other script in the directory.

## `[dotfiles]`

All 60 tracked targets live in one table in `.config/mise/config.toml`,
grouped by comment header to match what used to be separate stow packages:

- `fish` shell config, one set of entries covering every host
- `mise` this file itself
- `nvim` LazyVim config, including `lazy-lock.json`
- `doom` Doom Emacs config, the three files in `~/.config/doom`
- bin scripts that live in `~/.local/bin`
- `fonts`
- `bash` `~/.bashrc`, for the shells that are not fish
- `git` `~/.gitconfig` and the global ignore file
- `gh` GitHub CLI config and the PAT switcher `.bashrc` sources
- `systemd` user units and timers
- `zellij`, `htop`, `superfile`, `himalaya`, `alfred`, `taskferry`, `mcporter`
- `pi` agent config, extensions, skills, and prds under `.pi/` (absorbed
  from the old `jeremysball/pi-mono` repo 2026-08-30)
- an older graphical workstation section (`i3`, `xorg`, `picom`, `alacritty`,
  `helix`, `zsh`, `tmux`), kept for whenever I set one back up

There's no package concept anymore, so "only stow what a machine needs" is
now "only pass the targets a machine needs to `apply`," or just apply
everything and let the unused symlinks (an `i3` config on a machine with no
`i3`, say) sit there unused. They're harmless clutter, not a functional
problem.

### What is deliberately not tracked

`hosts.yml` under `gh` holds OAuth tokens and is gitignored. So is
`superfile/theme/`, which superfile ships itself.

`.pi/` runtime state is gitignored via `.pi/.gitignore`: `auth.json`,
`models-store.json`, `sessions/`, `node_modules/`, and the `*.bak.*`
timestamped backups. Those are machine-local (credentials, pi's model cache,
session history) and stay out of the repo. `agent/settings.json` and
`agent/models.json` are tracked — they are the live provider catalog and user
settings, not runtime state — so the tracked `.pi/` holds the config,
extensions, skills, and prds that should follow a machine.

### Retired LLM providers

On 2026-08-30 three providers were declared dead and commented out of the
live configs (not deleted — the blocks survive as comments in
`.config/opencode/opencode.jsonc` and the pi extension files):

- `alibaba-tknplan` — Alibaba token plan lapsed ("Access to model denied"
  on every dispatch)
- `opencode-go` — OpenCode Go subscription lapsed
- `minimax` — MiniMax quota exhausted

To bring any of them back, retrieve the pre-retirement config from the
`providers/pre-retirement-2026-08-30` tag in this repo (and the matching tag
in the `~/.pi` repo for the pi-side extensions), re-enable the commented
blocks, and flip the provider to `true` in
`.config/opencode/provider-status.yml`. That file is the one record of which
providers are live, and `scripts/verify-provider-parity.sh` reads it: a
provider left at `false` is skipped for parity, and one marked `true` with no
parity entry fails the check. The tag is the last commit before the
retirement change, so
`git show providers/pre-retirement-2026-08-30:.config/opencode/opencode.jsonc`
has the full live config as it stood.

`.config/kilo/kilo.jsonc` used a differently-named provider block
(`alibaba-token-plan`, not `alibaba-tknplan`) for the same lapsed Alibaba
Token Plan account, and was missed by the original 2026-08-30 retirement
pass, so its default `model`/`small_model` kept pointing at the dead provider
until this was caught and fixed. It's now commented out the same way, with
`model`/`small_model` switched to `ollama-cloud/deepseek-v4-flash:0731` and
`ollama-cloud/gpt-oss:20b`.

`.config/rclone/rclone.conf`, `.config/msmtp/`, and `.config/protonmail/`
hold credentials and stay out entirely. `himalaya` is here only because its
config fetches the bridge password from `pass` at runtime rather than
storing it.

`abs` and `abs.service` are not here either. They belong to the
`always-be-sessioning` repo, which installs them itself.

## Secrets

Global secrets (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, and the like) don't
live in this repo at all, plaintext or otherwise. `pass` is the source of
truth, holding one entry, `global/env`, in dotenv format. A separate
`secret-management` repo owns the machinery around it and installs itself
straight into `$HOME` rather than through mise's dotfiles:

- `secrets-unlock` runs `pass show global/env` from a real terminal (the one
  interactive pinentry prompt required per boot) and writes the result to
  `$XDG_RUNTIME_DIR/secrets/global.env`, mode 600. That path is tmpfs, so the
  decrypted file never touches persistent disk and is gone on reboot.
- `~/.gnupg/gpg-agent.conf` sets a long cache TTL, which is what makes `pass`
  usable from non-interactive/spawned shells after the first unlock instead of
  failing with `Inappropriate ioctl for device`.
- `~/.config/fish/conf.d/secrets.fish` sources `global.env` unconditionally on
  every new shell, so it no longer matters whether the shell was opened under
  a particular directory.

Updating secrets after the initial `install-secrets`:

```fish
mise-sys secrets-sync   # pulls secret-management + password-store, re-links, adopts new pass entries
secrets-unlock          # if global/env changed, refreshes $XDG_RUNTIME_DIR/secrets/global.env (needs TTY)
```

Re-running `mise-sys install-secrets` will not pull updates -- it only clones
when the target directory is missing. `secrets-sync` is the update path:
`--ff-only` pulls for both repos, `install.sh` re-links any changed scripts,
and any new `pass` entries are adopted automatically: `ssh/shared` (private)
to `~/.ssh/id_ed25519` (`600`) + `ssh/shared.pub` to `~/.ssh/id_ed25519.pub`
(`644`) and `~/.ssh/authorized_keys` (`600`), and every entry under
`ssh/authorized_keys/*` (one pubkey line each) rebuilt into `authorized_keys`.

What this repo does contain is the consumer side: `fish_greeting`
(`.config/fish/functions/fish_greeting.fish`) checks whether `global.env`
exists and nags `secrets are locked! run secrets-unlock` if not, instead of a
fortune. Two narrower cases don't go through `pass show global/env` at all:

- `himalaya`'s config fetches its bridge password from `pass` directly at
  runtime, which is the only reason that config is tracked here instead of
  excluded like the other credential-holding configs above.
- `gh`'s `hosts.yml` holds OAuth tokens directly, not via `pass`, and stays
  gitignored rather than routed through the global-secrets flow.

### SSH keys in pass and tailnet trust

SSH pubkeys can live alongside secrets in the same encrypted store -- they are
not secret, but putting them in `pass` makes distribution explicit and
versioned rather than a manual `ssh-copy-id` per host.

**Current choice: single shared key in `pass` (`ssh/shared` + `ssh/shared.pub`).**
This host (`coding-workspace`) was the source: its `~/.ssh/id_ed25519`
(`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA+M...` at `~/.ssh/id_ed25519.pub:1`) was
stored as two `pass` entries via `pass insert -m ssh/shared < ~/.ssh/id_ed25519`
and `pass insert -m ssh/shared.pub < ~/.ssh/id_ed25519.pub`, committed and
pushed to `jeremysball/password-store` (`ssh/shared.gpg:1`, `ssh/shared.pub.gpg:1`).
`secrets-sync` now distributes both halves: private to `~/.ssh/id_ed25519`
(`600`, backed up as `~/.ssh/id_ed25519.bak.<epoch>` if it differs) and pub to
`~/.ssh/id_ed25519.pub` (`644`) and appended to `~/.ssh/authorized_keys`
(`600`) if missing, so every tailnet host can `ssh` every other without per-host
`authorized_keys` editing. Blast radius is total -- leaking one host leaks the
key for all -- which is acceptable for a single-user private tailnet where the
WireGuard layer already trusts every node. For multi-user or audit, prefer the
per-host pattern below.

Supported layout (one entry per pubkey, not one big blob):

- **Shared (active):** `ssh/shared` (private, multiline) + `ssh/shared.pub` (one
  line). `secrets-sync` handles both as above.
- **Per-host (also supported):** `ssh/authorized_keys/<hostname>` -- each entry's
  content is one line, e.g. `ssh-ed25519 AAA... jeremy@<host>` (what `cat
  ~/.ssh/id_ed25519.pub` prints). After `pass git pull`, `secrets-sync` rebuilds
  `~/.ssh/authorized_keys` from every entry under `ssh/authorized_keys/*`
  (deduped). So adding a host is `pass insert -m ssh/authorized_keys/<new-host>`
  on one machine, `pass git push`, then `mise-sys secrets-sync` on the others.

New host with the shared key (hands-free after first unlock):

```fish
git clone https://github.com/jeremysball/dotfiles ~/.dotfiles; cd ~/.dotfiles; ./init.sh
# init.sh clones mise-en-system and runs install-secrets (clones password-store)
mise-sys secrets-sync  # pulls ssh/shared + ssh/shared.pub, writes ~/.ssh/id_ed25519 (600) + authorized_keys (600)
secrets-unlock         # one pinentry prompt if global/env changed, then exec fish
ssh coding-workspace   # no ssh-copy-id needed
```

More idiomatic alternatives if you don't want to manage keys at all:

- **Tailscale SSH** (`tailscale set --ssh=true` + an ACL rule without `check`).
  When `RunSSH` is true, tailscaled itself is the SSH server and auth is via
  tailnet identity, not `authorized_keys`. Your current ACL uses
  `holdAndDelegate` (check mode), which is why you have to re-authenticate in a
  browser often -- every SSH is delegated to the control plane for approval.
  Switching the ACL to a plain `accept` (no `check` key) makes it hands-free:

  ```json
  {"action": "accept", "src": ["autogroup:members"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}
  ```

  Then `tailscale set --ssh=true` on each host and `tailscale up --ssh` persists.
  For fully headless hosts (containers, servers that can't do browser login),
  bring them up once with a reusable auth key (`tailscale up --authkey=tskey-... --ssh`)
  or an OAuth client, and disable key expiry (`tailscale set --key-expiry=0` or
  set the key to not expire at creation). That removes the frequent re-auth you
  are seeing while keeping Tailscale's identity-based auth.

- **SSH certificates (CA)** -- heavier, but the most principled for many hosts.
  One CA signs short-lived host/user certs; no `authorized_keys` distribution.
  Overkill for a personal tailnet unless you enjoy the setup.

For a personal tailnet where you control all nodes, either the single shared
key in `pass` (simplest) or Tailscale SSH without `check` (no keys to rotate)
are both reasonable. The `pass`-backed `authorized_keys` path above keeps
plain `ssh` working even when tailscaled is down, while Tailscale SSH keeps
auth in the control plane and works even if you lose a key.

## fish

One set of entries covers every machine. Anything a given host might not have
is guarded on the command it needs, so `conf.d/keychain.fish` does nothing on
a box without keychain installed and does not print an error either.

Host-specific setup goes in `conf.d/`, not in `config.fish`. fish sources
every `conf.d/*.fish` before `config.fish` runs, which is why `config.fish`
here is two lines of comment and nothing else.

### Plugins are not tracked here

Only `fish_plugins`, the manifest, is in git. The actual tide and fisher
function files are not. There used to be 85 of them checked in, and applying
the whole directory installed one machine's prompt onto every other machine
as a side effect (see the whole-directory-vs-per-file note at the top).

On a machine missing anything the manifest lists, `conf.d/fisher-bootstrap.fish`
fetches fisher, sources it, and runs `fisher update`. The prompt stays plain
fish default until it finishes.

The guard checks that every plugin in the manifest is installed, not only that
fisher exists. Guarding on fisher alone leaves a hole: fisher writes its own
function to disk before installing the rest, so an install that dies partway
satisfies the guard permanently and the missing plugins never get retried.

### fisher writes to fish_plugins, and mise points that at this repo

Every fisher subcommand that changes state (`install`, `update`, `remove`,
`uninstall`) rewrites `fish_plugins`. It writes **the set that is
installed**, not the set the file listed. That is `functions/fisher.fish` line
221, inside the block shared by all four subcommands.

Since mise symlinks the manifest into this repo, that write lands on tracked
content. Consequences worth knowing:

- Running `fisher install <x>` when tide is broken rewrites the manifest to
  only `<x>` and drops tide. This is why the bootstrap calls `fisher update`
  instead: update installs the manifest's contents first, so the rewrite is a
  no-op. It is not that update avoids writing, because it does not.
- `fisher remove` of the last remaining plugin runs `rm -f $fish_plugins`,
  which deletes the mise-managed symlink. The repo file survives.
  `mise bootstrap dotfiles apply ~/.config/fish/fish_plugins` to repair.
- Any `fisher install` you run by hand dirties the repo. That is fine and
  arguably correct, since the manifest should track what you have. Expect
  `git status` to show it.

Also be careful adding files to `functions/`. If tide ships a function by the
same name, its install fails on the collision and you get a broken prompt with
a confusing error. That happened with `fish_mode_prompt.fish`.

## mise

[mise](https://mise.jdx.dev/) manages user-space CLI tools and language
runtimes from `.config/mise/config.toml`, the same file that holds the
`[dotfiles]` table. `mise install` reads its `[tools]` table and installs
everything listed. It resolves tools through its own registry, then aqua,
then ubi, then asdf plugins, so most things work by bare name, and anything
with a GitHub release binary works via `ubi:owner/repo`.

Some things stay on pacman on purpose, and the config comments say why:

- `fish` is the login shell and has to be in `/etc/shells`
- `grc` ships `/etc/grc.fish`, which `conf.d/grc.fish` sources by absolute path
- `ripgrep` is a hard dependency of the pacman `opencode` package, so the two
  move together or not at all
- `ghc` and `cabal` are left to ghcup, which is already managing six GHC
  versions side by side. mise installs ghcup and stops there.

### Per-project environments

Drop a `mise.toml` in a project to get a virtualenv and `.env` loading on cd:

```toml
[env]
_.python.venv = { path = ".venv", create = true }
_.file = ".env"
```

That creates the venv if it is missing, puts `.venv/bin` on PATH, sets
`VIRTUAL_ENV`, and loads `.env`. You have to run `mise trust` in the directory
once before mise will read the file, since otherwise any repo you clone could
set environment variables on you the moment you cd into it.

## doom

Doom Emacs config: `config.el`, `init.el`, `packages.el`. Doom keeps user
config in `~/.config/doom` and the framework itself in `~/.config/emacs`,
which is a clone of doomemacs and is not tracked here. On a fresh machine,
install Doom first with `mise-sys install-doom-emacs` (see "Setting up a
fresh machine" above), then run `mise bootstrap dotfiles apply --force
~/.config/doom/config.el ~/.config/doom/init.el ~/.config/doom/packages.el`
to overwrite the starter template Doom's installer just generated with the
tracked, customized versions. `--force` is required here specifically:
Doom's installer writes real starter content, not empty files, so it always
conflicts with the tracked source and a plain `apply` refuses.

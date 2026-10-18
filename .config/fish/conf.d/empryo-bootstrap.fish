# Empryo installs to ~/.empryo/ via its upstream installer
# (https://empryo.com/install.sh), not via mise's tool registry. mise only
# owns user-space CLIs it can resolve through aqua/ubi/registry backends, and
# Empryo's release assets are named `soulforge-*` (the upstream repo name)
# served from dl.empryo.com, so neither ubi nor aqua would put an `empryo`
# binary on PATH. This file just exposes ~/.empryo/bin once the bootstrap
# task (`mise run install-empryo`) has been run at least once on this host.
#
# Gated on the installed binary instead of `command -q empryo`: the first
# post-install session has the binary on disk but not on PATH, so a PATH
# lookup would miss it and the dir would never get added. `test -x` sees it
# from disk, and fish_add_path persists via fish_user_paths, so later
# sessions keep it.
if test -x $HOME/.empryo/bin/empryo
    fish_add_path --append --path $HOME/.empryo/bin
end
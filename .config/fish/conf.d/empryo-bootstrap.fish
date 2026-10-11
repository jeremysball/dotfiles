# Empryo installs to ~/.empryo/ via its upstream installer
# (https://empryo.com/install.sh), not via mise's tool registry. mise only
# owns user-space CLIs it can resolve through aqua/ubi/registry backends, and
# Empryo's release assets are named `soulforge-*` (the upstream repo name)
# served from dl.empryo.com, so neither ubi nor aqua would put an `empryo`
# binary on PATH. This file just exposes ~/.empryo/bin once the bootstrap
# task (`mise run install-empryo`) has been run at least once on this host.
#
# `command -q empryo` so the line no-ops on hosts that haven't installed
# Empryo yet, instead of leaving a dead directory on PATH.
if command -q empryo
    fish_add_path --append --path $HOME/.empryo/bin
end
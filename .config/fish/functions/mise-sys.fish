# mise-en-system is the dotfiles repo's mise-en-system/ submodule. This file
# is symlinked into ~/.config/fish/functions from that same repo, so resolving
# the symlink finds the repo wherever it was cloned, without hardcoding
# ~/.dotfiles.
function mise-sys --description "Run a mise-en-system task (mise -C <dotfiles>/mise-en-system run ...)"
    set -l repo (path dirname (path dirname (path dirname (path dirname (path resolve (functions --details mise-sys))))))
    set -l dir $repo/mise-en-system
    if not test -f $dir/mise.toml
        echo "mise-sys: $dir/mise.toml not found: run ./init.sh (or git submodule update --init mise-en-system) in $repo first" >&2
        return 1
    end
    mise -C $dir run $argv
end

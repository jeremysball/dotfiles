# 00-path — runs before 01-mise by design. fish sources conf.d/*.fish
# alphabetically, so PATH must be set before 01-mise checks `command -q mise`.
# On a fresh machine fish inherits system PATH only
# (/usr/local/sbin:/usr/local/bin:/usr/bin:/bin) with no ~/.local/bin where
# `mise` lives (curl https://mise.run | sh). Without this file first, activation
# never runs and no mise tool (cowsay, catbow, etc.) is visible at fish_greeting.
# fish_add_path dedupes, so PATH doesn't grow across nested shells.

# mise binary — must be on PATH for 01-mise even in non-interactive shells
if not contains -- $HOME/.local/bin $PATH
    fish_add_path --global --prepend $HOME/.local/bin
end
if test -d /home/linuxbrew/.linuxbrew/bin; and not contains -- /home/linuxbrew/.linuxbrew/bin $PATH
    fish_add_path --global --prepend /home/linuxbrew/.linuxbrew/bin
end

# Userspace CUDA toolkit (NVIDIA redist tarballs, installed without sudo on
# sisyphus). nvcc 12.8 rejects gcc > 14, so a conda-forge gcc 14 sits beside it
# and NVCC_CCBIN points nvcc at it. No-op on any machine without these dirs.
# Not gated on is-interactive: builds that need nvcc (uv pip install of
# llama-cpp-python, `fish -c` scripts) run in non-interactive shells.
set -l cuda_base (set -q XDG_DATA_HOME; and echo $XDG_DATA_HOME; or echo $HOME/.local/share)/cuda
if test -x $cuda_base/12.8/bin/nvcc
    fish_add_path --global --append --path $cuda_base/12.8/bin
    set -l cuda_ccbin $cuda_base/gcc14/bin/x86_64-conda-linux-gnu-g++
    if test -x $cuda_ccbin
        set -gx NVCC_CCBIN $cuda_ccbin
    else if status is-interactive
        # Without it nvcc falls back to the system gcc, which 12.8 rejects.
        echo "00-path: nvcc found but $cuda_ccbin is missing; NVCC_CCBIN not set" >&2
    end
end

# go-installed tools (bumblebee, catbow fallback, etc.) — only needed interactively
if status is-interactive
    fish_add_path --global --append --path $HOME/go/bin
end

# Personal Bash customizations. Source after the distribution's .bashrc.
case $- in
    *i*) ;;
    *) return ;;
esac

# Loading the fragment repeatedly should not reinitialize interactive plugins.
[ "${__WORKSTATION_BASH_LOADED:-}" = 1 ] && return
__WORKSTATION_BASH_LOADED=1

#prompt
set_prompt() {
    local last_cmd=$?
    local arrow_color="\[\e[1;32m\]"
    if [ $last_cmd -ne 0 ]; then
        arrow_color="\[\e[1;31m\]"
    fi
    local cyan="\[\e[1;36m\]"
    local blue="\[\e[1;34m\]"
    local red="\[\e[1;31m\]"
    local yellow="\[\e[1;33m\]"
    local green="\[\e[1;32m\]"
    local reset="\[\e[0m\]"

    # 1. Fetch the active Conda environment if present
    local conda_info=""
    if [ -n "$CONDA_DEFAULT_ENV" ]; then
        conda_info="(${green}${CONDA_DEFAULT_ENV}${reset}) "
    fi

    local git_info=""
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD 2> /dev/null)
    if [ -n "$branch" ]; then
        local dirty=""
        if [ -n "$(git status --porcelain 2> /dev/null)" ]; then
            dirty=" ${yellow}✗"
        fi
        git_info=" ${blue}git:(${red}${branch}${blue})${dirty}"
    fi

    # 2. Prepend conda_info to PS1
    PS1="${conda_info}${arrow_color}➜ ${cyan}\W${git_info}${reset} "
}

PROMPT_COMMAND=set_prompt

lsofc() {
	sudo lsof -i :"$1"
}

fkill() {
	sudo kill -9 "$@"
}

freee() {
  local port=$1
  if sudo fuser -k "$port/tcp"; then
	echo "Successfully killed processes using port $port"
  fi
}

tree() {
    # Call the real tree, always adding the ignore pattern first
    command tree -I '__pycache__|node_modules|.git|.venv|dist|build|coverage|.pytest_cache|venv' "$@"
}

# Optional integrations. Missing tools are left for their own installers.
if [ -n "${CONDA_ROOT:-}" ] && [ -x "$CONDA_ROOT/bin/conda" ]; then
    __workstation_conda="$CONDA_ROOT/bin/conda"
elif command -v conda >/dev/null 2>&1; then
    __workstation_conda=conda
fi
if [ -n "${__workstation_conda:-}" ]; then
    __workstation_conda_setup="$("$__workstation_conda" shell.bash hook 2>/dev/null)"
    if [ $? -eq 0 ]; then
        eval "$__workstation_conda_setup"
    fi
    unset __workstation_conda __workstation_conda_setup
fi

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

# Add only installed tools and avoid duplicating PATH entries on reload.
__workstation_path_append() {
    [ -d "$1" ] || return 0
    case ":$PATH:" in
        *":$1:"*) ;;
        *) export PATH="$PATH:$1" ;;
    esac
}
__workstation_path_append "$HOME/.foundry/bin"
__workstation_path_append /usr/local/go/bin
__workstation_path_append "$HOME/.local/share/yabridge"
if command -v go >/dev/null 2>&1; then
    __workstation_path_append "$(go env GOPATH)/bin"
fi
unset -f __workstation_path_append

if [ -f "$HOME/.local/share/blesh/ble.sh" ]; then
    source "$HOME/.local/share/blesh/ble.sh"
fi

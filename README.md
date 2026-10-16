# Workstation setup

Personal Bash, Git, GNOME and VS Code preferences, with a previewable restore
command and local backups. Captured from Ubuntu 24.04 / GNOME 46 on 2026-10-16.

Clone this repository onto the destination machine. A link alone does not apply
settings, and this repository is not an agent skill. An agent can use the README
to run the same commands you would run yourself.

```bash
git clone git@github.com:jamwujustyle/workstation-setup.git
cd workstation-setup
python3 setup.py
python3 setup.py apply
```

The first command inside the repository previews changes. `apply` writes user
preferences; it does not install software. Run it as your regular logged-in
user, without `sudo`. On GNOME, use the system Python (`/usr/bin/python3`) if
your active Python environment does not have `gi` installed. Close VS Code
before applying its settings, then reopen it and start a new terminal.

## What is restored

| Component | Contents | Destination behavior |
| --- | --- | --- |
| `shell` | Prompt, port/process helpers, `tree` exclusions, Readline, optional tool initialization | Adds managed blocks to `.bashrc` and `.inputrc`; keeps existing content |
| `git` | Pull strategy and LFS filters | Adds an include to `.gitconfig`; keeps existing identity and credentials |
| `editor` | VS Code settings and keybindings | Replaces the two user files after backing them up |
| `desktop` | Keyboard shortcuts, layouts, theme, dock, mouse, Terminal and power preferences | Applies reviewed GSettings keys supported on the destination |

```bash
python3 setup.py plan --only shell,git,editor
python3 setup.py apply --only shell,git,editor
python3 setup.py apply --only editor --code-user-dir /path/to/editor/User
```

The GNOME profile includes English/Russian layouts with Alt+left Shift, F7/F8
media navigation, Super+V for Clipboard Indicator, and Terminal Ctrl+C/Ctrl+V.
It also disables screen idle blanking and automatic AC suspend. Review those
choices before applying them on a laptop.

Desktop restore checks schemas, types, writable keys and dependencies. Missing
themes, extensions, applications or schemas are reported and skipped. Installed
favorites and compatible extensions are merged with existing entries. Terminal
appearance is applied to the destination's default profile; unrelated profiles
are preserved. Open GNOME Terminal once if no default profile exists. Re-run
`apply` after installing missing dependencies. Some extensions require logging
out and in.

## Install software separately

These commands preview by default. Add `--apply` to install the selected group.
APT installation asks for sudo through apt; it does not run the settings tool as
root. Package removal is disabled. Run `sudo apt-get update` first on a new
Ubuntu installation.

```bash
python3 setup.py packages cli
python3 setup.py packages desktop
python3 setup.py packages development
python3 setup.py snaps
python3 setup.py extensions

# Example: install the reviewed CLI dependencies.
python3 setup.py packages cli --apply
```

Install VS Code before its extensions. The desktop group supplies GNOME tooling
and fonts. Clipboard Indicator, external package repositories and optional
runtimes have their own installation steps in [Software](docs/software.md).
Snap channels are captured preferences, not version locks. Already installed
Snaps keep their channel. Extension installation uses available releases and
leaves installed extensions in place.

`inventory/` records the observed machine, including software beyond the curated
install groups. It is reference material, not an instruction to reinstall every
service, driver or package.

## Backups and undo

Each apply that changes anything saves a private backup beneath
`~/.local/state/workstation-setup/backups/` (or `$XDG_STATE_HOME`). The command
prints its exact path. Backups contain the original local files, including any
private content they already held, and must stay outside this repository.

```bash
python3 setup.py rollback /path/printed/by/apply
python3 setup.py rollback /path/printed/by/apply --apply
```

Rollback previews first and refuses to overwrite later edits. It restores
explicit GNOME values or resets keys that previously inherited defaults.
Unchanged repeated applies create no backup. If an apply stops partway through,
use its printed backup path to undo completed changes. Symbolic-link targets
are rejected so another dotfile manager's files are not overwritten indirectly.
Backups undo preferences only; they do not uninstall software.

## Maintain the setup

Edit the reviewed files in `config/`, preview, apply, and commit the changes you
want to reuse. `git pull --ff-only` updates the repository; applying remains an
explicit step. There is deliberately no whole-home or whole-dconf export:
credentials, histories, browser sessions, private keys, project files, wallpaper
paths and hardware state are outside this snapshot. The optional Fish fragment
is retained for reference and is not applied by default.

Keep agent policies in the separate
[agent-playbook repository](https://github.com/jamwujustyle/agent-playbook).
Keep private per-machine additions in your local configuration, outside this
repository. The original audit and existing configuration quirks are recorded
in [Audit](docs/audit.md).

## Scope and validation

This is an Ubuntu/GNOME baseline, not a cross-platform system image. Bash and
editor files can be reused elsewhere after reviewing their paths and available
tools; macOS, Windows and other desktop environments are not verified targets.
Ubuntu's installer file automates OS installation; it does not export these
personal application preferences. See the official
[Ubuntu Desktop installation guide](https://ubuntu.com/desktop/docs/en/24.04/tutorial/install-ubuntu-desktop/).

Run the focused checks without touching live settings:

```bash
python3 -m unittest discover -s tests -v
bash -n config/shell/bashrc.bash
```

Validation covers isolated temporary-home restore/rollback and GNOME settings
validation. A complete reinstall on a fresh machine has not been tested.

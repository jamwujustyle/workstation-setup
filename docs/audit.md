# Workstation settings audit

Inspected on 2026-10-16. This is a selective, sanitized export of preferences,
not a system image or a backup of application data. Live configuration has not
been changed by this audit.

## Shell and Git

- Bash uses a green/red command-status arrow, current directory, Git branch and
  dirty marker, and a Conda environment indicator.
- Preserved helpers: `lsofc` inspects a port; `fkill` sends SIGKILL through sudo;
  `freee` terminates processes using a TCP port; `tree` excludes common generated
  directories. The `freee` message now expands its port variable correctly.
- Optional integrations: ble.sh, NVM, Conda, Go, Foundry, and yabridge. Missing
  integrations are skipped. Conda is discovered through PATH or explicit
  `CONDA_ROOT`; tool directories are added only when present, without duplicates.
- The Bash fragment is sourced once per interactive shell. Distribution startup
  files remain in place. Readline disables its bell.
- Git retains LFS filters and `pull.rebase=merges`. Author identity and credential
  storage are configured separately on each machine.

## VS Code

Captured 78 user settings, 24 keybinding entries, and 38 installed extensions.
Both extension IDs and observed versions are recorded; extensions and settings
may behave differently across releases.

Preferences include Fira Code ligatures, a custom terminal palette, Dark Modern,
vscode-icons, format-on-save, language formatters, autosave on focus change,
word wrapping, and terminal cursor styling.

Custom bindings include terminal Ctrl+C/Ctrl+V, Ctrl+Left/Right word movement,
Ctrl+Shift+Up/Down selection, Ctrl+Backquote terminal toggle, and removal of several
Shift+Enter execution bindings. Existing bindings are preserved exactly in
meaning, including disabled bindings.

Two existing quirks are recorded rather than silently rewritten:

- F1 has both an explicit command binding and a matching removal entry.
- Go configuration contains a nested `[go]` section and tool settings within the
  language override; some entries may not take effect there.

## Dependencies and portability

Fira Code, `git-lfs`, and Fish were not installed when inspected, despite related
settings being present. Fish/Starship configuration is optional. The Bash
integrations need their tools installed separately; this export does not include
Conda environments, NVM runtimes, plugin binaries, or development dependencies.

Linux shell paths and application integrations are intended for Linux. VS Code
also retains generic Windows terminal profiles already in the source settings;
those profiles require their respective tools and installations. A settings
snapshot cannot reproduce hardware, application sessions, or every operating
system's behavior.

## Other configuration inspected

The optional `config/optional/tmux.conf` snapshot preserves Vim-style copy mode:
`v` starts selection, Ctrl+V toggles rectangular selection, and `y` copies through
`xclip` to the X clipboard. The earlier redundant `y` binding and incomplete
commented example were omitted; the effective binding is unchanged. To apply
manually, merge these lines into an existing `~/.tmux.conf` or source this file
from it. This clipboard command requires `xclip` and an X/XWayland display; it is
not a native Wayland clipboard integration.

The optional `config/optional/sublime-preferences.json` snapshot contains font
size 14 and disabled update checks. Merge those keys into Sublime Text's user
preferences if desired; the restore CLI does not change Sublime settings.

`.profile` contains the standard Ubuntu Bash startup and user-bin PATH setup;
no personal additions were found. No `.bash_aliases`, WezTerm, Kitty, Alacritty,
or Starship configuration file was found in their inspected default locations.

## Excluded data

Excluded API credentials, a credentialed database shortcut, Git identity and
credential-storage configuration, a project-specific database helper, temporary
generated instruction paths, and a machine-specific protoc executable path.
No shell history, browser profiles, application auth/session stores, private
keys, or project files are included. The existing local settings were left intact.

## Validation

Bash syntax and an interactive startup with an empty temporary HOME passed.
VS Code files parse as JSON. Exported content was checked against credential
values from the inspected source files without including those values in this
report. These checks validate the bundle; they do not claim that a fresh-machine
restore or all application behavior has been exercised.

## GNOME desktop and terminal

Captured 37 selected preferences from Ubuntu 24.04.5 LTS, GNOME Shell 46.0,
using Wayland. Default keyboard bindings were left to the target desktop;
explicit personal changes and their dependencies are recorded.

| Area | Captured preference |
| --- | --- |
| Keyboard layouts | English (US) and Russian; Alt + left Shift switches layouts |
| Media keys | F7 previous track; F8 next track |
| Clipboard | Super + V opens Clipboard Indicator; the conflicting GNOME message-tray binding is cleared only when the compatible extension is available |
| Terminal keys | Ctrl + C / Ctrl + V copy/paste; Ctrl + = zooms in; Ctrl + Shift + T/W opens/closes a tab |
| Terminal appearance | Black background, white text, no audible bell, explicit profile colors |
| Appearance | Dark color scheme with Yaru olive dark GTK/icon themes |
| Dock and desktop icons | Fixed left dock, full height, 24-pixel icons; Home icon hidden |
| Pointer and touchpad | Mouse speed approximately -0.2; two-finger touchpad scrolling enabled |
| Idle behavior | Automatic screen blanking disabled; automatic suspend on AC disabled |

There are no GNOME custom-command shortcuts. The terminal Copy binding takes
Ctrl + C away from its usual shell-interrupt role when handled by the GUI.
The dock records Spotify and `code.desktop`; `code.desktop` was absent from the
inspected launchers, so restore skips that stale favorite until it is installed.
Other target favorites and enabled extensions are preserved.

Clipboard Indicator version 71 declares GNOME 46–50 compatibility. The installed
Ubuntu Dock, AppIndicators, Desktop Icons NG, and Tiling Assistant declare GNOME
45/46 compatibility. Restore uses target-installed versions and checks declared
compatibility. Extension-managed tiling overrides and version bookkeeping are
excluded so a missing extension cannot disable native tiling by accident.
Terminal colors are applied to the destination's existing default profile; the
profile list and default selection are preserved.

Local wallpaper paths and images, app-grid ordering, recent input sources,
Num Lock state, hardware power-profile state, and terminal profile labels are
not exported. Clipboard contents/history were not read or copied.

Desktop regression tests run in child processes with `GSETTINGS_BACKEND=memory`.
They cover captured value validation, apply/restore, implicit versus explicit
defaults, stale-write and rollback conflicts, profile adaptation, absent themes
and extensions, merges, preflight failure, and recovery from a partial failure.
The read-only source-machine preview reported zero desktop changes. No live
settings were changed, and a fresh-machine graphical session has not been tested.

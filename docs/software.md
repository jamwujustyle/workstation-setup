# Software and portability

The snapshot was inspected on Ubuntu 24.04.5 LTS, amd64, on 2026-10-16.
Versions in `inventory/` describe the observed machine; they are not a lockfile
or a promise that the same builds remain available.

## Package groups

- `packages/cli.txt`: the selected terminal utilities and shell dependencies.
  `lsof` supports `lsofc`; `psmisc` supplies `fuser` for `freee`.
- `packages/desktop.txt`: GNOME configuration tools, terminal, audio controls,
  notifications, Python GObject bindings, and configured fonts.
- `packages/development.txt`: compiler/build tools, language prerequisites,
  database clients, media/PDF tools, and Ansible.
- `packages/snaps.json`: nine application snaps with their observed channels
  and classic-confinement flags. Spotify tracks `latest/candidate`; this is
  deliberately retained instead of silently changing it to stable. Snap base,
  graphics/runtime, store, and system-integration packages are excluded.
- `packages/vendor.txt`: reference only. The setup tool does not add these
  repositories or install their services automatically.

`git-lfs` and `fonts-firacode` were absent during inspection but are included
because the captured Git filters and editor font settings reference them.
JetBrains Mono was installed. The 3270 Nerd Font family was installed separately.

`inventory/apt-manual.txt` contains only currently installed packages marked
manual, with architecture suffixes normalized and duplicate names removed.
It is an audit reference, not a replay list: it includes machine-specific and
historical selections. Fish and Flatpak have residual dpkg configuration but
are not installed. No server, driver, or security-tool collection is added to
the curated install groups. APT preview uses simulation; the destination's
repositories and dependency resolver determine the available versions.
See the [APT marking](https://manpages.ubuntu.com/manpages/noble/man8/apt-mark.8.html)
and [simulation](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html) manuals.

## Vendor applications

Use the vendor's instructions for the destination Ubuntu release and architecture:

| Observed application | Installation source |
| --- | --- |
| Docker Engine, CLI, containerd, Buildx, Compose plugin | [Docker's Ubuntu repository guide](https://docs.docker.com/engine/install/ubuntu/) |
| Visual Studio Code | [Microsoft's Linux installation guide](https://code.visualstudio.com/docs/setup/linux) |
| Google Chrome | [Google's installation guide](https://support.google.com/chrome/answer/95346?hl=en&co=GENIE.Platform%3DDesktop) |
| Google Antigravity | [Official downloads](https://antigravity.google/download) |
| Tailscale | [Official Linux guide](https://tailscale.com/docs/install/linux) |

The `chatgpt` desktop package was also installed; obtain its installer through
the vendor distribution available to your account. App logins and account state
are not part of this setup. Installed package versions are in
`inventory/vendor-versions.json`.

The old `docker-compose` v1 package and the current `docker compose` plugin
coexist in the snapshot. Do not replay that combination by copying the full
package inventory; Docker's guide identifies conflicting distribution packages.
Docker service setup, groups, and Tailscale enrollment remain explicit steps.

## Desktop dependencies

After installing the desktop package group, open **Extension Manager**, choose
**Browse**, and search for **Clipboard Indicator** by Tudmotu. Install a release
compatible with the destination's GNOME major version (46 on the captured
desktop). Its UUID is `clipboard-indicator@tudmotu.com`; check the
[official GNOME registry entry](https://extensions.gnome.org/extension/779/clipboard-indicator/)
or [upstream repository](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator)
to identify the correct extension. Log out and in if needed, then rerun
`python3 setup.py apply --only desktop` to restore its settings and shortcut.
The setup tool's `extensions` command installs VS Code extensions, not GNOME
Shell extensions. Clipboard history is not restored.

The captured `Yaru-olive-dark` GTK theme and icons come from
`yaru-theme-gtk` and `yaru-theme-icon`, both installed on the inspected Ubuntu
desktop. They are Ubuntu desktop baseline dependencies rather than additions
in this repository's desktop package group. On a minimal Ubuntu installation,
install those two packages if needed. On other GNOME distributions, provide a
compatible Yaru theme or keep the destination theme; missing theme selections
are skipped during restore.

## Language tools and optional shell integrations

| Component | Observed state | Restore source |
| --- | --- | --- |
| nvm / Node / npm | nvm 0.39.7; Node 22.22.0; npm 10.9.4; nvm default `22` | [nvm installation instructions](https://github.com/nvm-sh/nvm#installing-and-updating); after installing nvm, use `nvm install 22` and `nvm alias default 22` |
| Go | 1.26.0, installed under `/usr/local/go` | [Go installation guide](https://go.dev/doc/install); select the destination architecture |
| Python | System Python 3.12.3; no pyenv-managed versions detected | Ubuntu packages in the development group |
| ble.sh | 0.4.0-devel4+2f564e63 | [Upstream installation instructions](https://github.com/akinomyoga/ble.sh#installation) |
| Foundry | forge, cast, anvil 1.5.1-stable | [Official Foundry toolchain manager](https://github.com/foundry-rs/foundryup) |
| Starship | 1.24.1 installed; the Bash fragment keeps the existing custom prompt | [Official installation guide](https://starship.rs/guide/) |
| 3270 Nerd Font | Installed, including Mono and Propo variants | [Nerd Fonts release archives](https://github.com/ryanoasis/nerd-fonts#font-installation) |
| yabridge | yabridgectl 5.1.1 | [Upstream installation instructions](https://github.com/robbert-vdh/yabridge#installation) |

The Bash fragment activates optional integrations only when their files or
commands exist. Installing these tools is separate from restoring the fragment.
For ble.sh, choose the upstream installation prefix `~/.local` so the loader is
installed at `~/.local/share/blesh/ble.sh` (for a source build, use
`make -C ble.sh install PREFIX=~/.local`). The captured Bash fragment already
sources that file; do not add a second source line to `.bashrc`.
Node's `22` alias follows that major version; use `nvm install 22.22.0` if the
recorded patch version is specifically needed. Existing Conda support remains
conditional; a new Conda distribution is not provisioned. No Foundry wallet
state or audio-plugin content is copied.

## Ubuntu's installer import

Ubuntu 24.04's graphical installer accepts an Autoinstall YAML configuration.
That configures the OS installation itself. This repository now includes an
[Autoinstall profile](ubuntu-install.md) that installs selected dependencies and
queues preference/policy setup for the first graphical login. It keeps disk and
account choices interactive. The standalone restore commands also work on an
existing compatible desktop.
See [Ubuntu's installation guide](https://ubuntu.com/desktop/docs/en/24.04/tutorial/install-ubuntu-desktop/)
and [Canonical's Autoinstall introduction](https://canonical-subiquity.readthedocs-hosted.com/en/latest/intro-to-autoinstall.html).

Apply GNOME settings as the logged-in desktop user with a session bus, not as
root. Schemas, extensions, themes and applications must exist on the target;
restoring their preferences does not install them. Raw dconf imports cannot
validate setting types, whereas GSettings uses installed schemas.
[GNOME's GSettings guide](https://teams.pages.gitlab.gnome.org/Websites/help.gnome.org/system-admin-guide/gsettings-browse.html)
and the [dconf manual](https://manpages.ubuntu.com/manpages/noble/man1/dconf.1.html)
describe these requirements.

Bash/editor preferences are broadly reusable with compatible tools. GNOME
shortcuts require GNOME, and these package groups target Ubuntu 24.04.
Other desktops, Linux distributions, Windows and macOS need corresponding
package and desktop adapters; this is not a full machine image.

# Use from the Ubuntu USB installer

Ubuntu calls its installation configuration **Autoinstall**. It uses YAML.
This repository's `autoinstall.yaml` connects that installer to the workstation
preferences and the separate agent-playbook repository.

## Install

1. Boot a current Ubuntu Desktop 24.04 LTS USB and connect to the internet.
2. Choose **Automated Installation** at the installation-type screen.
3. Paste this raw configuration URL into the configuration-address field:

   ```text
   https://raw.githubusercontent.com/jamwujustyle/workstation-setup/master/autoinstall.yaml
   ```

4. Continue through the normal questions, including disk selection, partitioning,
   encryption, account and password. This profile uses
   `interactive-sections: ['*']`; it contains no disk layout or account defaults.
5. Complete the installation, remove the USB, reboot and sign in to GNOME.
   First-login setup applies the saved preferences and installs the agent policies.

Use the **raw YAML URL**, not the GitHub repository page or `.git` address.
Alternatively, save `autoinstall.yaml` onto accessible removable storage and
enter its mounted `file:///…/autoinstall.yaml` URI in the import field. The
profile still needs internet access for Ubuntu packages and the repositories.
No custom Ubuntu ISO or existing GitHub SSH key is required.

## What runs when

During OS installation, Ubuntu installs the curated CLI and desktop package
groups, downloads pinned commits of both public repositories over HTTPS into
`/opt`, and creates a first-login entry for the single account created by the
installer. If the account cannot be identified unambiguously, staging stops
rather than selecting an arbitrary user.

At the first graphical login, the setup runs as that user with the desktop's
session bus. It copies both Git checkouts into
`~/.local/share/workstation-setup/repos/`, applies workstation preferences with
the existing backup mechanism, then runs agent-playbook's installer. That
installer places the global rules and skills in their normal user locations.
Both repositories keep their HTTPS remotes for subsequent reviewed updates.
No settings are applied to root's desktop or home directory.

This installs CLI/desktop dependencies and preferences. Vendor applications,
VS Code extensions, Snap apps and optional runtimes retain their separate
[software installation steps](software.md). Missing desktop themes/extensions/apps
are reported as skips. In particular, Clipboard Indicator must be installed
before its Super+V shortcut can be restored; reapply desktop preferences afterward.
A successful bootstrap is not proof that every optional application is installed.

## Status, recovery and updates

The private first-login log is
`~/.local/state/workstation-setup/first-login.log`. Setup records completion only
after both installers succeed. A failure is recorded rather than retried on
an endless loop of logins. After resolving the logged problem, run:

```bash
/usr/bin/python3 /opt/workstation-setup/installer/first_login.py --retry
```

Use workstation setup's printed backup path to roll back its preferences.
Agent-playbook preserves conflicting existing instructions and reports them;
it does not replace a different nonempty rule file.

The YAML pins both repositories to reviewed commits. Updating a branch does not
silently change the code executed by an existing YAML file. To publish a new
profile, first commit and verify the installer source, then regenerate the YAML
with that full commit hash and a reviewed playbook hash:

```bash
python3 installer/render_autoinstall.py \
  --revision FULL_WORKSTATION_COMMIT \
  --playbook-revision FULL_PLAYBOOK_COMMIT > autoinstall.yaml
```

Commit the generated file as a second batch. Do not put usernames, password
hashes, private SSH keys or machine-specific disk layouts in the public profile.

## Compatibility and verification

Target: Ubuntu Desktop 24.04 LTS with GNOME. The profile keeps all interactive
questions enabled. Desktop importer, wildcard handling and the first-login
approach were checked against Canonical's implementation and desktop standards:

- [Ubuntu installation guide](https://ubuntu.com/desktop/docs/en/24.04/tutorial/install-ubuntu-desktop/)
- [Ubuntu 24.04 GUI mapping for interactive sections](https://github.com/canonical/ubuntu-desktop-provision/blob/ubuntu/24.04/packages/ubuntu_bootstrap/lib/services/installer_service.dart#L61-L84)
- [Subiquity 24.04.1 wildcard expansion](https://github.com/canonical/subiquity/blob/24.04.1/subiquity/server/server.py#L166-L180)
- [Autoinstall late-command contract](https://github.com/canonical/subiquity/blob/24.04.1/doc/reference/autoinstall-reference.rst#L883-L893)
- [XDG desktop autostart specification](https://specifications.freedesktop.org/autostart/latest/)

Automated checks cover configuration generation, isolated account staging,
first-login orchestration, preference backup/rollback and GNOME's memory backend.
The generated YAML is also checked against the published Subiquity schema.
A complete USB/VM installation has not been executed. Older installer builds
have had [partial-autoinstall UI issues](https://github.com/canonical/ubuntu-desktop-provision/issues/926);
use a current point-release image and inspect the installation summary normally.

# Workstation configuration maintenance

This repository contains reviewed personal preferences and optional package
manifests. Keep configuration, installation, and observed inventory distinct.

- Review individual keys and lines when refreshing the snapshot. Never copy an
  entire home/config directory or unfiltered dconf dump into Git.
- Preserve private credentials, identities, hostnames, histories and local
  project paths outside the published snapshot. Do not print source secrets
  during comparison or validation.
- Test restore and rollback with temporary HOME/XDG directories and an isolated
  GSettings backend. Do not test by applying changes to the live desktop.
- Preserve destination content outside managed shell/Git blocks. Back up editor
  replacements and explicitly set desktop values before modifying them.
- Document compatibility and missing dependencies. Do not broaden package
  installation to all entries in the observed inventory.

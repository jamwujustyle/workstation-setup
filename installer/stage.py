#!/usr/bin/env python3
"""Prepare one user's first-login restore after installation; preview by default."""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import pwd
import stat
import sys
import tempfile

AUTOSTART_NAME = 'workstation-first-login.desktop'
DESKTOP_ENTRY = b'''[Desktop Entry]
Type=Application
Version=1.0
Name=Restore workstation preferences
Comment=Apply the prepared workstation configuration for this account.
Exec=/usr/bin/python3 /opt/workstation-setup/installer/first_login.py
TryExec=/usr/bin/python3
Terminal=false
OnlyShowIn=GNOME;ubuntu;
X-GNOME-Autostart-enabled=true
NoDisplay=true
'''
REQUIRED_SCRIPTS = (
    '/opt/workstation-setup/installer/first_login.py',
    '/opt/agent-playbook/install.py',
)


@dataclass(frozen=True)
class Account:
    name: str
    uid: int
    gid: int
    home: str
    shell: str


@dataclass(frozen=True)
class Plan:
    target: Path
    username: str
    create: bool


def checked_path(path, *, kind=None):
    """Reject links, including dangling links and linked parent directories."""
    if not path.is_absolute():
        raise ValueError('Expected an absolute target path')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f'Refusing symlink: {part}')
    if path.exists():
        if kind == 'directory' and not path.is_dir():
            raise ValueError(f'Expected a directory: {path}')
        if kind == 'file' and not path.is_file():
            raise ValueError(f'Expected a regular file: {path}')
    return path


def inside(target_root, absolute_path):
    root = checked_path(Path(target_root).absolute(), kind='directory')
    value = PurePosixPath(absolute_path)
    if not value.is_absolute() or '..' in value.parts:
        raise ValueError('Expected an absolute path without traversal')
    return root.joinpath(*value.parts[1:])


def eligible(account, target_root):
    if not 1000 <= account.uid < 60000:
        return False
    if not account.name or '/' in account.name or account.name in ('.', '..'):
        return False
    if account.home != f'/home/{account.name}':
        return False
    if Path(account.shell).name in ('nologin', 'false'):
        return False
    home = inside(target_root, account.home)
    checked_path(home, kind='directory')
    return home.is_dir()


def select_account(entries=None, username=None, target_root=Path('/')):
    """Select exactly one eligible account; entries can be isolated test records."""
    if entries is None:
        entries = pwd.getpwall()
    accounts = [entry if isinstance(entry, Account) else Account(
        entry.pw_name, entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_shell
    ) for entry in entries]
    if username is not None:
        accounts = [account for account in accounts if account.name == username]
    candidates = [account for account in accounts if eligible(account, target_root)]
    if len(candidates) != 1:
        if username is not None:
            raise ValueError('--username must identify one eligible regular account with an existing home')
        raise ValueError(f'Found {len(candidates)} eligible regular accounts; use --username to select one')
    return candidates[0]


def prepare(target_root, account, *, apply=False, chown=os.chown):
    """Stage only this account. Injectable root/ownership keep tests isolated."""
    if not eligible(account, target_root):
        raise ValueError('Account is not an eligible regular desktop user')
    for required in REQUIRED_SCRIPTS:
        script = checked_path(inside(target_root, required), kind='file')
        if not script.is_file():
            raise ValueError(f'Required source script is missing: {script}')

    home = inside(target_root, account.home)
    config = checked_path(home / '.config', kind='directory')
    autostart = checked_path(config / 'autostart', kind='directory')
    target = checked_path(autostart / AUTOSTART_NAME, kind='file')
    exists = target.exists()
    if exists and target.read_bytes() != DESKTOP_ENTRY:
        raise ValueError(f'Existing different autostart is preserved: {target}')
    plan = Plan(target=target, username=account.name, create=not exists)
    if not apply:
        return plan

    # Existing home/.config directories are not recursively chowned or chmodded.
    for directory in (config, autostart):
        if not directory.exists():
            directory.mkdir(mode=0o700)
            chown(directory, account.uid, account.gid)
    info = autostart.stat()
    if (info.st_uid, info.st_gid) != (account.uid, account.gid):
        chown(autostart, account.uid, account.gid)

    if exists:
        # Recheck before touching an existing managed file.
        checked_path(target, kind='file')
        if not target.exists() or target.read_bytes() != DESKTOP_ENTRY:
            raise ValueError(f'Autostart changed after planning: {target}')
        info = target.stat()
        if stat.S_IMODE(info.st_mode) != 0o644:
            target.chmod(0o644)
        if (info.st_uid, info.st_gid) != (account.uid, account.gid):
            chown(target, account.uid, account.gid)
        return plan

    fd, temporary = tempfile.mkstemp(prefix='.workstation-stage-', dir=autostart)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(DESKTOP_ENTRY)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        chown(temporary, account.uid, account.gid)
        # A link publishes the complete file without replacing a concurrent file.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', help='Select one initial regular account when necessary')
    parser.add_argument('--apply', action='store_true', help='Create its first-login autostart')
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != 0:
        raise ValueError('--apply must run as root inside the newly installed target')
    account = select_account(username=args.username)
    plan = prepare(Path('/'), account, apply=args.apply)
    operation = 'CREATE' if plan.create else 'KEEP'
    print(f'{operation} {plan.target}')
    if args.apply:
        print('First-login restore staged for this account. Desktop settings were not applied as root.')
    else:
        print('Preview only. Add --apply inside the installed target to stage the first-login restore.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)

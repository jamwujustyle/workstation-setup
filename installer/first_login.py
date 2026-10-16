#!/usr/bin/env python3
"""Apply the installer payload once, inside the destination user's GNOME session."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

URLS = {
    'workstation-setup': 'https://github.com/jamwujustyle/workstation-setup.git',
    'agent-playbook': 'https://github.com/jamwujustyle/agent-playbook.git',
}


def _reject_symlink_parents(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError('Setup destination and its parents must not be symlinks.')


def _private_dir(path):
    _reject_symlink_parents(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.geteuid():
        raise RuntimeError('Setup state directory must belong to the current user.')
    path.chmod(0o700)


def _private_file(path, flags):
    fd = os.open(path, flags | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def _marker(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.write('\n')
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_marker(path):
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError('Setup marker must not be a symlink.')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError('Setup marker is invalid; review it before retrying.')
    return value


def _command(command, runner, log, cwd=None):
    result = runner(command, cwd=cwd, text=True, capture_output=True)
    output = (result.stdout or '') + (result.stderr or '')
    if output:
        log.write(output.rstrip() + '\n')
        log.flush()
    if result.returncode:
        raise RuntimeError(f'{Path(command[0]).name} exited with status {result.returncode}; see the private log.')
    return result.stdout or ''


def _git(source, args, runner, log):
    return _command(['git', '-c', f'safe.directory={source.resolve()}', '-C', str(source), *args], runner, log).strip()


def _head(source, runner, log):
    value = _git(source, ['rev-parse', '--verify', 'HEAD^{commit}'], runner, log)
    if len(value) not in (40, 64) or any(c not in '0123456789abcdef' for c in value):
        raise RuntimeError('Installer payload has an invalid Git revision.')
    return value


def _clone(source, target, name, expected_head, runner, log):
    _reject_symlink_parents(target)
    new_clone = not target.exists() or (target.is_dir() and not any(target.iterdir()))
    if new_clone:
        target.parent.mkdir(parents=True, exist_ok=True)
        _command(['git', '-c', f'safe.directory={source.resolve()}',
                  '-c', f'safe.directory={source.resolve() / ".git"}', 'clone',
                  '--no-hardlinks', str(source), str(target)], runner, log)
    if (target / '.git').is_symlink():
        raise RuntimeError(f'{name}: existing Git directory is a symlink; preserved.')
    if not target.is_dir() or not (target / '.git').is_dir():
        raise RuntimeError(f'{name}: existing nonempty directory is not the expected clone; preserved.')
    top = _git(target, ['rev-parse', '--show-toplevel'], runner, log)
    if Path(top).resolve() != target.resolve():
        raise RuntimeError(f'{name}: existing checkout root differs; preserved.')
    if _head(target, runner, log) != expected_head:
        raise RuntimeError(f'{name}: existing checkout has a different revision; preserved.')
    # Inspect status without writing filenames or private edits into output.
    status = runner(['git', '-C', str(target), 'status', '--porcelain'],
                    text=True, capture_output=True)
    if status.returncode or status.stdout.strip():
        raise RuntimeError(f'{name}: existing checkout has local changes or cannot be inspected; preserved.')
    origin = runner(['git', '-C', str(target), 'remote', 'get-url', 'origin'],
                    text=True, capture_output=True)
    allowed = {str(source), str(source.resolve()), URLS[name]}
    if origin.returncode or origin.stdout.strip() not in allowed:
        raise RuntimeError(f'{name}: existing checkout has a different origin; preserved.')
    if origin.stdout.strip() != URLS[name]:
        _git(target, ['remote', 'set-url', 'origin', URLS[name]], runner, log)
    if new_clone:
        # Only a newly created clone gets a branch; existing branch choices survive.
        _git(target, ['checkout', '-B', 'master', expected_head], runner, log)
        _git(target, ['branch', '--set-upstream-to=origin/master', 'master'], runner, log)
    return target


def _notify(title, message, runner):
    binary = shutil.which('notify-send')
    if binary:
        try:
            runner([binary, title, message], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def run(home: Path, source: Path, playbook_source: Path, retry=False, runner=subprocess.run) -> int:
    """Restore a payload; runner injection lets tests avoid running either installer."""
    if os.geteuid() == 0:
        raise RuntimeError('Run first-login setup as the desktop user, never as root.')
    state = home / '.local/state/workstation-setup'
    _private_dir(state)
    lockfd = _private_file(state / 'first-login.lock', os.O_RDWR)
    try:
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        logpath = state / 'first-login.log'
        with os.fdopen(_private_file(logpath, os.O_WRONLY | os.O_APPEND), 'a') as log:
            failed = state / 'first-login-failed.json'
            successful = state / 'first-login-success.json'
            payload = None
            try:
                # A previous failure is not replayed on every desktop login.
                if _read_marker(failed) and not retry:
                    return 1
                heads = {name: _head(path, runner, log) for name, path in
                         [('workstation-setup', source), ('agent-playbook', playbook_source)]}
                payload = hashlib.sha256(json.dumps(heads, sort_keys=True).encode()).hexdigest()
                if not retry and (_read_marker(successful) or {}).get('payload') == payload:
                    return 0
                log.write(f"\nFirst-login setup {datetime.now(timezone.utc).isoformat()} payload={payload}\n")
                log.flush()
                repos = home / '.local/share/workstation-setup/repos'
                workspace = _clone(source, repos / 'workstation-setup', 'workstation-setup', heads['workstation-setup'], runner, log)
                playbook = _clone(playbook_source, repos / 'agent-playbook', 'agent-playbook', heads['agent-playbook'], runner, log)
                output = _command([sys.executable, str(workspace / 'setup.py'), 'apply'], runner, log, cwd=workspace)
                _command([sys.executable, str(playbook / 'install.py'), '--apply'], runner, log, cwd=playbook)
                skipped = [line for line in output.splitlines() if line.startswith('SKIP ')]
                _marker(successful, {'payload': payload, 'source_heads': heads, 'skipped_settings': skipped,
                                     'completed_at': datetime.now(timezone.utc).isoformat()})
                failed.unlink(missing_ok=True)
                message = (f'Preferences and agent policies applied with {len(skipped)} skipped settings.'
                           if skipped else 'Preferences and agent policies applied.')
                message += f' Review {logpath}. Start a new terminal and Codex chat.'
                log.write(message + '\n')
                log.flush()
                _notify('Workstation setup', message, runner)
                return 0
            except Exception as exc:
                # Keep failures actionable, without printing previous settings or credentials.
                log.write(f'FAILED: {exc}\nRetry after resolving the problem: python3 {source / "installer/first_login.py"} --retry\n')
                log.flush()
                _marker(failed, {'payload': payload, 'failed_at': datetime.now(timezone.utc).isoformat()})
                _notify('Workstation setup needs attention',
                        f'Setup is incomplete. Review {logpath}; then run first_login.py --retry. No automatic retry will occur.', runner)
                return 1
    finally:
        os.close(lockfd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry', action='store_true', help='Retry after a failure or reapply the same payload idempotently')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.exit(1, 'First-login setup must run as the desktop user, not root.\n')
    if not os.environ.get('DBUS_SESSION_BUS_ADDRESS') or 'GNOME' not in os.environ.get('XDG_CURRENT_DESKTOP', '').upper():
        parser.exit(1, 'Run this command inside the target user GNOME desktop session with a session D-Bus.\n')
    source = Path(__file__).resolve().parents[1]
    try:
        return run(Path.home(), source, Path('/opt/agent-playbook'), retry=args.retry)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'First-login setup: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

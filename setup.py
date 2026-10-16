#!/usr/bin/env python3
"""Preview and restore reviewed personal workstation preferences."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parent
COMPONENTS = {'shell', 'git', 'editor', 'desktop'}


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def safe_path(path):
    if not path.is_absolute():
        raise ValueError(f'Expected an absolute path: {path}')
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError(f'Refusing to replace or traverse symlink: {item}')
    if path.exists() and not path.is_file():
        raise ValueError(f'Expected a regular file: {path}')


def read_optional(path):
    safe_path(path)
    return path.read_bytes() if path.exists() else None


def atomic_write(path, data, mode=0o600):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.workstation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def managed(existing, label, body):
    text = (existing or b'').decode('utf-8', errors='surrogateescape')
    start = f'# >>> workstation-setup {label} >>>'
    end = f'# <<< workstation-setup {label} <<<'
    block = f'{start}\n{body.rstrip()}\n{end}\n'
    if start in text or end in text:
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f'Ambiguous managed {label} block; repair its markers first')
        pattern = re.compile(r'^' + re.escape(start) + r'\n.*?^' + re.escape(end) + r'(?:\n|$)', re.S | re.M)
        if not pattern.search(text):
            raise ValueError(f'Malformed managed {label} block')
        text = pattern.sub(lambda _: block, text, count=1)
    else:
        text += ('\n' if text and not text.endswith('\n') else '') + block
    return text.encode('utf-8', errors='surrogateescape')


def config_root():
    path = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    if not path.is_absolute():
        raise ValueError('XDG_CONFIG_HOME must be absolute')
    return path


def file_plan(components, code_dir=None):
    home = Path.home()
    root = config_root()
    desired = []
    if 'shell' in components:
        fragment = root / 'workstation/bashrc.bash'
        desired.append((fragment, (REPO / 'config/shell/bashrc.bash').read_bytes()))
        target = home / '.bashrc'
        quoted = shlex.quote(str(fragment))
        desired.append((target, managed(read_optional(target), 'bash', f'[ -r {quoted} ] && . {quoted}')))
        target = home / '.inputrc'
        desired.append((target, managed(read_optional(target), 'readline', (REPO / 'config/shell/inputrc').read_text())))
    if 'git' in components:
        fragment = root / 'workstation/gitconfig'
        desired.append((fragment, (REPO / 'config/shell/gitconfig').read_bytes()))
        target = home / '.gitconfig'
        quoted = str(fragment).replace('\\', '\\\\').replace('"', '\\"')
        desired.append((target, managed(read_optional(target), 'git', f'[include]\n\tpath = "{quoted}"')))
    if 'editor' in components:
        target = Path(code_dir).expanduser().absolute() if code_dir else root / 'Code/User'
        for filename in ['settings.json', 'keybindings.json']:
            source = REPO / 'config/vscode' / filename
            json.loads(source.read_text())
            desired.append((target / filename, source.read_bytes()))
    changes = []
    for target, after in desired:
        before = read_optional(target)
        if before == after:
            continue
        mode = stat.S_IMODE(target.stat().st_mode) if before is not None else 0o600
        changes.append({'path': str(target), 'before': before, 'after': after, 'mode': mode})
    return changes


def desktop_module():
    import desktop
    return desktop


def preview(components, code_dir=None):
    files = file_plan(components, code_dir)
    desktop_changes, skipped = ([], [])
    if 'desktop' in components:
        desktop_changes, skipped = desktop_module().plan(REPO)
    for change in files:
        print(f"FILE {change['path']}")
    for change in desktop_changes:
        print(f"SETTING {change['schema']} {change['key']}")
    for reason in skipped:
        print(f'SKIP {reason}')
    if 'git' in components and not shutil.which('git-lfs'):
        print('NOTE Git LFS is configured but git-lfs is missing; cli packages include it.')
    print(f'{len(files)} file changes; {len(desktop_changes)} desktop changes; {len(skipped)} skipped desktop settings.')
    return files, desktop_changes


def require_user():
    if os.geteuid() == 0:
        raise ValueError('Run as your regular desktop user, without sudo.')


def make_backup(files, settings):
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    root = state / 'workstation-setup/backups'
    safe_path(root / 'manifest.json')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root.parent, 0o700)
    os.chmod(root, 0o700)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=root))
    manifest = {'version': 1, 'files': [], 'desktop': settings}
    for index, change in enumerate(files):
        filename = f'{index}.before'
        if change['before'] is not None:
            atomic_write(backup / filename, change['before'])
        manifest['files'].append({
            'path': change['path'], 'before_file': filename if change['before'] is not None else None,
            'before_sha256': digest(change['before']), 'after_sha256': digest(change['after']),
            'mode': change['mode'],
        })
    atomic_write(backup / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
    return backup


def apply_config(components, code_dir):
    require_user()
    files, settings = preview(components, code_dir)
    if not files and not settings:
        print('Already up to date. No backup needed.')
        return
    if settings:
        desktop_module().preflight(settings)
    backup = make_backup(files, settings)
    print(f'Backup: {backup}', flush=True)
    try:
        for change in files:
            target = Path(change['path'])
            if read_optional(target) != change['before']:
                raise ValueError(f'File changed after planning: {target}')
            atomic_write(target, change['after'], change['mode'])
        if settings:
            desktop_module().apply(settings)
    except Exception:
        print(f'Apply incomplete. Recover with: python3 setup.py rollback {shlex.quote(str(backup))} --apply', file=sys.stderr)
        raise
    print('Preferences applied. Open a new terminal and reload VS Code; extensions may need a new desktop login.')


def rollback(backup, apply=False):
    location = Path(backup).expanduser().absolute()
    safe_path(location / 'manifest.json')
    manifest = json.loads((location / 'manifest.json').read_text())
    if manifest.get('version') != 1:
        raise ValueError('Unsupported backup format')
    changes = []
    for entry in manifest['files']:
        target = Path(entry['path'])
        current = read_optional(target)
        if digest(current) == entry['before_sha256']:
            continue
        if digest(current) != entry['after_sha256']:
            raise ValueError(f'Rollback would overwrite a later edit: {target}')
        source = entry['before_file']
        if source is not None and (Path(source).name != source or Path(source).is_absolute()):
            raise ValueError('Invalid backup file name')
        before = read_optional(location / source) if source is not None else None
        if digest(before) != entry['before_sha256']:
            raise ValueError(f'Backup integrity check failed for {target}')
        changes.append((target, current, before, entry['mode']))
    settings = desktop_module().pending_rollback(manifest['desktop']) if manifest['desktop'] else []
    for target, *_ in changes:
        print(f'RESTORE {target}')
    for entry in settings:
        print(f"RESTORE SETTING {entry['schema']} {entry['key']}")
    print(f'{len(changes)} files and {len(settings)} settings to restore.')
    if not apply:
        print('Preview only. Add --apply to restore.')
        return
    require_user()
    if settings:
        desktop_module().apply(settings, reverse=True)
    for target, current, before, mode in changes:
        if read_optional(target) != current:
            raise ValueError(f'File changed during rollback: {target}')
        if before is None:
            target.unlink()
        else:
            atomic_write(target, before, mode)
    print('Restored. The backup is retained; empty directories may remain.')


def package_names(group):
    source = REPO / 'packages' / f'{group}.txt'
    names = [line.strip() for line in source.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name) for name in names):
        raise ValueError('Invalid package name in manifest')
    return names


def run_command(command, apply):
    print(shlex.join(command), flush=True)
    if apply:
        subprocess.run(command, check=True)


def software(args):
    if args.action == 'packages':
        if not shutil.which('apt-get'):
            raise ValueError('Package groups require Ubuntu/Debian apt-get.')
        command = ['apt-get', '--no-remove', 'install', *package_names(args.group)]
        if args.apply:
            require_user()
            run_command(['sudo', *command], True)
        else:
            run_command(['apt-get', '--simulate', '--no-remove', 'install', *package_names(args.group)], True)
    elif args.action == 'extensions':
        code = shutil.which(args.code_command)
        if not code:
            raise ValueError(f'VS Code CLI not found: {args.code_command}')
        installed = set(subprocess.check_output([code, '--list-extensions'], text=True).lower().splitlines())
        for line in (REPO / 'config/vscode/extensions.txt').read_text().splitlines():
            if line.lower() not in installed and line.strip():
                run_command([code, '--install-extension', line], args.apply)
    elif args.action == 'snaps':
        if not shutil.which('snap'):
            raise ValueError('snap is not installed.')
        apps = json.loads((REPO / 'packages/snaps.json').read_text())
        installed = {line.split()[0] for line in subprocess.check_output(['snap', 'list'], text=True, timeout=30).splitlines()[1:] if line.strip()}
        for app in apps:
            if app['name'] in installed:
                print(f"SKIP {app['name']} already installed; its channel is preserved.")
                continue
            command = ['sudo', 'snap', 'install', app['name'], f"--channel={app['channel']}"]
            if app.get('classic'):
                command.append('--classic')
            run_command(command, args.apply)
    if not args.apply:
        print('Preview only. Add --apply to install.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    for action in ['plan', 'apply']:
        p = sub.add_parser(action)
        p.add_argument('--only', default='shell,git,editor,desktop', help='Comma-separated components: shell,git,editor,desktop')
        p.add_argument('--code-user-dir', help='Override the VS Code User settings directory')
    p = sub.add_parser('rollback')
    p.add_argument('backup')
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('packages')
    p.add_argument('group', choices=['cli', 'desktop', 'development'])
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('extensions')
    p.add_argument('--code-command', default='code')
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('snaps')
    p.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.action is None:
        args = parser.parse_args(['plan'])
    if args.action in ['plan', 'apply']:
        selected = set(args.only.split(','))
        if not selected or not selected <= COMPONENTS:
            parser.error('--only accepts shell,git,editor,desktop')
        if args.action == 'apply':
            apply_config(selected, args.code_user_dir)
        else:
            preview(selected, args.code_user_dir)
            print('Preview only. Run apply to write preferences.')
    elif args.action == 'rollback':
        rollback(args.backup, args.apply)
    else:
        software(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)

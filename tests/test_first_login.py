"""First-login tests use temporary local Git repos and never execute setup scripts."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('first_login', ROOT / 'installer/first_login.py')
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@unittest.skipIf(os.geteuid() == 0, 'First-login restoration intentionally refuses root.')
class FirstLoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.sources = []
        for name, script in [('workstation-setup', 'setup.py'), ('agent-playbook', 'install.py')]:
            source = self.base / name
            source.mkdir()
            self.git(source, 'init', '-q', '-b', 'master')
            (source / script).write_text("raise AssertionError('Real installer must never execute in a test')\n")
            self.git(source, 'add', script)
            self.git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
            self.sources.append(source)
        self.calls = []
        self.fail_setup = False
        self.notifications = []
        self.notify_patch = patch.object(hook, '_notify', side_effect=lambda title, message, runner: self.notifications.append((title, message)))
        self.notify_patch.start()
        self.addCleanup(self.notify_patch.stop)

    def git(self, source, *args):
        return subprocess.run(['git', '-C', str(source), *args], text=True,
                              capture_output=True, check=True).stdout.strip()

    def runner(self, command, **kwargs):
        self.calls.append(command)
        if command[0] == sys.executable:
            if command[-1] == 'apply':
                return subprocess.CompletedProcess(command, 1 if self.fail_setup else 0,
                                                   'SKIP unavailable optional extension\n', '')
            self.assertEqual(command[-1], '--apply')
            return subprocess.CompletedProcess(command, 0, 'Agent policies installed.\n', '')
        self.assertEqual(command[0], 'git')
        return subprocess.run(command, **kwargs)

    def run_hook(self, retry=False):
        return hook.run(self.home, *self.sources, retry=retry, runner=self.runner)

    @property
    def state(self):
        return self.home / '.local/state/workstation-setup'

    @property
    def repos(self):
        return self.home / '.local/share/workstation-setup/repos'

    def test_success_pins_detached_payload_restores_both_and_runs_once(self):
        source = self.sources[0]
        pinned = self.git(source, 'rev-parse', 'HEAD')
        (source / 'future.txt').write_text('not part of pinned payload')
        self.git(source, 'add', 'future.txt')
        self.git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'future')
        self.git(source, 'checkout', '--detach', '-q', pinned)
        self.assertEqual(self.run_hook(), 0)
        for name, src in zip(hook.URLS, self.sources):
            clone = self.repos / name
            self.assertEqual(self.git(clone, 'rev-parse', 'HEAD'), self.git(src, 'rev-parse', 'HEAD'))
            self.assertEqual(self.git(clone, 'remote', 'get-url', 'origin'), hook.URLS[name])
            self.assertEqual(self.git(clone, 'branch', '--show-current'), 'master')
            self.assertEqual(self.git(clone, 'rev-parse', '--abbrev-ref', '@{upstream}'), 'origin/master')
        self.assertFalse((self.repos / 'workstation-setup/future.txt').exists())
        clone_calls = [c for c in self.calls if 'clone' in c]
        self.assertEqual(len(clone_calls), 2)
        self.assertTrue(all('--no-hardlinks' in c for c in clone_calls))
        for command, source in zip(clone_calls, self.sources):
            self.assertIn(f'safe.directory={source.resolve()}', command)
            self.assertIn(f'safe.directory={source.resolve() / ".git"}', command)
        self.assertEqual(len([c for c in self.calls if c[0] == sys.executable]), 2)
        marker = json.loads((self.state / 'first-login-success.json').read_text())
        self.assertEqual(len(marker['skipped_settings']), 1)
        self.assertIn('1 skipped settings', self.notifications[-1][1])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for filename in ['first-login.log', 'first-login.lock', 'first-login-success.json']:
            self.assertEqual(stat.S_IMODE((self.state / filename).stat().st_mode), 0o600)
        self.calls.clear()
        self.assertEqual(self.run_hook(), 0)
        self.assertFalse(any(c[0] == sys.executable or 'clone' in c for c in self.calls))

    def test_failure_blocks_repeated_logins_and_explicit_retry_reuses_clones(self):
        self.fail_setup = True
        self.assertEqual(self.run_hook(), 1)
        self.assertTrue((self.state / 'first-login-failed.json').exists())
        self.assertFalse((self.state / 'first-login-success.json').exists())
        self.calls.clear()
        self.assertEqual(self.run_hook(), 1)
        self.assertEqual(self.calls, [])
        self.fail_setup = False
        self.assertEqual(self.run_hook(retry=True), 0)
        self.assertFalse((self.state / 'first-login-failed.json').exists())
        self.assertFalse(any('clone' in c for c in self.calls))

    def test_nonempty_conflict_is_preserved(self):
        target = self.repos / 'workstation-setup'
        target.mkdir(parents=True)
        protected = target / 'personal.txt'
        protected.write_text('unchanged')
        self.assertEqual(self.run_hook(), 1)
        self.assertEqual(protected.read_text(), 'unchanged')
        self.assertFalse(any(c[0] == sys.executable for c in self.calls))

    def test_dirty_matching_clone_is_preserved(self):
        self.assertEqual(self.run_hook(), 0)
        protected = self.repos / 'workstation-setup/setup.py'
        protected.write_text('personal modification')
        self.calls.clear()
        self.assertEqual(self.run_hook(retry=True), 1)
        self.assertEqual(protected.read_text(), 'personal modification')
        self.assertFalse(any(c[0] == sys.executable for c in self.calls))

    def test_parent_symlinks_are_rejected_before_external_writes(self):
        external = self.base / 'external-state'
        external.mkdir()
        (self.home / '.local').mkdir()
        (self.home / '.local/state').symlink_to(external, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.run_hook()
        self.assertEqual(list(external.iterdir()), [])
        (self.home / '.local/state').unlink()
        external_repos = self.base / 'external-repos'
        external_repos.mkdir()
        parent = self.home / '.local/share/workstation-setup'
        parent.mkdir(parents=True)
        (parent / 'repos').symlink_to(external_repos, target_is_directory=True)
        self.assertEqual(self.run_hook(), 1)
        self.assertEqual(list(external_repos.iterdir()), [])

    def test_git_directory_symlink_is_preserved_and_rejected(self):
        self.assertEqual(self.run_hook(), 0)
        gitdir = self.repos / 'workstation-setup/.git'
        moved = self.base / 'external-git'
        gitdir.rename(moved)
        gitdir.symlink_to(moved, target_is_directory=True)
        self.calls.clear()
        self.assertEqual(self.run_hook(retry=True), 1)
        self.assertTrue(gitdir.is_symlink())
        self.assertFalse(any(c[0] == sys.executable for c in self.calls))
        self.assertFalse(any(str(self.repos / 'workstation-setup') in c for c in self.calls))

    def test_existing_matching_clone_keeps_its_branch(self):
        self.assertEqual(self.run_hook(), 0)
        clone = self.repos / 'workstation-setup'
        self.git(clone, 'checkout', '-qb', 'personal-branch')
        self.assertEqual(self.run_hook(retry=True), 0)
        self.assertEqual(self.git(clone, 'branch', '--show-current'), 'personal-branch')

    def test_lock_contention_does_not_execute_payload(self):
        self.state.mkdir(parents=True)
        with (self.state / 'first-login.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_hook(), 0)
        self.assertEqual(self.calls, [])


class FirstLoginEntryTests(unittest.TestCase):
    def test_root_rejected_before_any_state_write(self):
        with patch.object(hook.os, 'geteuid', return_value=0):
            with self.assertRaises(RuntimeError):
                hook.run(Path('/unwritten-test-path'), Path('/unused'), Path('/unused'))

    def test_cli_without_gnome_session_rejected(self):
        env = dict(os.environ)
        env.pop('DBUS_SESSION_BUS_ADDRESS', None)
        env.pop('XDG_CURRENT_DESKTOP', None)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'installer/first_login.py')],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertTrue('GNOME desktop session' in result.stderr or 'not root' in result.stderr)


if __name__ == '__main__':
    unittest.main()

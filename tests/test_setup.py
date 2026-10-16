"""Exercise restore and recovery only inside isolated temporary user roots."""
from pathlib import Path
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'setup.py'
ONLY = 'shell,git,editor'


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workstation test ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.config = self.base / 'config'
        self.state = self.base / 'state'
        self.home.mkdir()
        self.config.mkdir()
        self.editor = self.config / 'Code/User'
        self.editor.mkdir(parents=True)
        # Deliberately synthetic local values, not credentials from this machine.
        self.bash = b"# local startup\nexport LOCAL_FIXTURE_CREDENTIAL='test-only-placeholder'"
        self.git = (b'[user]\n\tname = Fixture Person\n'
                    b'\temail = fixture@example.invalid\n'
                    b'[credential]\n\thelper = cache\n'
                    b'[fixture]\n\tcredential = test-only-placeholder\n')
        self.original = {
            self.home / '.bashrc': self.bash,
            self.home / '.gitconfig': self.git,
            self.editor / 'settings.json': b'// original JSONC\n{"local": true,}\n',
        }
        for path, contents in self.original.items():
            path.write_bytes(contents)
            path.chmod(0o640)
        self.env = {
            'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.config),
            'XDG_STATE_HOME': str(self.state),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'LANG': 'C.UTF-8',
            'TERM': 'dumb',
        }
        self.targets = [
            self.home / '.bashrc', self.home / '.inputrc', self.home / '.gitconfig',
            self.config / 'workstation/bashrc.bash',
            self.config / 'workstation/gitconfig',
            self.editor / 'settings.json', self.editor / 'keybindings.json',
        ]

    def cli(self, *args, succeeds=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *args],
                                cwd=self.base, env=self.env,
                                text=True, capture_output=True)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('test-only-placeholder', result.stdout + result.stderr)
        return result

    def apply(self):
        self.cli('apply', '--only', ONLY)
        backups = sorted((self.state / 'workstation-setup/backups').iterdir())
        self.assertTrue(backups)
        return backups[-1]

    def snapshot(self):
        return {path: path.read_bytes() if path.exists() else None for path in self.targets}

    def test_plan_is_read_only(self):
        before = self.snapshot()
        result = self.cli('plan', '--only', ONLY)
        self.assertIn('Preview only', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.config / 'workstation').exists())

    def test_apply_preserves_local_shell_and_git_values(self):
        self.apply()
        self.assertTrue((self.home / '.bashrc').read_bytes().startswith(self.bash + b'\n'))
        self.assertTrue((self.home / '.gitconfig').read_bytes().startswith(self.git))
        for key, value in [('user.name', 'Fixture Person'),
                           ('user.email', 'fixture@example.invalid'),
                           ('credential.helper', 'cache'),
                           ('fixture.credential', 'test-only-placeholder'),
                           ('pull.rebase', 'merges')]:
            result = subprocess.run(['git', 'config', '--global', '--includes', '--get', key],
                                    env=self.env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), value)
        self.assertNotIn(b'test-only-placeholder', (self.config / 'workstation/bashrc.bash').read_bytes())
        for path in self.original:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        json.loads((self.editor / 'settings.json').read_text())
        json.loads((self.editor / 'keybindings.json').read_text())

    def test_second_apply_is_idempotent_and_creates_no_backup(self):
        self.apply()
        before = self.snapshot()
        backups = set((self.state / 'workstation-setup/backups').iterdir())
        result = self.cli('apply', '--only', ONLY)
        self.assertIn('Already up to date', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set((self.state / 'workstation-setup/backups').iterdir()), backups)

    def test_backup_permissions_are_private(self):
        backup = self.apply()
        for directory in [backup, backup.parent, backup.parent.parent]:
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in backup.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        manifest = json.loads((backup / 'manifest.json').read_text())
        self.assertEqual(manifest['desktop'], [])
        for entry in manifest['files']:
            self.assertTrue(Path(entry['path']).is_relative_to(self.base))

    def test_rollback_restores_exact_bytes_and_absent_targets(self):
        before = self.snapshot()
        backup = self.apply()
        applied = self.snapshot()
        self.cli('rollback', str(backup))
        self.assertEqual(self.snapshot(), applied)
        self.cli('rollback', str(backup), '--apply')
        self.assertEqual(self.snapshot(), before)
        for path in self.original:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertTrue((backup / 'manifest.json').is_file())
        # Recovery can be repeated without changing the recovered state.
        self.cli('rollback', str(backup), '--apply')
        self.assertEqual(self.snapshot(), before)

    def test_rollback_rejects_later_edits_before_restoring_any_file(self):
        backup = self.apply()
        path = self.home / '.bashrc'
        path.write_bytes(path.read_bytes() + b'\n# later local edit\n')
        later = self.snapshot()
        result = self.cli('rollback', str(backup), '--apply', succeeds=False)
        self.assertIn('later edit', result.stderr)
        self.assertEqual(self.snapshot(), later)

    def test_rollback_rejects_modified_backup(self):
        backup = self.apply()
        current = self.snapshot()
        manifest = json.loads((backup / 'manifest.json').read_text())
        entry = next(item for item in manifest['files'] if item['before_file'])
        (backup / entry['before_file']).write_bytes(b'tampered backup\n')
        result = self.cli('rollback', str(backup), '--apply', succeeds=False)
        self.assertIn('integrity check failed', result.stderr)
        self.assertEqual(self.snapshot(), current)

    def test_apply_refuses_symlink_target(self):
        target = self.home / '.bashrc'
        other = self.base / 'outside.bashrc'
        other.write_bytes(self.bash)
        target.unlink()
        target.symlink_to(other)
        result = self.cli('apply', '--only', ONLY, succeeds=False)
        self.assertIn('symlink', result.stderr)
        self.assertTrue(target.is_symlink())
        self.assertEqual(other.read_bytes(), self.bash)
        self.assertFalse(self.state.exists())

    def test_apply_refuses_symlink_parent(self):
        real_config = self.base / 'actual-config'
        self.config.rename(real_config)
        self.config.symlink_to(real_config, target_is_directory=True)
        result = self.cli('apply', '--only', ONLY, succeeds=False)
        self.assertIn('symlink', result.stderr)
        self.assertFalse(self.state.exists())
        self.assertEqual((self.home / '.bashrc').read_bytes(), self.bash)

    def test_apply_refuses_malformed_or_ambiguous_managed_blocks(self):
        start = '# >>> workstation-setup bash >>>'
        end = '# <<< workstation-setup bash <<<'
        variants = [start + '\nmissing end\n', end + '\nmissing start\n',
                    end + '\n' + start + '\n',
                    start + '\n' + start + '\n' + end + '\n',
                    'prefix ' + start + '\nbody\n' + end + '\n',
                    start + '\nbody\n' + end + ' suffix\n']
        for content in variants:
            with self.subTest(content=content):
                path = self.home / '.bashrc'
                path.write_text(content)
                before = self.snapshot()
                result = self.cli('apply', '--only', ONLY, succeeds=False)
                self.assertIn('managed bash block', result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.state.exists())


if __name__ == '__main__':
    unittest.main()

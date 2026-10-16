"""First-login staging tests; no real /home, /opt, ownership, or desktop writes."""
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'installer/stage.py'
SPEC = importlib.util.spec_from_file_location('workstation_installer_stage', SOURCE)
stage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage
SPEC.loader.exec_module(stage)


class InstallerStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-stage-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = stage.Account('fixture', 1000, 1000, '/home/fixture', '/bin/bash')
        self.home = self.root / 'home/fixture'
        self.home.mkdir(parents=True)
        for required in stage.REQUIRED_SCRIPTS:
            path = stage.inside(self.root, required)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# isolated source fixture\n')
        self.target = self.home / '.config/autostart' / stage.AUTOSTART_NAME
        self.ownership_calls = []

    def chown(self, path, uid, gid):
        path = Path(path)
        self.assertTrue(path.is_relative_to(self.root))
        self.ownership_calls.append((path, uid, gid))

    def prepare(self, apply=False):
        return stage.prepare(self.root, self.account, apply=apply, chown=self.chown)

    def test_selects_single_regular_account_and_ignores_system_accounts(self):
        system = stage.Account('root', 0, 0, '/root', '/bin/bash')
        no_login = stage.Account('service', 1001, 1001, '/home/service', '/usr/sbin/nologin')
        (self.root / 'home/service').mkdir()
        self.assertEqual(stage.select_account([system, no_login, self.account], target_root=self.root), self.account)

    def test_ambiguity_requires_explicit_username(self):
        other = stage.Account('second', 1001, 1001, '/home/second', '/bin/bash')
        (self.root / 'home/second').mkdir()
        with self.assertRaisesRegex(ValueError, '2 eligible'):
            stage.select_account([self.account, other], target_root=self.root)
        selected = stage.select_account([self.account, other], username='fixture', target_root=self.root)
        self.assertEqual(selected, self.account)
        with self.assertRaisesRegex(ValueError, 'eligible regular account'):
            stage.select_account([self.account, other], username='missing', target_root=self.root)

    def test_rejects_nonregular_missing_home_and_false_shell(self):
        invalid = [
            stage.Account('fixture', 999, 1000, '/home/fixture', '/bin/bash'),
            stage.Account('fixture', 60000, 1000, '/home/fixture', '/bin/bash'),
            stage.Account('fixture', 1000, 1000, '/home/fixture', '/bin/false'),
            stage.Account('fixture', 1000, 1000, '/home/fixture', '/sbin/nologin'),
            stage.Account('missing', 1000, 1000, '/home/missing', '/bin/bash'),
            stage.Account('fixture', 1000, 1000, '/opt/fixture', '/bin/bash'),
            stage.Account('../fixture', 1000, 1000, '/home/../fixture', '/bin/bash'),
        ]
        for account in invalid:
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    stage.select_account([account], target_root=self.root)

    def test_preview_is_read_only(self):
        plan = self.prepare()
        self.assertTrue(plan.create)
        self.assertEqual(plan.target, self.target)
        self.assertFalse((self.home / '.config').exists())
        self.assertEqual(self.ownership_calls, [])

    def test_apply_creates_only_selected_accounts_autostart(self):
        other_home = self.root / 'home/other'
        other_home.mkdir()
        plan = self.prepare(apply=True)
        self.assertTrue(plan.create)
        self.assertEqual(self.target.read_bytes(), stage.DESKTOP_ENTRY)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.target.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.target.parent.parent.stat().st_mode), 0o700)
        self.assertFalse((other_home / '.config').exists())
        self.assertFalse((self.root / 'etc').exists())
        self.assertTrue(self.ownership_calls)
        for path, uid, gid in self.ownership_calls:
            self.assertTrue(path.is_relative_to(self.home / '.config'))
            self.assertEqual((uid, gid), (self.account.uid, self.account.gid))

    def test_existing_parent_configuration_is_not_broadly_chowned(self):
        config = self.home / '.config'
        config.mkdir(mode=0o750)
        unrelated = config / 'other.conf'
        unrelated.write_text('keep this\n')
        before_mode = stat.S_IMODE(config.stat().st_mode)
        self.prepare(apply=True)
        changed_paths = [call[0] for call in self.ownership_calls]
        self.assertNotIn(self.home, changed_paths)
        self.assertNotIn(config, changed_paths)
        self.assertNotIn(unrelated, changed_paths)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), before_mode)
        self.assertEqual(unrelated.read_text(), 'keep this\n')

    def test_same_autostart_is_idempotent(self):
        self.prepare(apply=True)
        original = self.target.stat()
        second = self.prepare(apply=True)
        self.assertFalse(second.create)
        self.assertEqual(self.target.stat().st_ino, original.st_ino)
        self.assertEqual(self.target.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_preserves_different_existing_autostart(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text('[Desktop Entry]\nExec=keep-local-command\n')
        before = self.target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Existing different autostart'):
            self.prepare(apply=True)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.ownership_calls, [])

    def test_missing_required_source_stops_before_changes(self):
        stage.inside(self.root, stage.REQUIRED_SCRIPTS[1]).unlink()
        with self.assertRaisesRegex(ValueError, 'Required source script is missing'):
            self.prepare(apply=True)
        self.assertFalse((self.home / '.config').exists())
        self.assertEqual(self.ownership_calls, [])

    def test_refuses_source_symlink(self):
        required = stage.inside(self.root, stage.REQUIRED_SCRIPTS[0])
        real = self.root / 'other-source.py'
        real.write_text('pass\n')
        required.unlink()
        required.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare(apply=True)
        self.assertFalse((self.home / '.config').exists())

    def test_refuses_target_symlink(self):
        self.target.parent.mkdir(parents=True)
        real = self.root / 'other.desktop'
        real.write_text('preserved\n')
        self.target.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare(apply=True)
        self.assertEqual(real.read_text(), 'preserved\n')

    def test_refuses_parent_and_home_symlinks(self):
        real = self.root / 'elsewhere'
        real.mkdir()
        config = self.home / '.config'
        config.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare(apply=True)
        config.unlink()
        self.home.rmdir()
        self.home.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            stage.select_account([self.account], target_root=self.root)
        self.assertEqual(list(real.iterdir()), [])

    def test_desktop_entry_launches_exact_user_session_worker(self):
        entries = dict(line.split('=', 1) for line in stage.DESKTOP_ENTRY.decode().splitlines() if '=' in line)
        self.assertEqual(entries['Exec'], '/usr/bin/python3 /opt/workstation-setup/installer/first_login.py')
        self.assertEqual(entries['OnlyShowIn'], 'GNOME;ubuntu;')
        self.assertEqual(entries['Terminal'], 'false')
        self.assertEqual(entries['Type'], 'Application')
        self.assertNotIn('sudo', entries['Exec'])

    def test_cli_apply_requires_root_before_account_discovery(self):
        with mock.patch.object(stage.os, 'geteuid', return_value=1000), mock.patch.object(stage, 'select_account') as select:
            with self.assertRaisesRegex(ValueError, 'must run as root'):
                stage.main(['--apply'])
            select.assert_not_called()

    def test_cli_default_preview_does_not_require_root(self):
        plan = stage.Plan(self.target, self.account.name, True)
        with mock.patch.object(stage.os, 'geteuid', return_value=1000), \
                mock.patch.object(stage, 'select_account', return_value=self.account) as select, \
                mock.patch.object(stage, 'prepare', return_value=plan) as prepare, \
                mock.patch('builtins.print'):
            self.assertEqual(stage.main([]), 0)
            select.assert_called_once_with(username=None)
            prepare.assert_called_once_with(Path('/'), self.account, apply=False)


if __name__ == '__main__':
    unittest.main()

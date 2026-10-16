"""Desktop regression tests always execute mutations in isolated memory backends."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[1]


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, GSETTINGS_BACKEND="memory", PYTHONDONTWRITEBYTECODE="1")
        probe = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""\
                from gi.repository import Gio
                source = Gio.SettingsSchemaSource.get_default()
                required = [
                    'org.gnome.desktop.interface', 'org.gnome.desktop.session',
                    'org.gnome.shell', 'org.gnome.shell.keybindings',
                    'org.gnome.Terminal.ProfilesList', 'org.gnome.Terminal.Legacy.Profile',
                ]
                assert source and all(source.lookup(s, True) for s in required)
                assert source.lookup('org.gnome.desktop.interface', True).has_key('color-scheme')
            """)],
            env=env, capture_output=True, text=True,
        )
        if probe.returncode:
            raise unittest.SkipTest("System Python GI and GNOME/Terminal schemas are required.")

    def run_memory(self, body):
        # No desktop import occurs in the discovery process. Each child starts
        # with a fresh memory backend before GI or GSettings is imported.
        env = dict(os.environ, GSETTINGS_BACKEND="memory", PYTHONDONTWRITEBYTECODE="1")
        prelude = """\
import os
assert os.environ['GSETTINGS_BACKEND'] == 'memory'
from pathlib import Path
from unittest.mock import patch
import desktop
repo = Path.cwd()
Gio, GLib = desktop._gi()
interface = Gio.Settings.new('org.gnome.desktop.interface')
row = {'schema': 'org.gnome.desktop.interface',
       'path': '/org/gnome/desktop/interface/', 'key': 'color-scheme',
       'before': None, 'after': "'prefer-dark'"}
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", prelude + textwrap.dedent(body)],
            cwd=REPO, env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_validate_manifest(self):
        self.run_memory("""
            result = desktop.validate(repo)
            assert result['checked'] > 0
            assert isinstance(result['skipped'], list)
        """)

    def test_round_trip_preserves_implicit_and_explicit_defaults(self):
        self.run_memory("""
            assert interface.get_user_value('color-scheme') is None
            assert desktop.apply([row]) == 1
            assert len(desktop.pending_rollback([row])) == 1
            assert desktop.apply(desktop.pending_rollback([row]), reverse=True) == 1
            assert interface.get_user_value('color-scheme') is None
            assert desktop.pending_rollback([row]) == []
            interface.set_string('color-scheme', 'default')
            row['before'] = "'default'"
            desktop.apply([row])
            desktop.apply([row], reverse=True)
            assert interface.get_user_value('color-scheme').unpack() == 'default'
        """)

    def test_stale_forward_and_conflicting_rollback_are_rejected(self):
        self.run_memory("""
            interface.set_string('color-scheme', 'prefer-light')
            try:
                desktop.apply([row])
            except RuntimeError:
                pass
            else:
                raise AssertionError('Stale forward write accepted')
            assert interface.get_string('color-scheme') == 'prefer-light'
            interface.reset('color-scheme')
            desktop.apply([row])
            interface.set_string('color-scheme', 'prefer-light')
            for action in (lambda: desktop.pending_rollback([row]),
                           lambda: desktop.apply([row], reverse=True)):
                try:
                    action()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Conflicting rollback accepted')
            assert interface.get_string('color-scheme') == 'prefer-light'
        """)

    def test_terminal_profile_adapts_without_replacing_profile_list(self):
        self.run_memory("""
            profiles = Gio.Settings.new_with_path(
                'org.gnome.Terminal.ProfilesList', '/org/gnome/terminal/legacy/profiles:/')
            target = '81466b15-4b75-4943-a6cb-8f6a25d40f24'
            profiles.set_strv('list', [target])
            profiles.set_string('default', target)
            changes, _ = desktop.plan(repo)
            rows = [r for r in changes if r['schema'] == 'org.gnome.Terminal.Legacy.Profile']
            assert rows
            assert all('/:' + target + '/' in r['path'] for r in rows)
            assert not any(r['schema'] == 'org.gnome.Terminal.ProfilesList' for r in changes)
            profiles.set_strv('list', [])
            changes, skipped = desktop.plan(repo)
            assert not any(r['schema'] == 'org.gnome.Terminal.Legacy.Profile' for r in changes)
            assert any('no valid destination default profile' in s for s in skipped)
        """)

    def test_missing_extensions_preserve_message_tray(self):
        self.run_memory("""
            with patch.object(desktop, '_compatible_extensions', return_value=(set(), None)):
                changes, skipped = desktop.plan(repo)
            assert not any(r['schema'].startswith('org.gnome.shell.extensions.') for r in changes)
            assert not any(r['key'] == 'toggle-message-tray' for r in changes)
            assert any('compatible clipboard-indicator@tudmotu.com is required' in s for s in skipped)
        """)

    def test_favorites_and_extensions_merge_without_losing_unrelated_values(self):
        self.run_memory("""
            shell = Gio.Settings.new('org.gnome.shell')
            shell.set_strv('enabled-extensions', ['unrelated@example.invalid'])
            shell.set_strv('favorite-apps', ['unrelated.desktop'])
            compatible = {'clipboard-indicator@tudmotu.com'}
            with patch.object(desktop, '_compatible_extensions', return_value=(compatible, None)), \
                 patch.object(desktop, '_app_exists', side_effect=lambda app: app == 'spotify_spotify.desktop'):
                changes, skipped = desktop.plan(repo)
            extensions = next(r for r in changes if r['key'] == 'enabled-extensions')
            favorites = next(r for r in changes if r['key'] == 'favorite-apps')
            assert GLib.Variant.parse(None, extensions['after'], None, None).unpack() == [
                'unrelated@example.invalid', 'clipboard-indicator@tudmotu.com']
            assert GLib.Variant.parse(None, favorites['after'], None, None).unpack() == [
                'spotify_spotify.desktop', 'unrelated.desktop']
            assert any('code.desktop is not installed' in s for s in skipped)
            assert any('ubuntu-dock@ubuntu.com is unavailable or incompatible' in s for s in skipped)
        """)

    def test_missing_themes_are_skipped(self):
        self.run_memory("""
            with patch.object(desktop, '_theme_exists', return_value=False):
                changes, skipped = desktop.plan(repo)
            assert not any(r['key'] in ('gtk-theme', 'icon-theme', 'cursor-theme') for r in changes)
            assert any('requested theme is not installed' in s for s in skipped)
        """)

    def test_partial_write_failure_restores_only_completed_changes(self):
        self.run_memory("""
            second = {'schema': 'org.gnome.desktop.session',
                      'path': '/org/gnome/desktop/session/', 'key': 'idle-delay',
                      'before': None, 'after': 'uint32 0'}
            original = desktop._write
            calls = []
            def fail_second(*args):
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError('injected failure')
                return original(*args)
            with patch.object(desktop, '_write', side_effect=fail_second):
                try:
                    desktop.apply([row, second])
                except RuntimeError as exc:
                    assert 'completed changes were restored' in str(exc)
                else:
                    raise AssertionError('Injected failure was ignored')
            assert desktop.pending_rollback([row, second]) == []
            assert interface.get_user_value('color-scheme') is None
        """)

    def test_full_preflight_prevents_first_write_when_later_variant_is_invalid(self):
        self.run_memory("""
            bad = {'schema': 'org.gnome.desktop.session',
                   'path': '/org/gnome/desktop/session/', 'key': 'idle-delay',
                   'before': None, 'after': "'invalid-type'"}
            try:
                desktop.apply([row, bad])
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid variant accepted')
            assert interface.get_user_value('color-scheme') is None
        """)


if __name__ == '__main__':
    unittest.main()

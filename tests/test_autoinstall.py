"""Check installer profile invariants without running an installer."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('render_autoinstall', ROOT / 'installer/render_autoinstall.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AutoinstallTests(unittest.TestCase):
    def test_guided_profile_has_no_disk_or_account_defaults(self):
        output = module.render(ROOT, 'a' * 40, 'b' * 40)
        self.assertIn("interactive-sections:\n    - '*'", output)
        for field in ['storage:', 'identity:', 'user-data:', 'password:', 'ssh:', 'early-commands:']:
            self.assertNotIn(field, output)
        self.assertTrue(output.startswith('#cloud-config\n'))

    def test_pins_both_repositories_and_stages_without_running_user_settings(self):
        output = module.render(ROOT, 'a' * 40, 'b' * 40)
        commands = [json.loads(line.strip()[2:]) for line in output.splitlines() if line.strip().startswith('- [')]
        self.assertEqual(len(commands), 5)
        self.assertIn('a' * 40, commands[1])
        self.assertIn('b' * 40, commands[3])
        self.assertIn('/opt/workstation-setup/installer/stage.py', commands[4])
        self.assertNotIn('setup.py apply', output)
        self.assertNotIn('install.py --apply', output)
        self.assertNotIn('git@github.com', output)

    def test_refuses_moving_or_shell_injected_revisions(self):
        for value in ['master', 'a' * 39, 'a' * 41, 'A' * 40, 'abc; touch /tmp/unexpected']:
            with self.assertRaises(ValueError):
                module.render(ROOT, value, 'b' * 40)
            with self.assertRaises(ValueError):
                module.render(ROOT, 'a' * 40, value)

    def test_packages_follow_existing_cli_and_desktop_manifests(self):
        output = module.render(ROOT, 'a' * 40, 'b' * 40)
        for group in ['cli', 'desktop']:
            for name in (ROOT / 'packages' / f'{group}.txt').read_text().splitlines():
                if name.strip() and not name.startswith('#'):
                    self.assertIn(f'    - {name}\n', output)
        self.assertNotIn('    - ansible\n', output)


if __name__ == '__main__':
    unittest.main()

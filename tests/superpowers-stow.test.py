"""Exercise fresh-machine Superpowers discovery through real GNU Stow."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOTFILES = Path(os.environ.get('DOTFILES_TEST_SOURCE', str(ROOT.parent.parent / 'dotfiles')))
SUPERPOWERS = ROOT.parent / 'super-mezzanine'


class FreshInstall(unittest.TestCase):
    def test_stow_and_restow_keep_external_workflow_and_personal_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_home = Path(tmp)
            dotfiles = fixture_home / 'dotfiles'
            source = fixture_home / 'Proj/super-mezzanine'
            shutil.copytree(SUPERPOWERS, source, symlinks=True,
                            ignore=shutil.ignore_patterns('.git', '__pycache__'))
            dotfiles.mkdir()
            shutil.copy2(DOTFILES / '.stow-local-ignore', dotfiles / '.stow-local-ignore')
            for package in ('agents', 'claude', 'opencode', 'codex'):
                shutil.copytree(DOTFILES / package, dotfiles / package, symlinks=True,
                                ignore=shutil.ignore_patterns('memory', '__pycache__', 'node_modules'))
            personal = fixture_home / '.agents/skills/last30days/SKILL.md'
            personal.parent.mkdir(parents=True)
            personal.write_text('separately installed skill')
            settings = fixture_home / '.claude/personal.json'
            settings.parent.mkdir(parents=True)
            settings.write_text('personal settings')
            for _ in range(2):
                run = subprocess.run(['stow', '--dir', str(dotfiles), '--target', str(fixture_home),
                                      '--restow', 'agents', 'opencode'], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                run = subprocess.run(['stow', '--dir', str(dotfiles), '--target', str(fixture_home),
                                      '--no-folding', '--restow', 'claude', 'codex'], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                for skill in (source / 'skills').glob('*/SKILL.md'):
                    for base in ('.agents/skills', '.claude/skills', '.config/opencode/skills'):
                        actual = fixture_home / base / skill.parent.name
                        self.assertEqual(actual.resolve(), skill.parent.resolve())
                        self.assertTrue(actual.is_symlink())
                        self.assertFalse((actual / 'SKILL.md').is_symlink())
                self.assertEqual(personal.read_text(), 'separately installed skill')
                self.assertEqual(settings.read_text(), 'personal settings')
                self.assertEqual((fixture_home / '.agents/skills/standup').resolve(),
                                 (dotfiles / 'agents/.agents/skills/standup').resolve())
                self.assertEqual((fixture_home / '.config/opencode/agents/superpowers.md').resolve(),
                                 source / 'runtimes/opencode/agents/superpowers.md')
                self.assertEqual((fixture_home / '.local/bin/clickup-http').resolve(), source / 'bin/clickup-http')
                self.assertEqual((fixture_home / '.local/bin/codex-provider-agent').resolve(),
                                 source / 'bin/codex-provider-agent')
                providers = subprocess.run([str(fixture_home / '.local/bin/codex-provider-agent'), '--list'],
                                           env={**os.environ, 'HOME': str(fixture_home)},
                                           capture_output=True, text=True)
                self.assertEqual(providers.returncode, 0, providers.stderr)
                self.assertIn('clickup', providers.stdout)

    def test_bootstrap_clones_superpowers_before_stow(self):
        script = (ROOT / 'clone-repos.sh').read_text()
        self.assertIn('https://github.com/datascopesystems/super-mezzanine.git', script)
        self.assertIn('~/Proj/super-mezzanine', script)
        setup = (ROOT / 'endeavouros-setup.sh').read_text()
        self.assertLess(setup.index('bash "$SCRIPT_DIR/clone-repos.sh"'),
                        setup.index('stow --target='))


if __name__ == '__main__':
    unittest.main()

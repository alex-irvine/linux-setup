"""Install, stow, migrate credentials and pull through the real CLI in a temporary home."""

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest


class BugwarriorSetupTest(unittest.TestCase):
    def test_restore_my_clickup_workflow_and_preserve_private_credentials_on_rerun(self):
        setup = Path(__file__).resolve().parents[1] / "bugwarrior-setup.sh"
        dotfiles = Path(os.environ.get("DOTFILES_DIR", Path.home() / "dotfiles")).resolve()
        python_dir = subprocess.check_output(["uv", "python", "dir"], text=True).strip()
        with tempfile.TemporaryDirectory(prefix="bugwarrior-setup-test-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            env = dict(
                os.environ, HOME=str(home), DOTFILES_DIR=str(dotfiles),
                UV_TOOL_DIR=str(root / "tools"), UV_TOOL_BIN_DIR=str(home / ".local/bin"),
                UV_PYTHON_INSTALL_DIR=python_dir, UV_OFFLINE="1",
            )
            # Reuse downloaded dependencies, but install an independent tool environment.
            env["UV_CACHE_DIR"] = subprocess.check_output(["uv", "cache", "dir"], text=True).strip()

            def run(*command, success=True):
                result = subprocess.run(
                    command, env=env, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, timeout=180,
                )
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("pk_MIGRATION_TEST_ONLY", result.stdout + result.stderr)
                self.assertNotIn("pk_DIFFERENT_TEST_ONLY", result.stdout + result.stderr)
                return result

            # A fresh install stows the public config and leaves the API key unset.
            run("bash", str(setup))
            config = home / ".config/bugwarrior/bugwarrior.toml"
            secret = home / ".config/bugwarrior-secrets/clickup-token"
            self.assertTrue(config.is_symlink())
            self.assertEqual(config.resolve(), dotfiles / "task/.config/bugwarrior/bugwarrior.toml")
            self.assertTrue((home / ".taskrc").is_symlink())
            self.assertFalse(secret.exists())
            public_config = config.read_text()
            parsed = tomllib.loads(public_config)
            self.assertEqual(parsed["clickup"]["statuses"], [
                "in progress", "ready for qa", "uat", "qa failed", "qa in progress",
            ])
            self.assertEqual(parsed["clickup"]["only_if_assigned"], "Alex Irvine")
            tool = home / ".local/bin/bugwarrior"
            self.assertTrue(tool.is_file())
            run(str(tool), "--help")

            # Recreate an existing installation with an inline key, then migrate it.
            config.unlink()
            legacy = public_config.replace(
                "'" + parsed["clickup"]["token"] + "'", '"pk_MIGRATION_TEST_ONLY"',
            )
            config.write_text(legacy)
            config.chmod(0o600)
            run("bash", str(setup))
            self.assertTrue(config.is_symlink())
            self.assertEqual(secret.read_text(), "pk_MIGRATION_TEST_ONLY\n")
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(secret.parent.stat().st_mode), 0o700)
            self.assertFalse(secret.resolve().is_relative_to(dotfiles))
            self.assertEqual(config.read_text(), public_config)

            # Setup remains safe to repeat; exercise pulls with the newly installed tool.
            run("bash", str(setup))
            self.assertEqual(secret.read_text(), "pk_MIGRATION_TEST_ONLY\n")
            run(str(root / "tools/bugwarrior/bin/python"), "-m", "unittest", "discover", "-s",
                str(dotfiles / "task/.local/share/bugwarrior-clickup/tests"), "-v")

            # An existing different key must never be overwritten or printed.
            config.unlink()
            conflicting = legacy.replace("pk_MIGRATION_TEST_ONLY", "pk_DIFFERENT_TEST_ONLY")
            config.write_text(conflicting)
            run("bash", str(setup), success=False)
            self.assertEqual(config.read_text(), conflicting)
            self.assertEqual(secret.read_text(), "pk_MIGRATION_TEST_ONLY\n")
            self.assertEqual((dotfiles / "task/.config/bugwarrior/bugwarrior.toml").read_text(), public_config)


if __name__ == "__main__":
    unittest.main()

import os
import unittest

import agent_shell
import safe_harness
import ralph_loop
import real_repo_loop

WORKDIR = os.path.abspath(os.path.dirname(__file__))


class TestAgentShellSubcommandAllowlist(unittest.TestCase):
    def test_allowed_git_subcommand_runs(self):
        result = agent_shell.run_shell("git status", WORKDIR)
        self.assertIn("exit code:", result)

    def test_disallowed_git_subcommand_is_rejected(self):
        result = agent_shell.run_shell("git push", WORKDIR)
        self.assertIn("not in the allowed git subcommand list", result)
        self.assertNotIn("exit code:", result)

    def test_git_config_is_rejected_by_default(self):
        result = agent_shell.run_shell("git config user.name", WORKDIR)
        self.assertIn("not in the allowed git subcommand list", result)

    def test_push_allowed_when_explicitly_included(self):
        # -h prints usage and exits without touching the network, so this
        # only exercises the subcommand policy, not an actual push.
        allowed = agent_shell.DEFAULT_ALLOWED_GIT_SUBCOMMANDS | {"push"}
        result = agent_shell.run_shell(
            "git push -h", WORKDIR, allowed_git_subcommands=allowed
        )
        self.assertNotIn("not in the allowed git subcommand list", result)

    def test_pip_install_is_rejected(self):
        result = agent_shell.run_shell("pip install requests", WORKDIR)
        self.assertIn("not in the allowed pip subcommand list", result)
        self.assertNotIn("exit code:", result)

    def test_pip_list_is_allowed(self):
        result = agent_shell.run_shell("pip list", WORKDIR)
        self.assertIn("exit code:", result)

    def test_bare_git_with_no_subcommand_is_not_rejected_by_subcommand_check(self):
        # No subcommand to validate; this should reach the binary allowlist
        # path (and just run `git`, which prints usage) rather than being
        # rejected by the subcommand allowlist itself.
        result = agent_shell.run_shell("git", WORKDIR)
        self.assertNotIn("not in the allowed git subcommand list", result)


class TestPerScriptGitSubcommandPolicy(unittest.TestCase):
    def test_safe_harness_rejects_push(self):
        self.assertIn(
            "not in the allowed git subcommand list", safe_harness.run_shell("git push")
        )

    def test_ralph_loop_rejects_push(self):
        self.assertIn(
            "not in the allowed git subcommand list", ralph_loop.run_shell("git push")
        )

    def test_real_repo_loop_allows_push(self):
        result = real_repo_loop.run_shell("git push -h")
        self.assertNotIn("not in the allowed git subcommand list", result)

    def test_real_repo_loop_still_rejects_config(self):
        result = real_repo_loop.run_shell("git config user.name")
        self.assertIn("not in the allowed git subcommand list", result)


if __name__ == "__main__":
    unittest.main()

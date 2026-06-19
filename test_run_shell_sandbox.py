import unittest

import safe_harness


class TestRunShellSandbox(unittest.TestCase):
    def test_allowed_binary_executes_normally(self):
        result = safe_harness.run_shell('python -c "print(1)"')
        self.assertIn("exit code: 0", result)
        self.assertIn("1", result)

    def test_disallowed_binary_is_rejected_before_execution(self):
        result = safe_harness.run_shell("del important_file.txt")
        self.assertIn("not in the allowed command list", result)
        self.assertIn("del", result)

    def test_chaining_attempt_does_not_run_the_second_command(self):
        # Without a real shell, "&&" is just a literal argv entry handed to
        # python, not a chain separator — so "echo pwned" never runs as its
        # own command. python ignores the trailing positional args after -c.
        result = safe_harness.run_shell('python -c "print(1)" && echo pwned')
        self.assertIn("exit code: 0", result)
        self.assertNotIn("pwned", result)

    def test_unparseable_command_is_rejected_cleanly(self):
        result = safe_harness.run_shell('git commit -m "unterminated quote')
        self.assertIn("Error: could not parse command", result)

    def test_empty_command_is_rejected(self):
        result = safe_harness.run_shell("")
        self.assertIn("Error: empty command", result)


if __name__ == "__main__":
    unittest.main()

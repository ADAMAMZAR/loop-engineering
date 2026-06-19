import unittest

import safe_harness
import real_repo_loop
import ralph_loop


class TestSafeHarnessArgs(unittest.TestCase):
    def test_defaults_to_demo_goal_when_omitted(self):
        args = safe_harness.build_arg_parser().parse_args([])
        self.assertEqual(args.goal, safe_harness.DEFAULT_GOAL)

    def test_uses_supplied_goal(self):
        args = safe_harness.build_arg_parser().parse_args(["fix the bug in parser.py"])
        self.assertEqual(args.goal, "fix the bug in parser.py")


class TestRealRepoLoopArgs(unittest.TestCase):
    def test_defaults_to_demo_goal_when_omitted(self):
        args = real_repo_loop.build_arg_parser().parse_args([])
        self.assertEqual(args.goal, real_repo_loop.DEFAULT_GOAL)

    def test_uses_supplied_goal(self):
        args = real_repo_loop.build_arg_parser().parse_args(["add a CONTRIBUTING.md"])
        self.assertEqual(args.goal, "add a CONTRIBUTING.md")


class TestRalphLoopArgs(unittest.TestCase):
    def test_defaults_to_project_spec_md(self):
        args = ralph_loop.build_arg_parser().parse_args([])
        self.assertTrue(args.spec.endswith("spec.md"))

    def test_uses_supplied_spec_path(self):
        args = ralph_loop.build_arg_parser().parse_args(["--spec", "other_tasks.md"])
        self.assertEqual(args.spec, "other_tasks.md")


if __name__ == "__main__":
    unittest.main()

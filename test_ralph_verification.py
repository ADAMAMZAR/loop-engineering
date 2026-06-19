import os
import unittest
from unittest.mock import patch

import ralph_loop


SPEC_WITH_VERIFY = """# spec
- [ ] Do thing one
  - verify: `python -c "exit(0)"`
- [x] Already done thing
  - verify: `python -c "exit(1)"`
- [ ] No verify command here
"""


class TestParseTasks(unittest.TestCase):
    def test_parses_verify_command_for_pending_task(self):
        tasks = ralph_loop.parse_tasks(SPEC_WITH_VERIFY.splitlines(keepends=True))
        self.assertEqual(tasks[0]["text"], "Do thing one")
        self.assertFalse(tasks[0]["done"])
        self.assertEqual(tasks[0]["verify"], 'python -c "exit(0)"')

    def test_parses_done_flag_and_verify_for_completed_task(self):
        tasks = ralph_loop.parse_tasks(SPEC_WITH_VERIFY.splitlines(keepends=True))
        self.assertTrue(tasks[1]["done"])
        self.assertEqual(tasks[1]["verify"], 'python -c "exit(1)"')

    def test_task_without_verify_line_has_none(self):
        tasks = ralph_loop.parse_tasks(SPEC_WITH_VERIFY.splitlines(keepends=True))
        self.assertIsNone(tasks[2]["verify"])


class TestRunVerification(unittest.TestCase):
    def test_passing_command_returns_true(self):
        passed, output = ralph_loop.run_verification('python -c "exit(0)"')
        self.assertTrue(passed)
        self.assertIn("exit code: 0", output)

    def test_failing_command_returns_false(self):
        passed, output = ralph_loop.run_verification('python -c "exit(1)"')
        self.assertFalse(passed)
        self.assertIn("exit code: 1", output)


class TestHandleTaskCompletion(unittest.TestCase):
    def setUp(self):
        # Point the module at a throwaway log file so tests don't pollute
        # the real ralph_audit.jsonl, and avoid touching git/spec.md by
        # mocking those calls out per-test.
        self.addCleanup(self._cleanup_log)
        ralph_loop.AUDIT_LOG_PATH = os.path.join(
            ralph_loop.WORKDIR, "test_ralph_audit.jsonl"
        )

    def _cleanup_log(self):
        if os.path.exists(ralph_loop.AUDIT_LOG_PATH):
            os.remove(ralph_loop.AUDIT_LOG_PATH)

    @patch("ralph_loop.commit_task")
    @patch("ralph_loop.mark_task_done")
    @patch("ralph_loop.load_tasks")
    def test_passing_verification_checks_off_and_commits(
        self, mock_load_tasks, mock_mark_done, mock_commit
    ):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": 'python -c "exit(0)"'}
        mock_load_tasks.return_value = ([], [task])

        success, output = ralph_loop.handle_task_completion(task)

        self.assertTrue(success)
        self.assertIsNone(output)
        mock_mark_done.assert_called_once()
        mock_commit.assert_called_once_with("Do thing")

    @patch("ralph_loop.commit_task")
    @patch("ralph_loop.mark_task_done")
    def test_failing_verification_blocks_commit(self, mock_mark_done, mock_commit):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": 'python -c "exit(1)"'}

        success, output = ralph_loop.handle_task_completion(task)

        self.assertFalse(success)
        self.assertIn("exit code: 1", output)
        mock_mark_done.assert_not_called()
        mock_commit.assert_not_called()

    @patch("ralph_loop.commit_task")
    @patch("ralph_loop.mark_task_done")
    @patch("ralph_loop.load_tasks")
    def test_no_verify_command_still_commits_with_warning(
        self, mock_load_tasks, mock_mark_done, mock_commit
    ):
        task = {"line_index": 0, "done": False, "text": "Untested thing", "verify": None}
        mock_load_tasks.return_value = ([], [task])

        success, output = ralph_loop.handle_task_completion(task)

        self.assertTrue(success)
        self.assertIsNone(output)
        mock_commit.assert_called_once_with("Untested thing")


class TestRunTaskWithRetries(unittest.TestCase):
    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_succeeds_on_first_attempt_without_retry(self, mock_run_task, mock_handle):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_handle.return_value = (True, None)

        result = ralph_loop.run_task_with_retries(task)

        self.assertTrue(result)
        mock_run_task.assert_called_once_with("Do thing", None)

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_retries_once_with_failure_context_then_succeeds(
        self, mock_run_task, mock_handle
    ):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_handle.side_effect = [(False, "exit code: 1\nstderr:\nboom"), (True, None)]

        result = ralph_loop.run_task_with_retries(task)

        self.assertTrue(result)
        self.assertEqual(mock_run_task.call_count, 2)
        first_call_args = mock_run_task.call_args_list[0].args
        second_call_args = mock_run_task.call_args_list[1].args
        self.assertEqual(first_call_args, ("Do thing", None))
        self.assertIn("boom", second_call_args[1])

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_gives_up_after_max_attempts(self, mock_run_task, mock_handle):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_handle.return_value = (False, "still failing")

        result = ralph_loop.run_task_with_retries(task)

        self.assertFalse(result)
        self.assertEqual(mock_run_task.call_count, ralph_loop.MAX_ATTEMPTS_PER_TASK)


if __name__ == "__main__":
    unittest.main()

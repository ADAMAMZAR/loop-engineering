import os
import json
import unittest
from unittest.mock import MagicMock, patch

import ralph_loop


def _tool_call_response(name="write_file", args=None, call_id="call_1"):
    """Build a fake chat-completion response carrying one tool call."""
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(args or {"path": "x.txt", "content": "x"})

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    message.model_dump.return_value = {"role": "assistant", "tool_calls": [tool_call]}

    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage.total_tokens = 10
    return response


def _final_response(content="all done"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    message.model_dump.return_value = {"role": "assistant", "content": content}

    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage.total_tokens = 10
    return response


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


class TestWarnAboutMissingVerify(unittest.TestCase):
    def test_warns_for_pending_tasks_without_verify(self):
        tasks = ralph_loop.parse_tasks(SPEC_WITH_VERIFY.splitlines(keepends=True))

        with self.assertLogs(ralph_loop.logger, level="WARNING") as captured:
            ralph_loop.warn_about_missing_verify(tasks)

        message = captured.records[0].getMessage()
        self.assertIn("No verify command here", message)
        self.assertNotIn("Do thing one", message)  # has a verify command

    def test_no_warning_when_all_pending_tasks_have_verify(self):
        tasks = [
            {"line_index": 0, "done": False, "text": "A", "verify": "cmd"},
            {"line_index": 1, "done": True, "text": "B", "verify": None},
        ]

        with self.assertNoLogs(ralph_loop.logger, level="WARNING"):
            ralph_loop.warn_about_missing_verify(tasks)


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        self._original_total = ralph_loop.total_tokens_used
        self._original_max = ralph_loop.MAX_TOKENS_PER_RUN
        self.addCleanup(self._restore)

    def _restore(self):
        ralph_loop.total_tokens_used = self._original_total
        ralph_loop.MAX_TOKENS_PER_RUN = self._original_max

    def test_record_usage_accumulates_and_flags_when_exceeded(self):
        ralph_loop.total_tokens_used = 0
        ralph_loop.MAX_TOKENS_PER_RUN = 100

        response = MagicMock()
        response.usage.total_tokens = 60
        self.assertFalse(ralph_loop.record_usage(response))  # 60/100, still under

        response.usage.total_tokens = 50
        self.assertTrue(ralph_loop.record_usage(response))  # 110/100, now over

    @patch("ralph_loop.execute_tool_call")
    @patch("ralph_loop.client")
    def test_run_task_stops_on_first_call_once_budget_exceeded(
        self, mock_client, mock_execute
    ):
        ralph_loop.total_tokens_used = 0
        ralph_loop.MAX_TOKENS_PER_RUN = 5
        mock_client.chat.completions.create.return_value = _tool_call_response()

        outcome, detail = ralph_loop.run_task("some task")

        self.assertEqual(outcome, "budget_exceeded")
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)
        mock_execute.assert_not_called()  # never even reached the tool-call handling

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_run_task_with_retries_does_not_retry_on_budget_exceeded(
        self, mock_run_task, mock_handle
    ):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_run_task.return_value = ("budget_exceeded", "out of tokens")

        result = ralph_loop.run_task_with_retries(task)

        self.assertFalse(result)
        mock_run_task.assert_called_once()  # no retry burns more budget
        mock_handle.assert_not_called()


class TestRunTaskNonConvergence(unittest.TestCase):
    """run_task talks to a mocked client/tool executor so no real API call
    or file write happens — only the loop's own convergence logic is under
    test here.
    """

    @patch("ralph_loop.execute_tool_call")
    @patch("ralph_loop.client")
    def test_completes_normally_when_model_stops_requesting_tools(
        self, mock_client, mock_execute
    ):
        mock_client.chat.completions.create.return_value = _final_response("Task complete.")

        outcome, detail = ralph_loop.run_task("some task")

        self.assertEqual(outcome, "completed")
        self.assertEqual(detail, "Task complete.")
        mock_execute.assert_not_called()

    @patch("ralph_loop.execute_tool_call")
    @patch("ralph_loop.client")
    def test_stuck_on_repeated_identical_tool_call(self, mock_client, mock_execute):
        mock_client.chat.completions.create.return_value = _tool_call_response()
        mock_execute.return_value = "Error: something went wrong"

        outcome, detail = ralph_loop.run_task("some task")

        self.assertEqual(outcome, "stuck")
        self.assertIn("Error: something went wrong", detail)
        self.assertEqual(
            mock_client.chat.completions.create.call_count, ralph_loop.STUCK_REPEAT_THRESHOLD
        )

    @patch("ralph_loop.execute_tool_call")
    @patch("ralph_loop.client")
    def test_max_iterations_when_never_stuck_but_never_finishes(
        self, mock_client, mock_execute
    ):
        # Vary the tool call's args each time so the "stuck" detector never
        # fires, but the model also never stops requesting tools.
        n = ralph_loop.MAX_ITERATIONS_PER_TASK
        mock_client.chat.completions.create.side_effect = [
            _tool_call_response(args={"path": f"f{i}.txt", "content": "x"}) for i in range(n)
        ]
        mock_execute.side_effect = [f"Wrote {i} characters" for i in range(n)]

        outcome, detail = ralph_loop.run_task("some task")

        self.assertEqual(outcome, "max_iterations")
        self.assertEqual(mock_client.chat.completions.create.call_count, n)


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
        mock_run_task.return_value = ("completed", "done")
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
        mock_run_task.return_value = ("completed", "done")
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
        mock_run_task.return_value = ("completed", "done")
        mock_handle.return_value = (False, "still failing")

        result = ralph_loop.run_task_with_retries(task)

        self.assertFalse(result)
        self.assertEqual(mock_run_task.call_count, ralph_loop.MAX_ATTEMPTS_PER_TASK)

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_non_convergence_retries_with_reason_then_succeeds(
        self, mock_run_task, mock_handle
    ):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_run_task.side_effect = [
            ("stuck", "Stuck: write_file repeated the same failing result"),
            ("completed", "done"),
        ]
        mock_handle.return_value = (True, None)

        result = ralph_loop.run_task_with_retries(task)

        self.assertTrue(result)
        self.assertEqual(mock_run_task.call_count, 2)
        second_call_args = mock_run_task.call_args_list[1].args
        self.assertIn("Stuck", second_call_args[1])
        mock_handle.assert_called_once()  # not called for the non-converged attempt

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_non_convergence_on_every_attempt_gives_up(self, mock_run_task, mock_handle):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_run_task.return_value = ("max_iterations", "Hit the iteration cap")

        result = ralph_loop.run_task_with_retries(task)

        self.assertFalse(result)
        self.assertEqual(mock_run_task.call_count, ralph_loop.MAX_ATTEMPTS_PER_TASK)
        mock_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()

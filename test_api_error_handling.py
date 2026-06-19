import unittest
from unittest.mock import MagicMock, patch

import httpx
import openai

import safe_harness
import real_repo_loop
import ralph_loop


def _api_error():
    request = httpx.Request("POST", "https://example.invalid/")
    return openai.APIConnectionError(message="connection failed", request=request)


class TestHasApiKey(unittest.TestCase):
    def test_safe_harness_true_when_set(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "key"}):
            self.assertTrue(safe_harness.has_api_key())

    def test_safe_harness_false_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(safe_harness.has_api_key())

    def test_real_repo_loop_true_when_set(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "key"}):
            self.assertTrue(real_repo_loop.has_api_key())

    def test_real_repo_loop_false_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(real_repo_loop.has_api_key())

    def test_ralph_loop_true_when_set(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "key"}):
            self.assertTrue(ralph_loop.has_api_key())

    def test_ralph_loop_false_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(ralph_loop.has_api_key())


class TestCallModel(unittest.TestCase):
    @patch("safe_harness.client")
    def test_safe_harness_returns_response_on_success(self, mock_client):
        mock_client.chat.completions.create.return_value = "a response"
        response, error = safe_harness.call_model([])
        self.assertEqual(response, "a response")
        self.assertIsNone(error)

    @patch("safe_harness.client")
    def test_safe_harness_returns_error_on_api_failure(self, mock_client):
        mock_client.chat.completions.create.side_effect = _api_error()
        response, error = safe_harness.call_model([])
        self.assertIsNone(response)
        self.assertIn("connection failed", error)

    @patch("real_repo_loop.client")
    def test_real_repo_loop_returns_response_on_success(self, mock_client):
        mock_client.chat.completions.create.return_value = "a response"
        response, error = real_repo_loop.call_model([])
        self.assertEqual(response, "a response")
        self.assertIsNone(error)

    @patch("real_repo_loop.client")
    def test_real_repo_loop_returns_error_on_api_failure(self, mock_client):
        mock_client.chat.completions.create.side_effect = _api_error()
        response, error = real_repo_loop.call_model([])
        self.assertIsNone(response)
        self.assertIn("connection failed", error)

    @patch("ralph_loop.client")
    def test_ralph_loop_returns_response_on_success(self, mock_client):
        mock_client.chat.completions.create.return_value = "a response"
        response, error = ralph_loop.call_model([])
        self.assertEqual(response, "a response")
        self.assertIsNone(error)

    @patch("ralph_loop.client")
    def test_ralph_loop_returns_error_on_api_failure(self, mock_client):
        mock_client.chat.completions.create.side_effect = _api_error()
        response, error = ralph_loop.call_model([])
        self.assertIsNone(response)
        self.assertIn("connection failed", error)


class TestRunTaskApiError(unittest.TestCase):
    @patch("ralph_loop.execute_tool_call")
    @patch("ralph_loop.call_model")
    def test_run_task_returns_api_error_outcome(self, mock_call_model, mock_execute):
        mock_call_model.return_value = (None, "connection failed")

        outcome, detail = ralph_loop.run_task("some task")

        self.assertEqual(outcome, "api_error")
        self.assertIn("connection failed", detail)
        mock_execute.assert_not_called()

    @patch("ralph_loop.handle_task_completion")
    @patch("ralph_loop.run_task")
    def test_run_task_with_retries_does_not_retry_on_api_error(
        self, mock_run_task, mock_handle
    ):
        task = {"line_index": 0, "done": False, "text": "Do thing", "verify": "cmd"}
        mock_run_task.return_value = ("api_error", "connection failed")

        result = ralph_loop.run_task_with_retries(task)

        self.assertFalse(result)
        mock_run_task.assert_called_once()
        mock_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()

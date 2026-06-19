import os
import json
import unittest

import audit_replay


TOOL_EVENT = {"tool": "write_file", "args": {"path": "x.txt"}, "decision": "approved", "timestamp": "2026-06-19T10:00:00"}
DENIED_EVENT = {"tool": "run_shell", "args": {"command": "git push"}, "decision": "denied", "timestamp": "2026-06-19T11:00:00"}
VERIFY_EVENT = {"task": "Create greet.py", "verify_command": "python greet.py", "verify_passed": True, "verify_output": "ok", "timestamp": "2026-06-19T12:00:00"}
NON_CONVERGENCE_EVENT = {"task": "Create math_ops.py", "non_convergence": "stuck", "detail": "Stuck: write_file repeated", "timestamp": "2026-06-19T13:00:00"}

ALL_EVENTS = [TOOL_EVENT, DENIED_EVENT, VERIFY_EVENT, NON_CONVERGENCE_EVENT]


class TestLoadEvents(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(os.path.dirname(__file__), "test_audit_replay_fixture.jsonl")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_loads_valid_jsonl_lines(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(TOOL_EVENT) + "\n")
            f.write(json.dumps(DENIED_EVENT) + "\n")

        events = audit_replay.load_events(self.path)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["tool"], "write_file")

    def test_skips_blank_and_malformed_lines(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(TOOL_EVENT) + "\n")
            f.write("\n")
            f.write("{not valid json\n")
            f.write(json.dumps(DENIED_EVENT) + "\n")

        events = audit_replay.load_events(self.path)

        self.assertEqual(len(events), 2)


class TestFilterEvents(unittest.TestCase):
    def test_filter_by_tool(self):
        result = audit_replay.filter_events(ALL_EVENTS, tool="write_file")
        self.assertEqual(result, [TOOL_EVENT])

    def test_filter_by_decision(self):
        result = audit_replay.filter_events(ALL_EVENTS, decision="denied")
        self.assertEqual(result, [DENIED_EVENT])

    def test_filter_by_task_substring(self):
        result = audit_replay.filter_events(ALL_EVENTS, task_contains="greet")
        self.assertEqual(result, [VERIFY_EVENT])

    def test_filter_by_since(self):
        result = audit_replay.filter_events(ALL_EVENTS, since="2026-06-19T12:00:00")
        self.assertEqual(result, [VERIFY_EVENT, NON_CONVERGENCE_EVENT])

    def test_filter_by_until(self):
        result = audit_replay.filter_events(ALL_EVENTS, until="2026-06-19T11:00:00")
        self.assertEqual(result, [TOOL_EVENT, DENIED_EVENT])

    def test_combining_filters(self):
        result = audit_replay.filter_events(ALL_EVENTS, tool="write_file", decision="approved")
        self.assertEqual(result, [TOOL_EVENT])

    def test_filter_does_not_error_on_events_missing_the_field(self):
        # TOOL_EVENT has no "task" key at all — task_contains must not crash on it.
        result = audit_replay.filter_events(ALL_EVENTS, task_contains="x.txt")
        self.assertEqual(result, [])

    def test_no_filters_returns_everything(self):
        result = audit_replay.filter_events(ALL_EVENTS)
        self.assertEqual(result, ALL_EVENTS)


class TestFormatEvent(unittest.TestCase):
    def test_formats_tool_event(self):
        text = audit_replay.format_event(TOOL_EVENT)
        self.assertIn("write_file", text)
        self.assertIn("approved", text)

    def test_formats_verify_event(self):
        text = audit_replay.format_event(VERIFY_EVENT)
        self.assertIn("PASSED", text)
        self.assertIn("greet.py", text)

    def test_formats_non_convergence_event(self):
        text = audit_replay.format_event(NON_CONVERGENCE_EVENT)
        self.assertIn("stuck", text)
        self.assertIn("math_ops.py", text)


if __name__ == "__main__":
    unittest.main()

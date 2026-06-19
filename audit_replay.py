"""Query and pretty-print an audit log (audit_log.jsonl, ralph_audit.jsonl,
real_repo_audit.jsonl), instead of having to read raw JSON lines by eye.

Usage:
    python audit_replay.py audit_log.jsonl
    python audit_replay.py ralph_audit.jsonl --tool write_file
    python audit_replay.py audit_log.jsonl --decision denied
    python audit_replay.py ralph_audit.jsonl --task "greet.py"
    python audit_replay.py audit_log.jsonl --since 2026-06-19T00:00:00

The audit log files written by safe_harness.py, ralph_loop.py, and
real_repo_loop.py don't all share one event shape (tool calls, verification
results, and non-convergence reports each carry different fields) — every
filter here is a no-op against events missing the relevant field, rather
than an error, so one tool works across all of them.
"""

import sys
import json
import argparse


def load_events(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: skipping malformed line {line_number}: {e}", file=sys.stderr)
    return events


def filter_events(events, tool=None, decision=None, task_contains=None, since=None, until=None):
    """Pure filtering logic, split out from CLI/file I/O so it's testable.

    Each filter only applies to events that have the relevant field; events
    missing it pass through unaffected by that particular filter.
    """
    result = events
    if tool is not None:
        result = [e for e in result if e.get("tool") == tool]
    if decision is not None:
        result = [e for e in result if e.get("decision") == decision]
    if task_contains is not None:
        result = [e for e in result if task_contains in e.get("task", "")]
    if since is not None:
        result = [e for e in result if e.get("timestamp", "") >= since]
    if until is not None:
        result = [e for e in result if e.get("timestamp", "") <= until]
    return result


def format_event(event):
    timestamp = event.get("timestamp", "?")
    if "tool" in event:
        decision = event.get("decision", "?")
        return f"[{timestamp}] tool={event['tool']} decision={decision} args={event.get('args')}"
    if "verify_command" in event:
        passed = event.get("verify_passed")
        status = "PASSED" if passed else "FAILED"
        return f"[{timestamp}] verify {status} task={event.get('task')!r} command={event['verify_command']!r}"
    if "non_convergence" in event:
        return (
            f"[{timestamp}] non_convergence={event['non_convergence']} "
            f"task={event.get('task')!r} detail={event.get('detail')}"
        )
    return f"[{timestamp}] {event}"


def main():
    parser = argparse.ArgumentParser(description="Query and replay an audit log JSONL file.")
    parser.add_argument("path", help="Path to the audit log file, e.g. audit_log.jsonl")
    parser.add_argument("--tool", help="Only show events for this tool name")
    parser.add_argument("--decision", help="Only show events with this decision (approved/denied/auto/...)")
    parser.add_argument("--task", dest="task_contains", help="Only show events whose task text contains this substring")
    parser.add_argument("--since", help="Only show events with timestamp >= this ISO string")
    parser.add_argument("--until", help="Only show events with timestamp <= this ISO string")
    args = parser.parse_args()

    events = load_events(args.path)
    filtered = filter_events(
        events,
        tool=args.tool,
        decision=args.decision,
        task_contains=args.task_contains,
        since=args.since,
        until=args.until,
    )

    for event in filtered:
        print(format_event(event))
    print(f"\n{len(filtered)} of {len(events)} events shown.")


if __name__ == "__main__":
    main()

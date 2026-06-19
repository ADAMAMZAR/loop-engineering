# Ralph loop spec

Each task below is implemented by its own fresh agent instance with no
memory of the others. Check items off only by running `ralph_loop.py` —
it edits this file and commits automatically.

- [x] Create `greet.py` with a function `greet(name)` that returns
  `f"Hello, {name}!"`, plus a `if __name__ == "__main__":` block that
  prints `greet("World")`. Verify it by running `python greet.py` and
  confirming the output is `Hello, World!`.
- [ ] Create `math_ops.py` with functions `add(a, b)` and `multiply(a, b)`.
  Then create `test_math_ops.py` with assert-based checks for both
  functions, and run it with `python test_math_ops.py` to confirm it
  passes silently (no AssertionError).

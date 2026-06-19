"""Shared API key resolution for safe_harness.py, ralph_loop.py, and
real_repo_loop.py.

A plain environment variable (which a .env file just populates) already
works with most real deployment mechanisms: Docker --env-file, a Kubernetes
Secret mounted via envFrom, a CI provider's secrets, a systemd
EnvironmentFile. What it doesn't cover is the "secret as a file" pattern
those same platforms often prefer instead (Docker/Kubernetes secrets are
commonly mounted as files, and official Docker images expose this via a
"_FILE" suffix convention, e.g. POSTGRES_PASSWORD_FILE) — a mounted file with
restrictive permissions doesn't show up in `docker inspect` or a process
listing the way an env var can.
"""

import os

API_KEY_ENV_VAR = "GOOGLE_API_KEY"
API_KEY_FILE_ENV_VAR = "GOOGLE_API_KEY_FILE"


def resolve_api_key():
    """Return the API key, preferring GOOGLE_API_KEY if set, then reading
    the file named by GOOGLE_API_KEY_FILE if that's set instead. Returns
    None if neither resolves to a usable key.
    """
    key = os.environ.get(API_KEY_ENV_VAR)
    if key:
        return key

    key_file = os.environ.get(API_KEY_FILE_ENV_VAR)
    if key_file:
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            return content or None
        except OSError:
            return None

    return None


def has_api_key():
    return bool(resolve_api_key())

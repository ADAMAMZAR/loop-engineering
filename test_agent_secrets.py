import os
import tempfile
import unittest
from unittest.mock import patch

import agent_secrets


class TestResolveApiKey(unittest.TestCase):
    def test_returns_env_var_when_set(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "from-env"}, clear=True):
            self.assertEqual(agent_secrets.resolve_api_key(), "from-env")

    def test_returns_none_when_neither_is_set(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(agent_secrets.resolve_api_key())

    def test_reads_from_file_when_env_var_missing(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".secret", delete=False
        ) as f:
            f.write("from-file\n")
            path = f.name
        try:
            with patch.dict(
                os.environ, {"GOOGLE_API_KEY_FILE": path}, clear=True
            ):
                self.assertEqual(agent_secrets.resolve_api_key(), "from-file")
        finally:
            os.remove(path)

    def test_env_var_takes_priority_over_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".secret", delete=False
        ) as f:
            f.write("from-file")
            path = f.name
        try:
            with patch.dict(
                os.environ,
                {"GOOGLE_API_KEY": "from-env", "GOOGLE_API_KEY_FILE": path},
                clear=True,
            ):
                self.assertEqual(agent_secrets.resolve_api_key(), "from-env")
        finally:
            os.remove(path)

    def test_returns_none_when_file_path_does_not_exist(self):
        with patch.dict(
            os.environ, {"GOOGLE_API_KEY_FILE": "/no/such/file"}, clear=True
        ):
            self.assertIsNone(agent_secrets.resolve_api_key())

    def test_returns_none_when_file_is_empty(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".secret", delete=False
        ) as f:
            path = f.name
        try:
            with patch.dict(
                os.environ, {"GOOGLE_API_KEY_FILE": path}, clear=True
            ):
                self.assertIsNone(agent_secrets.resolve_api_key())
        finally:
            os.remove(path)


class TestHasApiKey(unittest.TestCase):
    def test_true_when_resolvable(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "x"}, clear=True):
            self.assertTrue(agent_secrets.has_api_key())

    def test_false_when_not_resolvable(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(agent_secrets.has_api_key())


if __name__ == "__main__":
    unittest.main()

import os
import logging
import unittest
from unittest.mock import patch

import agent_logging


class TestConfigureLogging(unittest.TestCase):
    def setUp(self):
        # basicConfig() is a no-op once handlers exist, so each test gets a
        # clean root logger to actually observe the level it requests.
        self._original_handlers = logging.root.handlers[:]
        self._original_level = logging.root.level
        logging.root.handlers = []
        self.addCleanup(self._restore)

    def _restore(self):
        logging.root.handlers = self._original_handlers
        logging.root.level = self._original_level

    def test_defaults_to_info_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            agent_logging.configure_logging()
        self.assertEqual(logging.root.level, logging.INFO)

    def test_respects_log_level_env_var(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=True):
            agent_logging.configure_logging()
        self.assertEqual(logging.root.level, logging.DEBUG)

    def test_falls_back_to_info_for_unrecognized_level(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "NOT_A_LEVEL"}, clear=True):
            agent_logging.configure_logging()
        self.assertEqual(logging.root.level, logging.INFO)


if __name__ == "__main__":
    unittest.main()

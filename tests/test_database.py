import unittest
import sys
import os
import queue
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.services.database import DatabaseManager


class TestDatabaseWriteTimeout(unittest.TestCase):

    def _make_manager(self):
        with patch.object(DatabaseManager, '_ensure_tables_sync'), \
             patch.object(DatabaseManager, '_apply_pragma_sync'):
            mgr = DatabaseManager.__new__(DatabaseManager)
            mgr._write_queue = queue.Queue()
            mgr._writer_thread = None  # type: ignore[assignment]
            mgr._db_path = ":memory:"  # type: ignore[attr-defined]
            mgr._running = True  # type: ignore[attr-defined]
            return mgr

    def test_queue_write_no_wait(self):
        mgr = self._make_manager()
        mock_func = MagicMock(return_value=42)
        result = mgr._queue_write(mock_func, wait=False)
        self.assertEqual(result, 1)
        self.assertFalse(mgr._write_queue.empty())

    def test_queue_write_wait_success(self):
        mgr = self._make_manager()

        def fake_writer():
            task = mgr._write_queue.get(timeout=2)
            func, args, kwargs, result_queue = task
            result_queue.put(("success", 99))

        t = threading.Thread(target=fake_writer, daemon=True)
        t.start()

        mock_func = MagicMock(return_value=99)
        result = mgr._queue_write(mock_func, wait=True)
        self.assertEqual(result, 99)
        t.join(timeout=3)

    def test_queue_write_wait_timeout(self):
        mgr = self._make_manager()
        mgr._WRITE_TIMEOUT = 0.5

        mock_func = MagicMock(return_value=0)
        mgr._write_queue.put((mock_func, (), {}, None))

        result = mgr._queue_write(mock_func, wait=True)
        self.assertEqual(result, -1)

    def test_queue_write_wait_error_response(self):
        mgr = self._make_manager()

        def fake_writer_error():
            task = mgr._write_queue.get(timeout=2)
            func, args, kwargs, result_queue = task
            result_queue.put(("error", RuntimeError("db error")))

        t = threading.Thread(target=fake_writer_error, daemon=True)
        t.start()

        mock_func = MagicMock(side_effect=RuntimeError("db error"))
        result = mgr._queue_write(mock_func, wait=True)
        self.assertEqual(result, -1)
        t.join(timeout=3)


if __name__ == '__main__':
    unittest.main()

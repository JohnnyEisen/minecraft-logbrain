import unittest
import sys
import os
import time
import threading
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.threading_utils import (
    ThreadPoolManager,
    get_global_pool,
    set_pool_size,
    submit_task,
    run_in_thread,
    RepeatingWorker,
    BackgroundWatcher,
)


class TestThreadPoolManager(unittest.TestCase):

    def tearDown(self):
        ThreadPoolManager.reset()

    def test_singleton(self):
        m1 = ThreadPoolManager.get_instance()
        m2 = ThreadPoolManager.get_instance()
        self.assertIs(m1, m2)

    def test_get_pool_creates(self):
        manager = ThreadPoolManager.get_instance()
        pool = manager.get_pool("test_pool", max_workers=2)
        self.assertIn("test_pool", manager._pools)
        self.assertEqual(manager._pool_configs["test_pool"], 2)

    def test_get_pool_reuses(self):
        manager = ThreadPoolManager.get_instance()
        pool1 = manager.get_pool("reuse_pool", max_workers=1)
        pool2 = manager.get_pool("reuse_pool")
        self.assertIs(pool1, pool2)

    def test_submit_task(self):
        manager = ThreadPoolManager.get_instance()

        def add(a, b):
            return a + b

        future = manager.submit("test_submit", add, 1, 2)
        result = future.result(timeout=5)
        self.assertEqual(result, 3)

    def test_default_max_workers(self):
        manager = ThreadPoolManager.get_instance()
        cpu_count = os.cpu_count() or 4
        expected = min(cpu_count * 4, 32)
        self.assertEqual(manager.default_max_workers, expected)

    def test_set_default_max_workers(self):
        manager = ThreadPoolManager.get_instance()
        manager.default_max_workers = 5
        self.assertEqual(manager.default_max_workers, 5)

    def test_shutdown_pool(self):
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("shutdown_test")
        self.assertIn("shutdown_test", manager._pools)
        manager.shutdown_pool("shutdown_test")
        self.assertNotIn("shutdown_test", manager._pools)

    def test_shutdown_all(self):
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("pool_a")
        manager.get_pool("pool_b")
        manager.shutdown_all(wait=False)
        self.assertEqual(len(manager._pools), 0)

    def test_shutdown_all_with_wait(self):
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("pool_wait")
        future = manager.submit("pool_wait", lambda: 42)
        manager.shutdown_all(wait=True)
        self.assertEqual(future.result(), 42)

    def test_get_stats(self):
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("stats_pool", max_workers=3)
        stats = manager.get_stats()
        self.assertIn("pools", stats)
        self.assertIn("stats_pool", stats["pools"])
        self.assertEqual(stats["pools"]["stats_pool"]["max_workers"], 3)

    def test_get_executor(self):
        manager = ThreadPoolManager.get_instance()
        executor = manager.get_executor("exec_test")
        self.assertIsNotNone(executor)

    def test_process_pool_none_by_default(self):
        manager = ThreadPoolManager.get_instance()
        pool = manager.get_process_pool()
        self.assertIsNotNone(pool)
        manager.shutdown_all()

    def test_submit_to_process_none_returns_none(self):
        ThreadPoolManager.reset()
        manager = ThreadPoolManager.get_instance()
        manager._process_pool = None
        with patch.object(manager, "get_process_pool", return_value=None):
            result = manager.submit_to_process(lambda: 1)
            self.assertIsNone(result)

    def test_reset(self):
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("reset_test")
        ThreadPoolManager.reset()
        manager2 = ThreadPoolManager.get_instance()
        self.assertNotIn("reset_test", manager2._pools)

    def test_atexit_registered(self):
        ThreadPoolManager.reset()
        manager = ThreadPoolManager.get_instance()
        manager.get_pool("atexit_test")
        self.assertTrue(manager._shutdown_registered)


class TestGlobalPool(unittest.TestCase):

    def tearDown(self):
        try:
            ThreadPoolManager.reset()
        except Exception:
            pass

    @patch("mca_core.threading_utils._global_pool", None)
    def test_get_global_pool_lazy(self):
        pool = get_global_pool()
        self.assertIsNotNone(pool)

    @patch("mca_core.threading_utils._global_pool", None)
    @patch("mca_core.threading_utils._pool_max_workers", None)
    def test_set_pool_size_before_init(self):
        set_pool_size(5)
        from mca_core.threading_utils import _pool_max_workers
        self.assertEqual(_pool_max_workers, 5)

    def test_set_pool_size_after_init(self):
        pool = get_global_pool()
        set_pool_size(2)


class TestSubmitTask(unittest.TestCase):

    def tearDown(self):
        try:
            ThreadPoolManager.reset()
        except Exception:
            pass

    @patch("mca_core.threading_utils._global_pool", None)
    def test_submit_task(self):
        def square(x):
            return x * x

        future = submit_task(square, 5)
        result = future.result(timeout=5)
        self.assertEqual(result, 25)

    @patch("mca_core.threading_utils._global_pool", None)
    def test_submit_task_with_kwargs(self):
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}"

        future = submit_task(greet, "World", greeting="Hi")
        result = future.result(timeout=5)
        self.assertEqual(result, "Hi, World")


class TestRunInThread(unittest.TestCase):

    def test_run_in_thread(self):
        result_container = []

        def task():
            result_container.append(42)

        thread = run_in_thread(task, name="test_thread")
        self.assertTrue(thread.daemon)
        thread.join(timeout=5)
        self.assertEqual(result_container, [42])

    def test_run_in_thread_non_daemon(self):
        result_container = []

        def task():
            result_container.append(1)

        thread = run_in_thread(task, name="non_daemon", daemon=False)
        thread.join(timeout=5)
        self.assertEqual(result_container, [1])

    def test_run_in_thread_with_name(self):
        def task():
            pass

        thread = run_in_thread(task, name="named_thread")
        self.assertIn("named_thread", thread.name)
        thread.join(timeout=5)


class TestRepeatingWorker(unittest.TestCase):

    def setUp(self):
        self.errors = []

    def test_start_and_stop(self):
        called = []

        def task():
            called.append(1)

        worker = RepeatingWorker(task, interval=0.05, initial_delay=0.01)
        self.assertFalse(worker.is_running)
        worker.start()
        time.sleep(0.15)
        self.assertTrue(worker.is_running)
        self.assertTrue(len(called) >= 1)
        worker.stop(timeout=2)
        self.assertFalse(worker.is_running)

    def test_double_start(self):
        called = []

        def task():
            called.append(1)

        worker = RepeatingWorker(task, interval=0.1)
        worker.start()
        thread1 = worker._thread
        worker.start()
        self.assertIs(worker._thread, thread1)
        worker.stop(timeout=2)

    def test_error_callback(self):
        error_caught = []

        def task():
            raise ValueError("test error")

        def on_error(e):
            error_caught.append(e)

        worker = RepeatingWorker(task, interval=0.05, on_error=on_error, initial_delay=0.01)
        worker.start()
        time.sleep(0.15)
        worker.stop(timeout=2)
        self.assertTrue(len(error_caught) >= 1)
        self.assertIsInstance(error_caught[0], ValueError)

    def test_error_no_callback(self):
        def task():
            raise RuntimeError("silent error")

        worker = RepeatingWorker(task, interval=0.05, initial_delay=0.01)
        worker.start()
        time.sleep(0.15)
        worker.stop(timeout=2)

    def test_initial_delay(self):
        called_at = []

        def task():
            called_at.append(time.time())

        worker = RepeatingWorker(task, interval=0.1, initial_delay=0.2)
        start = time.time()
        worker.start()
        time.sleep(0.3)
        worker.stop(timeout=2)
        if called_at:
            self.assertGreaterEqual(called_at[0] - start, 0.15)

    def test_stop_with_timeout(self):
        def task():
            time.sleep(0.01)

        worker = RepeatingWorker(task, interval=0.05)
        worker.start()
        time.sleep(0.05)
        worker.stop(timeout=2)

    def test_is_running_initial(self):
        def task():
            pass

        worker = RepeatingWorker(task, interval=1.0)
        self.assertFalse(worker.is_running)


class TestBackgroundWatcher(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_start_and_stop(self):
        called = []

        def on_change():
            called.append(1)

        test_file = os.path.join(self.tmpdir, "watch.txt")
        with open(test_file, "w") as f:
            f.write("initial")

        watcher = BackgroundWatcher(test_file, on_change, poll_interval=0.05)
        watcher.start()
        time.sleep(0.1)

        with open(test_file, "w") as f:
            f.write("changed")
        time.sleep(0.15)

        watcher.stop()
        self.assertGreater(len(called), 0)

    def test_file_not_exists(self):
        called = []

        def on_change():
            called.append(1)

        watcher = BackgroundWatcher("/nonexistent/file.txt", on_change, poll_interval=0.05)
        watcher.start()
        time.sleep(0.1)
        watcher.stop()
        self.assertEqual(len(called), 0)

    def test_double_start(self):
        called = []

        def on_change():
            called.append(1)

        test_file = os.path.join(self.tmpdir, "watch2.txt")
        with open(test_file, "w") as f:
            f.write("initial")

        watcher = BackgroundWatcher(test_file, on_change, poll_interval=0.1)
        watcher.start()
        worker1 = watcher._worker
        watcher.start()
        self.assertIs(watcher._worker, worker1)
        watcher.stop()

    def test_file_path_property(self):
        test_file = os.path.join(self.tmpdir, "prop.txt")
        watcher = BackgroundWatcher(test_file, lambda: None)
        self.assertEqual(watcher.file_path, test_file)

    def test_no_change(self):
        called = []

        def on_change():
            called.append(1)

        test_file = os.path.join(self.tmpdir, "nochange.txt")
        with open(test_file, "w") as f:
            f.write("static")

        watcher = BackgroundWatcher(test_file, on_change, poll_interval=0.05)
        watcher.start()
        time.sleep(0.15)
        watcher.stop()
        self.assertEqual(len(called), 0)


class TestThreadPoolManagerThreadSafety(unittest.TestCase):

    def tearDown(self):
        ThreadPoolManager.reset()

    def test_concurrent_submit(self):
        manager = ThreadPoolManager.get_instance()
        errors = []

        def safe_op(x):
            return x * 2

        futures = []
        for i in range(20):
            f = manager.submit("concurrent", safe_op, i)
            futures.append(f)

        for i, f in enumerate(futures):
            try:
                result = f.result(timeout=5)
                self.assertEqual(result, i * 2)
            except Exception as e:
                errors.append(e)

        self.assertEqual(len(errors), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
from __future__ import annotations

import threading
import unittest

from mca_core.state import ThreadSafeState


class TestThreadSafeState(unittest.TestCase):
    def test_update_and_get(self):
        state = ThreadSafeState()
        state.update("key1", "value1")
        self.assertEqual(state.get("key1"), "value1")

    def test_get_default(self):
        state = ThreadSafeState()
        self.assertIsNone(state.get("missing"))
        self.assertEqual(state.get("missing", 42), 42)

    def test_update_notifies_callback(self):
        state = ThreadSafeState()
        changes = []
        state.subscribe(lambda k, o, n: changes.append((k, o, n)))
        state.update("x", 1)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], ("x", None, 1))

    def test_update_notifies_old_value(self):
        state = ThreadSafeState()
        changes = []
        state.subscribe(lambda k, o, n: changes.append((k, o, n)))
        state.update("x", 1)
        state.update("x", 2)
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[1], ("x", 1, 2))

    def test_callback_exception_does_not_break(self):
        state = ThreadSafeState()
        good = []
        state.subscribe(lambda k, o, n: (_ for _ in ()).throw(RuntimeError))
        state.subscribe(lambda k, o, n: good.append(n))
        state.update("x", 42)
        self.assertEqual(good, [42])

    def test_no_deadlock_on_callback_update(self):
        state = ThreadSafeState()
        state.subscribe(lambda k, o, n: state.update(k, n + 1))
        state.update("x", 0)
        self.assertGreaterEqual(state.get("x"), 1)

    def test_concurrent_updates_no_crash(self):
        state = ThreadSafeState()
        n = 50
        barrier = threading.Barrier(n)
        def worker():
            barrier.wait()
            for i in range(100):
                state.update(f"key_{i}", i)
        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(state.get("key_0"), 0)
        self.assertEqual(state.get("key_99"), 99)


if __name__ == "__main__":
    unittest.main()

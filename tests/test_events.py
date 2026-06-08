from __future__ import annotations

import threading
import time
import unittest

from mca_core.events import EventBus, AnalysisEvent, get_event_bus, reset_event_bus


class TestEventBus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe("test.event", lambda e: received.append(e.payload))
        bus.publish(AnalysisEvent("test.event", {"key": "value"}))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["key"], "value")

    def test_multiple_subscribers(self):
        bus = EventBus()
        count_a = []
        count_b = []
        bus.subscribe("evt", lambda e: count_a.append(1))
        bus.subscribe("evt", lambda e: count_b.append(1))
        bus.publish(AnalysisEvent("evt", {}))
        self.assertEqual(len(count_a), 1)
        self.assertEqual(len(count_b), 1)

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e.payload)
        bus.subscribe("evt", handler)
        bus.unsubscribe("evt", handler)
        bus.publish(AnalysisEvent("evt", {"v": 1}))
        self.assertEqual(len(received), 0)

    def test_unsubscribe_via_returned_fn(self):
        bus = EventBus()
        received = []
        unsub = bus.subscribe("evt", lambda e: received.append(e.payload))
        unsub()
        bus.publish(AnalysisEvent("evt", {"v": 1}))
        self.assertEqual(len(received), 0)

    def test_publish_no_subscribers(self):
        bus = EventBus()
        bus.publish(AnalysisEvent("nonexistent.event", {}))

    def test_subscriber_exception_does_not_break_others(self):
        bus = EventBus()
        good = []
        bus.subscribe("evt", lambda e: good.append(1))
        bus.subscribe("evt", lambda e: self._raise())
        bus.subscribe("evt", lambda e: good.append(2))
        bus.publish(AnalysisEvent("evt", {}))
        self.assertGreaterEqual(len(good), 1)

    def test_get_event_bus_singleton(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)

    def test_get_event_bus_thread_safety(self):
        results = []
        def get_bus():
            results.append(get_event_bus())
        threads = [threading.Thread(target=get_bus) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(id(b) for b in results)), 1)

    def test_reset_event_bus(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        self.assertIsNot(bus1, bus2)

    @staticmethod
    def _raise():
        raise RuntimeError("boom")


if __name__ == "__main__":
    unittest.main()

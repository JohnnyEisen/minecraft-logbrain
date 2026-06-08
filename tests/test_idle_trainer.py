import unittest
import sys
import os
import threading
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestIdleTrainerStopJoin(unittest.TestCase):

    @patch('mca_core.idle_trainer.psutil', create=True)
    @patch('mca_core.idle_trainer.GPUtil', None)
    def test_stop_joins_thread(self, mock_psutil):
        try:
            from mca_core.idle_trainer import IdleTrainer
        except ImportError:
            self.skipTest("IdleTrainer not available")

        mock_learner = MagicMock()
        mock_psutil.cpu_percent.return_value = 5
        mock_psutil.virtual_memory.return_value = MagicMock(percent=30)

        with patch('mca_core.idle_trainer.generate_batch', return_value=[]):
            trainer = IdleTrainer(mock_learner, output_dir=".")
            trainer.start()
            self.assertTrue(trainer.running)
            self.assertTrue(trainer.thread.is_alive())

            trainer.stop()
            self.assertFalse(trainer.running)
            self.assertFalse(trainer.thread.is_alive(), "Thread should be joined after stop()")

    @patch('mca_core.idle_trainer.psutil', create=True)
    @patch('mca_core.idle_trainer.GPUtil', None)
    def test_stop_start_no_double_thread(self, mock_psutil):
        try:
            from mca_core.idle_trainer import IdleTrainer
        except ImportError:
            self.skipTest("IdleTrainer not available")

        mock_learner = MagicMock()
        mock_psutil.cpu_percent.return_value = 90
        mock_psutil.virtual_memory.return_value = MagicMock(percent=90)

        with patch('mca_core.idle_trainer.generate_batch', return_value=[]):
            trainer = IdleTrainer(mock_learner, output_dir=".")
            trainer.start()
            tid1 = trainer.thread.ident

            trainer.stop()
            trainer.start()
            tid2 = trainer.thread.ident

            self.assertNotEqual(tid1, tid2, "New thread should be created after stop+start")
            trainer.stop()


class TestIdleTrainerKeyErrorGuard(unittest.TestCase):

    @patch('mca_core.idle_trainer.psutil', create=True)
    @patch('mca_core.idle_trainer.GPUtil', None)
    def test_summary_missing_file_key(self, mock_psutil):
        try:
            from mca_core.idle_trainer import IdleTrainer
        except ImportError:
            self.skipTest("IdleTrainer not available")

        mock_learner = MagicMock()
        mock_psutil.cpu_percent.return_value = 5
        mock_psutil.virtual_memory.return_value = MagicMock(percent=30)

        with patch('mca_core.idle_trainer.generate_batch', return_value=[{"error": "generation failed"}]):
            trainer = IdleTrainer(mock_learner, output_dir=".")
            trainer.start()
            time.sleep(0.5)
            trainer.stop()

            mock_learner.learn_pattern.assert_not_called()


if __name__ == '__main__':
    unittest.main()

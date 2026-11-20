import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from control.arm import CommError
from control.fixed_runner import FixedRunner, VerifiedGraspFailure
from control.fixed_sort import TargetRejected, select_target
from dashboard.server import serve, render_page
from dashboard.store import EventStore
from scripts.run_dashboard import load_history
from shared.event_sink import EventSink
from shared.schemas import DetectResult, SortEvent, Reason


TARGET = DetectResult('other', 300, 400, .9, 1)


def selected(*args, **kwargs):
    return TARGET, [dict(TARGET.__dict__)] * 5


class Arm:
    def __init__(self, failures=0):
        self.calls = []
        self.failures = failures
    def grasp(self, target):
        self.calls.append('grasp')
        if self.failures:
            self.failures -= 1
            raise VerifiedGraspFailure('verified empty gripper')
        return True
    def go_safe(self):
        self.calls.append('safe')
    def _move(self, *args):
        self.calls.append('return')


class RecoveryTests(unittest.TestCase):
    def test_command_completion_is_not_physical_success(self):
        result = FixedRunner(None, Arm(), selector=selected).run_once()
        self.assertEqual(result['event']['reason'], Reason.COMMAND_COMPLETE)
        self.assertFalse(result['event']['ok'])
        self.assertIsNone(result['physical_success_confirmed'])

    def test_one_verified_failure_retries_then_completes(self):
        arm = Arm(1)
        result = FixedRunner(None, arm, selector=selected).run_once()
        self.assertEqual(arm.calls, ['grasp', 'grasp', 'return'])
        self.assertEqual(result['attempts'], 2)

    def test_two_verified_failures_return_safe_and_next_target_can_run(self):
        arm = Arm(2)
        runner = FixedRunner(None, arm, selector=selected)
        result = runner.run_once()
        self.assertEqual(result['event']['reason'], Reason.GRASP_FAIL)
        self.assertEqual(arm.calls, ['grasp', 'grasp', 'safe'])
        self.assertFalse(runner.halted)
        self.assertTrue(runner.run_once()['command_sequence_completed'])

    def test_communication_error_stops_all_subsequent_motion(self):
        arm = Arm()
        def fail(target):
            arm.calls.append('failed_write')
            raise CommError('I2C failed')
        arm.grasp = fail
        runner = FixedRunner(None, arm, selector=selected)
        result = runner.run_once()
        self.assertEqual(result['event']['reason'], Reason.COMM_ERROR)
        with self.assertRaises(CommError):
            runner.run_once()
        self.assertEqual(arm.calls, ['failed_write'])

    def test_rejection_skips_without_motion_and_can_continue(self):
        arm = Arm()
        def reject(*args, **kwargs):
            raise TargetRejected('low confidence')
        runner = FixedRunner(None, arm, selector=reject)
        result = runner.run_once()
        self.assertEqual(result['event']['reason'], Reason.TARGET_REJECTED)
        self.assertEqual(arm.calls, [])
        runner.selector = selected
        self.assertTrue(runner.run_once()['command_sequence_completed'])

    def test_no_target_has_a_bounded_observation_window(self):
        class Clock:
            now = 0
            def __call__(self):
                return self.now
            def sleep(self, duration):
                self.now += duration
        clock = Clock()
        class Detector:
            def detect(self):
                return None
        with self.assertRaises(TargetRejected) as caught:
            select_target(Detector(), timeout_sec=.2, clock=clock, sleep=clock.sleep)
        self.assertEqual(caught.exception.reason, Reason.TIMEOUT_NO_TARGET)
        self.assertLessEqual(clock.now, .2)

    def test_interruption_never_sends_return_motion(self):
        arm = Arm()
        arm.grasp = lambda target: (_ for _ in ()).throw(KeyboardInterrupt())
        result = FixedRunner(None, arm, selector=selected).run_once()
        self.assertEqual(result['event']['reason'], Reason.INTERRUPTED)
        self.assertEqual(arm.calls, [])


class EventDeliveryTests(unittest.TestCase):
    def start_server(self, store):
        server = serve('127.0.0.1', 0, store=store, data_source='mock')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, 'http://127.0.0.1:' + str(server.server_address[1])

    def test_offline_event_is_replayed_once_and_survives_server_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = EventStore(log_path=str(root/'server.jsonl'))
            server, url = self.start_server(store)
            sink = EventSink(root/'producer', url)
            event = SortEvent('hardware-run-1', 1000, 'other', 4, False, 100, Reason.COMMAND_COMPLETE)
            with patch('shared.event_sink.urlopen', side_effect=OSError('offline')):
                sink.publish(event)
            self.assertEqual(store.summary()['total'], 0)
            self.assertTrue(sink.queue.read_text().strip())
            self.assertEqual(EventSink(root/'producer', url).flush(), 1)
            self.assertEqual(store.summary()['unverified'], 1)
            self.assertEqual(store.summary()['failed'], 0)
            # Server received the first delivery but acknowledgement was lost.
            sink.publish(event)
            self.assertEqual(store.summary()['total'], 1)
            self.assertEqual(len((root/'server.jsonl').read_text().splitlines()), 1)
            restored = EventStore(log_path=str(root/'server.jsonl'))
            load_history(root/'server.jsonl', restored)
            self.assertEqual(restored.summary()['total'], 1)
            self.assertIn('待核验', render_page('/events', restored))

    def test_conflicting_duplicate_id_is_rejected(self):
        store = EventStore()
        event = SortEvent('same', 1000, 'other', 4, False, 100, Reason.COMMAND_COMPLETE)
        store.add(event)
        payload = event.to_dict()
        payload['cost_ms'] = 500
        with self.assertRaises(ValueError):
            store.add(payload)

    def test_mixed_outcomes_have_consistent_statistics(self):
        store = EventStore()
        for number, reason in enumerate([Reason.OK, Reason.COMMAND_COMPLETE, Reason.GRASP_FAIL]):
            store.add(SortEvent(str(number), 1000, 'other', 4, reason == Reason.OK, 1, reason))
        self.assertEqual(store.summary(), {'total':3, 'success':1, 'failed':1, 'unverified':1})
        self.assertNotIn(Reason.COMMAND_COMPLETE, store.fallback_counts())

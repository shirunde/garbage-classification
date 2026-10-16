import unittest

from control.arm import CommError, MockArm
from control.sorter import SmileScript, Sorter
from control.voice import PAUSE, START, STOP, parse_command
from shared.schemas import DetectResult, Reason
from vision.detector import MockDetector, ScriptedColorTracker


def detect(cls="recyclable", conf=0.9, expr="none"):
    return DetectResult(cls, 100, 120, conf, 1, expr)


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        self.now += 50
        return self.now


def run_sorter(script, grasp=None, tracked=None, smiles=None, link_down_after=None):
    clock = Clock()
    arm = MockArm(grasp, link_down_after=link_down_after)
    sorter = Sorter(
        detector=MockDetector(script),
        arm=arm,
        color_tracker=ScriptedColorTracker(tracked),
        face=SmileScript(smiles or []),
        clock=clock,
    )
    return sorter.run_once(), sorter, arm


class SorterTest(unittest.TestCase):
    def test_success_without_smile_does_not_wave(self):
        event, _sorter, arm = run_sorter([detect()], smiles=[False])
        self.assertTrue(event.ok)
        self.assertEqual(event.reason, Reason.OK)
        self.assertEqual(event.bin_id, 1)
        self.assertEqual(event.cls, "recyclable")
        self.assertEqual(arm.waves, 0)
        self.assertGreaterEqual(event.cost_ms, 0)

    def test_success_with_smile_waves(self):
        event, _sorter, arm = run_sorter([detect(conf=0.88)], smiles=[True])
        self.assertTrue(event.ok)
        self.assertEqual(arm.waves, 1)

    def test_gray_zone_smile_confirms_drop(self):
        event, _sorter, arm = run_sorter([detect("hazardous", 0.6)], smiles=[True, False])
        self.assertTrue(event.ok)
        self.assertEqual(event.bin_id, 2)
        self.assertEqual(arm.attempts, 1)

    def test_gray_zone_timeout_skips(self):
        event, _sorter, arm = run_sorter([detect(conf=0.7)], smiles=[False])
        self.assertFalse(event.ok)
        self.assertEqual(event.reason, Reason.NEED_CONFIRM_TIMEOUT)
        self.assertEqual(event.bin_id, 0)
        self.assertEqual(arm.attempts, 0)

    def test_low_conf_color_track_recovers(self):
        event, _sorter, _arm = run_sorter(
            [detect("kitchen", 0.2)],
            tracked=detect("kitchen", 0.8),
            smiles=[False],
        )
        self.assertTrue(event.ok)
        self.assertEqual(event.bin_id, 3)

    def test_low_conf_color_track_fail(self):
        event, _sorter, arm = run_sorter([detect("other", 0.1)], tracked=None)
        self.assertEqual(event.reason, Reason.LOW_CONF_COLOR_TRACK)
        self.assertEqual(arm.attempts, 0)

    def test_grasp_retries_once_then_succeeds(self):
        event, _sorter, arm = run_sorter([detect()], grasp=[False, True], smiles=[False])
        self.assertTrue(event.ok)
        self.assertEqual(arm.attempts, 2)
        self.assertEqual(arm.safe_moves, 0)

    def test_grasp_fail_returns_safe(self):
        event, _sorter, arm = run_sorter([detect()], grasp=[False, False], smiles=[False])
        self.assertEqual(event.reason, Reason.GRASP_FAIL)
        self.assertEqual(arm.safe_moves, 1)

    def test_no_target(self):
        event, _sorter, _arm = run_sorter([None])
        self.assertEqual(event.reason, Reason.TIMEOUT_NO_TARGET)
        self.assertEqual(event.cls, "")

    def test_comm_error_stops_next_motion(self):
        event, sorter, _arm = run_sorter([detect()], link_down_after=0)
        self.assertEqual(event.reason, Reason.COMM_ERROR)
        self.assertTrue(sorter.halted)
        with self.assertRaises(CommError):
            sorter.run_once()

    def test_voice_commands(self):
        self.assertEqual(parse_command(START), "start")
        self.assertEqual(parse_command(PAUSE), "pause")
        self.assertEqual(parse_command(STOP), "stop")
        self.assertIsNone(parse_command("你好"))


if __name__ == "__main__":
    unittest.main()

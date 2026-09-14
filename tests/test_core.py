import time
import unittest

from core import HoldToTalk, ReleaseResult


class HoldToTalkTests(unittest.TestCase):
    def test_short_press_is_tap(self) -> None:
        calls: list[str] = []
        controller = HoldToTalk(0.1, lambda: calls.append("start"), lambda: calls.append("stop"))

        self.assertTrue(controller.press())
        self.assertIs(controller.release(), ReleaseResult.TAP)
        self.assertEqual(calls, [])

    def test_hold_starts_and_stops_recording(self) -> None:
        calls: list[str] = []
        controller = HoldToTalk(0.01, lambda: calls.append("start"), lambda: calls.append("stop"))

        controller.press()
        time.sleep(0.04)

        self.assertIs(controller.release(), ReleaseResult.RECORDING_FINISHED)
        self.assertEqual(calls, ["start", "stop"])


if __name__ == "__main__":
    unittest.main()

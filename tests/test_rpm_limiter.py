import unittest
from unittest import mock

from gemini_translator.core.worker_helpers import rpm_limiter as rpm_limiter_module
from gemini_translator.core.worker_helpers.rpm_limiter import (
    RPM_RECOVERY_SECONDS,
    RPMLimiter,
)


class RPMLimiterWaitTests(unittest.TestCase):
    def test_seconds_until_next_allowed_zero_before_first_request(self):
        limiter = RPMLimiter(60)  # interval = 1.0s
        self.assertEqual(limiter.seconds_until_next_allowed(), 0.0)

    def test_seconds_until_next_allowed_after_consuming_slot(self):
        limiter = RPMLimiter(60)  # interval = 1.0s
        self.assertTrue(limiter.can_proceed())  # consumes the slot at "now"
        remaining = limiter.seconds_until_next_allowed()
        self.assertGreater(remaining, 0.0)
        self.assertLessEqual(remaining, 1.0)
        # Still blocked right after consuming, so a positive wait is meaningful.
        self.assertFalse(limiter.can_proceed())

    def test_no_limit_always_zero(self):
        limiter = RPMLimiter(0)  # disabled limiter
        self.assertEqual(limiter.seconds_until_next_allowed(), 0.0)


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now


class RPMLimiterRecoveryTests(unittest.TestCase):
    """После 429 RPM снижается, а в спокойное время возвращается по шагу.

    Раньше снижение было навсегда: за долгую сессию ключ съезжал 5→4→3→2→1 и
    дальше работал впятеро медленнее, хотя лимит сервиса давно отпустил.
    """

    def setUp(self):
        self.clock = _Clock()
        patcher = mock.patch.object(rpm_limiter_module, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_lowered_rpm_returns_one_step_after_a_quiet_period(self):
        limiter = RPMLimiter(5)
        limiter.decrease_rpm(25)
        limiter.decrease_rpm(25)
        self.assertEqual(limiter.get_rpm(), 3)

        self.clock.now += RPM_RECOVERY_SECONDS - 1
        self.assertEqual(limiter.get_rpm(), 3)
        self.clock.now += 1
        self.assertEqual(limiter.get_rpm(), 4)
        self.clock.now += RPM_RECOVERY_SECONDS
        self.assertEqual(limiter.get_rpm(), 5)
        self.clock.now += 10 * RPM_RECOVERY_SECONDS
        self.assertEqual(limiter.get_rpm(), 5)

    def test_a_new_limit_hit_restarts_the_quiet_period(self):
        limiter = RPMLimiter(5)
        limiter.decrease_rpm(25)
        self.clock.now += RPM_RECOVERY_SECONDS - 1
        limiter.decrease_rpm(25)

        self.clock.now += RPM_RECOVERY_SECONDS - 1
        self.assertEqual(limiter.get_rpm(), 3)
        self.clock.now += 1
        self.assertEqual(limiter.get_rpm(), 4)

    def test_a_recovered_rpm_shortens_the_wait_between_requests(self):
        limiter = RPMLimiter(5)  # 12 s between requests
        limiter.decrease_rpm(25)  # 4 RPM: 15 s
        self.clock.now += RPM_RECOVERY_SECONDS
        self.assertTrue(limiter.can_proceed())

        self.assertEqual(limiter.seconds_until_next_allowed(), 12.0)


if __name__ == "__main__":
    unittest.main()

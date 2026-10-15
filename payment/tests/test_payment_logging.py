import os
import subprocess
import sys
import unittest


class PaymentLoggingTest(unittest.TestCase):
    def test_logging_works_without_app_configuration(self):
        code = (
            "from shared.logger import logger; "
            "logger.debug('payment booking_id=7 outcome=started'); "
            "logger.info('payment booking_id=7 outcome=succeeded')"
        )
        for level in (None, "DEBUG"):
            with self.subTest(level=level):
                env = dict(os.environ)
                env.pop("LOG_LEVEL", None)
                if level:
                    env["LOG_LEVEL"] = level
                result = subprocess.run(
                    [sys.executable, "-c", code], env=env,
                    capture_output=True, text=True, check=True)
                expected = "INFO payment booking_id=7 outcome=succeeded\n"
                if level == "DEBUG":
                    expected = "DEBUG payment booking_id=7 outcome=started\n" + expected
                self.assertEqual(result.stderr, expected)


if __name__ == "__main__":
    unittest.main()

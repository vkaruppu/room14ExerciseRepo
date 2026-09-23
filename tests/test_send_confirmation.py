import unittest

from support.mock_backend import _record_action, send_confirmation


class SendConfirmationTest(unittest.TestCase):
    def test_send_confirmation_returns_a_full_record(self):
        _record_action("K7PQ2M", "hold_seat", "HOLD-TEST")
        result = send_confirmation(
            "K7PQ2M",
            "Your rebooking has been held and is waiting for confirmation.",
        )

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["pnr"], "K7PQ2M")
        self.assertEqual(result["message"], "Your rebooking has been held and is waiting for confirmation.")
        self.assertIn("sent_at", result)
        self.assertIn("message_id", result)

    def test_send_confirmation_requires_a_prior_action_for_the_pnr(self):
        result = send_confirmation(
            "ZZZZZZ",
            "This message should not be sent without a real booking action.",
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "no_recent_action")


if __name__ == "__main__":
    unittest.main()

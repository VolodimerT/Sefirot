"""Verify the ChatGPT-Supabase research queue never places bets."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import chat_queue

class QueueTests(unittest.TestCase):
    def test_empty_queue_is_noop(self):
        with patch.object(chat_queue,"request",return_value={"job":None}) as api:
            self.assertFalse(chat_queue.process_one())
            self.assertEqual(api.call_count,1)
    def test_status_executes_canonical_core_and_acks(self):
        job={"job":{"id":"6e7dbf7b-8276-438f-a712-922005e19ddb","kind":"status","request":{}}}
        replies=iter([job,{"completed":True}])
        with patch.object(chat_queue,"request",side_effect=lambda q:next(replies)) as api:
            with patch.object(chat_queue,"execute",return_value={"stage":"READY"}) as engine:
                self.assertTrue(chat_queue.process_one())
                engine.assert_called_once_with("status",{})
                self.assertEqual(api.call_args.args[0]["success"],True)
                self.assertEqual(api.call_args.args[0]["response"]["stage"],"READY")
    def test_rejects_unknown_betting_action(self):
        job={"job":{"id":"6e7dbf7b-8276-438f-a712-922005e19ddb","kind":"place_bet","request":{}}}
        replies=iter([job,{"completed":True}])
        with patch.object(chat_queue,"request",side_effect=lambda q:next(replies)) as api:
            with patch.object(chat_queue,"execute") as engine:
                self.assertTrue(chat_queue.process_one())
                engine.assert_not_called()
                self.assertFalse(api.call_args.args[0]["success"])
if __name__=="__main__":unittest.main()

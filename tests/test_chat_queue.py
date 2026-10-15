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

    def test_reclaimed_probe_does_not_repeat_provider_fetch(self):
        for attempt in (2,3):
            with self.subTest(attempt=attempt):
                job={'job':{'id':'6e7dbf7b-8276-438f-a712-922005e19ddb',
                            'kind':'sports_probe','request':{'queries':[]},'attempt':attempt}}
                with patch.object(chat_queue,'request',side_effect=[job,{'completed':True}]) as api, \
                     patch.object(chat_queue,'execute') as engine:
                    self.assertTrue(chat_queue.process_one())
                    engine.assert_not_called()
                    self.assertEqual(api.call_args.args[0]['error'],'PROVIDER_FETCH_RETRY_REQUIRES_REVIEW')
                    self.assertFalse(api.call_args.args[0]['success'])

    def test_probe_requires_an_integer_first_attempt(self):
        for attempt in (None,True,0,1.0,'1',4):
            with self.subTest(attempt=attempt):
                job={'job':{'id':'6e7dbf7b-8276-438f-a712-922005e19ddb',
                            'kind':'sports_probe','request':{'queries':[]},'attempt':attempt}}
                with patch.object(chat_queue,'request',side_effect=[job,{'completed':True}]) as api, \
                     patch.object(chat_queue,'execute') as engine:
                    self.assertTrue(chat_queue.process_one())
                    engine.assert_not_called()
                    self.assertFalse(api.call_args.args[0]['success'])

    def test_probe_first_attempt_executes_and_preserves_receipt(self):
        job={'job':{'id':'6e7dbf7b-8276-438f-a712-922005e19ddb',
                    'kind':'sports_probe','request':{'queries':[]},'attempt':1}}
        original={'queries':[{'receipt':{'payload_hash':'a'*64}}]}
        with patch.object(chat_queue,'request',side_effect=[job,{'completed':True}]) as api, \
             patch.object(chat_queue,'execute',return_value=original) as engine:
            self.assertTrue(chat_queue.process_one())
            engine.assert_called_once_with('sports_probe',{'queries':[]})
            self.assertEqual(api.call_args.args[0]['response'],original)
            self.assertTrue(api.call_args.args[0]['success'])

    def test_lost_completion_does_not_trigger_another_fetch_on_reclaim(self):
        item={'id':'6e7dbf7b-8276-438f-a712-922005e19ddb','kind':'sports_probe',
              'request':{'queries':[]},'attempt':1}
        replies=[{'job':item},OSError('SYNTHETIC_UNAVAILABLE'),
                 {'job':{**item,'attempt':2}},{'completed':True}]
        with patch.object(chat_queue,'request',side_effect=replies) as api, \
             patch.object(chat_queue,'execute',return_value={'queries':[]}) as engine:
            with self.assertRaises(OSError):chat_queue.process_one()
            self.assertTrue(chat_queue.process_one())
            self.assertEqual(engine.call_count,1)
            self.assertEqual(api.call_args.args[0]['error'],'PROVIDER_FETCH_RETRY_REQUIRES_REVIEW')
if __name__=="__main__":unittest.main()

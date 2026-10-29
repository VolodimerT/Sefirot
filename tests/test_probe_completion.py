"""Bounded replay of an existing receipt; never replay provider execution."""
import copy
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import chat_queue
import chat_store

UID='00000000-0000-0000-0000-000000000099'
JOB={'job':{'id':UID,'kind':'sports_probe','attempt':1,'request':{'queries':[]}}}
ACK={'completed':True,'id':UID,'attempts':1}

class ProbeCompletionTests(unittest.TestCase):
    def test_transient_completion_replay_saves_same_receipt_without_refetch(self):
        result={'queries':[{'receipt':{'payload_hash':'a'*64}}]};original=copy.deepcopy(result)
        error=chat_store.DurableStoreError('SEFIROT_DURABLE_STORE_UNAVAILABLE',retryable=True)
        with patch.object(chat_queue,'request',side_effect=[JOB,error,ACK]) as store, \
             patch.object(chat_queue,'execute',return_value=result) as execute:
            self.assertTrue(chat_queue.process_one())
        execute.assert_called_once()
        a,b=[c.args[0] for c in store.call_args_list[1:]]
        self.assertEqual(a,b);self.assertEqual(a['action'],'probe_complete')
        self.assertEqual(a['attempt'],1);self.assertEqual(a['response'],original)
        self.assertEqual(result,original)

    def test_second_transport_failure_stops_after_two_completion_attempts(self):
        error=chat_store.DurableStoreError('SEFIROT_DURABLE_STORE_UNAVAILABLE',retryable=True)
        with patch.object(chat_queue,'request',side_effect=[JOB,error,error]) as store, \
             patch.object(chat_queue,'execute',return_value={}) as execute:
            with self.assertRaises(chat_store.DurableStoreError):chat_queue.process_one()
        self.assertEqual(store.call_count,3);execute.assert_called_once()

    def test_permanent_failure_never_retries_or_falls_back_to_legacy(self):
        error=chat_store.DurableStoreError('SEFIROT_DURABLE_STORE_UNAVAILABLE')
        with patch.object(chat_queue,'request',side_effect=[JOB,error]) as store, \
             patch.object(chat_queue,'execute',return_value={}):
            with self.assertRaises(chat_store.DurableStoreError):chat_queue.process_one()
        self.assertEqual(store.call_count,2)
        self.assertEqual(store.call_args.args[0]['action'],'probe_complete')

    def test_acknowledgement_must_bind_id_and_integer_attempt(self):
        for ack in ({'completed':True},{**ACK,'id':'foreign'},
                    {**ACK,'attempts':True},{**ACK,'attempts':2},{**ACK,'completed':False}):
            with self.subTest(ack=ack),patch.object(chat_queue,'request',side_effect=[JOB,ack]) as store, \
                 patch.object(chat_queue,'execute',return_value={}):
                with self.assertRaisesRegex(RuntimeError,'CHAT_PROBE_NOT_ACKNOWLEDGED'):
                    chat_queue.process_one()
                self.assertEqual(store.call_count,2)

    def test_claim_failure_is_never_retried(self):
        error=chat_store.DurableStoreError('SEFIROT_DURABLE_STORE_UNAVAILABLE',retryable=True)
        with patch.object(chat_queue,'request',side_effect=error) as store,patch.object(chat_queue,'execute') as execute:
            with self.assertRaises(chat_store.DurableStoreError):chat_queue.process_one()
        self.assertEqual(store.call_count,1);execute.assert_not_called()

    def test_http_error_classification_is_sanitized_and_closes_body(self):
        for code in (301,401,403,409,422,429,500,502,503,504):
            stream=BytesIO(b'PRIVATE_SENTINEL')
            error=HTTPError('https://private.invalid/?token=PRIVATE_SENTINEL',code,'PRIVATE_SENTINEL',{},stream)
            with self.subTest(code=code),patch.object(chat_store,'config',return_value=('https://synthetic.test','x'*48)), \
                 patch.object(chat_store,'build_opener') as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaises(chat_store.DurableStoreError) as caught:chat_store.request({'action':'pull'})
                self.assertEqual(caught.exception.retryable,code in (500,502,503,504))
                self.assertEqual(str(caught.exception),'SEFIROT_DURABLE_STORE_UNAVAILABLE')
                self.assertTrue(stream.closed)

    def test_lost_connection_is_retryable_but_unknown_exception_is_not(self):
        for error,retryable in ((URLError('PRIVATE_SENTINEL'),True),(TimeoutError(),True),(ValueError('PRIVATE_SENTINEL'),False)):
            with self.subTest(error=type(error)),patch.object(chat_store,'config',return_value=('https://synthetic.test','x'*48)), \
                 patch.object(chat_store,'build_opener') as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaises(chat_store.DurableStoreError) as caught:chat_store.request({'action':'pull'})
                self.assertEqual(caught.exception.retryable,retryable)
                self.assertNotIn('PRIVATE_SENTINEL',str(caught.exception))

if __name__=='__main__':unittest.main()

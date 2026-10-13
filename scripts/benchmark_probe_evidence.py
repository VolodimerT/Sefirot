"""Offline two-script comparison; mocked getter, no credentials or ledger IO."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from sefirot.contracts import digest
import chat_sports_probe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-probe',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('baseline_probe',args.baseline_probe)
    before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
    after=chat_sports_probe
    data={'get':'fixtures','parameters':{'id':123},'errors':{},'results':1,
          'paging':{'current':1,'total':1},'response':[{
          'fixture':{'id':123,'date':'2026-10-13T19:00:00Z','status':{'short':'NS'}},
          'league':{'id':7,'name':'SYNTHETIC','season':2026},
          'teams':{'home':{'id':1,'name':'A'},'away':{'id':2,'name':'B'}},
          'score':{'fulltime':{'home':None,'away':None}}}]}
    packet={'data':data,'receipt':{'provider':'API_FOOTBALL_V3','provider_host':'v3.football.api-sports.io',
            'endpoint':'/fixtures','parameters':{'id':123},'received_at':'2026-10-13T10:00:00Z',
            'payload_hash':digest(data),'http_status':200,'transport':'SUPABASE_GATEWAY'}}
    for module in (before,after):
        module.get_sports=lambda *a,**kw:copy.deepcopy(packet)
        module.transport_status=lambda:{'transport':'SUPABASE_GATEWAY','credential_configured':False}
    request={'queries':[{'endpoint':'fixtures','params':{'id':123}}]*8}
    old=before.collect(request);new=after.collect(request)
    assert [q['rows'] for q in old['queries']]==[q['rows'] for q in new['queries']]
    assert all(after.verify_evidence(q)['status']=='CANONICAL_PACKET_ARCHIVED' for q in new['queries'])
    for _ in range(3):before.collect(request);after.collect(request)
    timings=[]
    for pair in range(31):
        row={}
        order=(('after',after),('before',before)) if pair%2 else (('before',before),('after',after))
        for label,module in order:
            started=perf_counter_ns()
            for _ in range(10):module.collect(request)
            row[label]=(perf_counter_ns()-started)/10/1e6
        timings.append(row)
    print(json.dumps({'synthetic':True,'provider_calls':0,'ledger_writes':0,'queries_per_job':8,
          'pairs':31,'same_compact_rows':True,'before_rehashable_packets':0,'after_rehashable_packets':8,
          'source_archive_bytes':new['source_archive_bytes'],
          'serialized_before_bytes':len(json.dumps(old).encode()),'serialized_after_bytes':len(json.dumps(new).encode()),
          'before_median_ms':median(x['before'] for x in timings),
          'after_median_ms':median(x['after'] for x in timings),
          'median_paired_delta_ms':median(x['after']-x['before'] for x in timings),
          'timing_scope':'8-query collector CPU only, mocked getter; not whole network/decision latency',
          'out_of_sample_validation':False,'monetary_permission':False,'measurements':timings},indent=2))


if __name__=='__main__':main()

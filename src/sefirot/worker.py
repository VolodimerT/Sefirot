"""Local file inbox automation; every job has an immutable receipt, no wager execution."""
import json
import sqlite3
from pathlib import Path
from .contracts import strict,text,digest


def process_inbox(service,directory):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True);output=[]
    for path in sorted(root.glob('*.json')):
        try:
            job=json.loads(path.read_text(encoding='utf-8'));strict(job,('id','type','payload'));text(job['id'],'job id')
            jid=job['id'];hashed=digest(job)
            try:prior=service.repo.get('jobs',jid)
            except ValueError:prior=None
            if prior:
                if prior['input_hash']!=hashed:raise ValueError('job id reused for changed input')
                output.append({'id':jid,'status':'ALREADY_PROCESSED'});continue
            kind=job['type'];data=job['payload'];at=service.now()
            if kind=='CAPTURE':
                strict(data,('sports','markets'),('calibrator_id','parent','reason'))
                result=service.capture(data['sports'],data['markets'],data.get('calibrator_id'),parent=data.get('parent'),reason=data.get('reason'))
            elif kind=='DECIDE':
                strict(data,('prediction_id','quotes','recheck','portfolio'))
                result=service.decide(data['prediction_id'],data['quotes'],data['recheck'],data['portfolio'],at)
            elif kind=='RESULT':result=service.result(data)
            elif kind=='CLOSING':
                strict(data,('match_id','quote'));result=service.closing(data['match_id'],data['quote'])
            else:raise ValueError('inbox permits only CAPTURE, DECIDE, RESULT, CLOSING')
            receipt={'id':jid,'at':at,'input_hash':hashed,'status':'DONE','result':result}
            with service.repo.transaction():service.repo.insert('jobs',jid,receipt,at=at);service.repo.log('INBOX_JOB',at,{'id':jid,'input_hash':hashed})
            output.append({'id':jid,'status':'DONE','result_id':result.get('id')})
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
            output.append({'file':path.name,'status':'ERROR','decision':'PASS','error':str(exc)})
    return output

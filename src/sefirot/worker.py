"""Local file inbox: atomic actions and receipts, no network or wager execution."""
import json
import sqlite3
from pathlib import Path
from .contracts import strict,text,digest
from .markets import DEFAULT_POOL


def _summary(receipt, status):
    result=receipt['result']
    row={'id':receipt['id'],'status':status,'result_id':result.get('id')}
    if 'decision_card' in result:row['decision_card']=result['decision_card']
    elif 'sports' in result and 'sealed_at' in result:
        row.update(prediction_id=result['id'],match=result['sports']['match'],
                   stage='FORECAST_SEALED',synthetic=result['synthetic'])
    return row


def _prediction_reference(service, data):
    refs=[key for key in ('prediction_id','prediction_job_id') if key in data]
    if len(refs)!=1:raise ValueError('exactly one prediction_id or prediction_job_id required')
    text(data[refs[0]],refs[0])
    if refs[0]=='prediction_id':return data['prediction_id']
    receipt=service.repo.get('jobs',data['prediction_job_id']);result=receipt['result']
    if (receipt.get('status')!='DONE' or 'sealed_at' not in result or 'sports' not in result
            or receipt.get('job_type','CAPTURE')!='CAPTURE'):
        raise ValueError('prediction_job_id must reference a completed CAPTURE job')
    return result['id']


def process_inbox(service,directory):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True);output=[]
    try:
        if not service.repo.verify():raise ValueError('journal integrity failed')
    except (ValueError,KeyError,TypeError,sqlite3.Error):
        return [{'status':'ERROR','decision':'PASS','error':'journal integrity failed'}]
    # File order is intentional: seal the forecast before opening quote jobs.
    for path in sorted(root.glob('*.json')):
        try:
            job=json.loads(path.read_text(encoding='utf-8'));strict(job,('id','type','payload'));text(job['id'],'job id')
            jid=job['id'];hashed=digest(job)
            # Service operations nest through savepoints; this outer transaction
            # commits the action, job receipt and audit together.
            with service.repo.transaction():
                try:prior=service.repo.get('jobs',jid)
                except ValueError:prior=None
                if prior:
                    if prior['input_hash']!=hashed:raise ValueError('job id reused for changed input')
                    output.append(_summary(prior,'ALREADY_PROCESSED'));continue
                kind=job['type'];data=job['payload'];at=service.now()
                if kind=='CAPTURE':
                    strict(data,('sports',),('markets','calibrator_id','parent','reason','goal_model'))
                    result=service.capture(data['sports'],data.get('markets',DEFAULT_POOL),data.get('calibrator_id'),
                        parent=data.get('parent'),reason=data.get('reason'),goal_model=data.get('goal_model'))
                elif kind=='DECIDE':
                    strict(data,('quotes','recheck','portfolio'),('prediction_id','prediction_job_id'))
                    result=service.decide(_prediction_reference(service,data),data['quotes'],data['recheck'],data['portfolio'],at)
                elif kind=='RESULT':result=service.result(data)
                elif kind=='CLOSING':
                    strict(data,('match_id','quote'));result=service.closing(data['match_id'],data['quote'])
                else:raise ValueError('inbox permits only CAPTURE, DECIDE, RESULT, CLOSING')
                receipt={'id':jid,'at':at,'input_hash':hashed,'job_type':kind,'status':'DONE','result':result}
                service.repo.insert('jobs',jid,receipt,at=at)
                service.repo.record_log('jobs',jid,at,receipt)
                service.repo.log('INBOX_JOB',at,{'id':jid,'input_hash':hashed})
            output.append(_summary(receipt,'DONE'))
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
            output.append({'file':path.name,'status':'ERROR','decision':'PASS','error':str(exc)})
    return output


def render_inbox(rows):
    from .decision_card import render_card
    if not rows:
        return ('Очередь пуста. Поместите задания 01-capture.json и затем 02-decide.json в эту папку.\n'
                'После результата добавьте RESULT. Формат и пример: docs/OFFLINE_WORKFLOW.md.\n'
                'Разрешения на ставку нет.')
    lines=[]
    for row in rows:
        name=row.get('id',row.get('file','Журнал'))
        label={'DONE':'обработано','ALREADY_PROCESSED':'уже обработано','ERROR':'ошибка'}[row['status']]
        lines.append(f"{name}: {label}")
        if row['status']=='ERROR':lines.append('  Пропуск: '+row['error'])
        elif 'decision_card' in row:lines.append(render_card(row['decision_card']))
        elif 'match' in row:
            m=row['match'];lines.append(f"  {m['home']} — {m['away']}: прогноз зафиксирован до цены.")
            lines.append('  Прогноз: '+row['prediction_id'])
            if row['synthetic']:lines.append('  Синтетический пример; денежного допуска нет.')
    lines.append('Обработка задания не означает разрешение ставки; исполнителя ставок нет.')
    return '\n'.join(lines)

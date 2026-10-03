"""Transactional application service: capture → decide → settle → audit → monitor."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from math import sqrt
from .contracts import Policy,REASONS,SEPHIROT,digest,time,iso,number,integer,text,strict
from .engine import prepare,decide,code_hash,model_code_hash
from .repository import Repository
from .markets import market_of,settle,validate_quote
from .evaluation import log_loss
from .evidence import profile_of
from .probability import fit_calibrator,worst_case_probabilities
from .feedback import brier,summary,context_key,competence,ratings,compare_versions


class Service:
    def __init__(self,repository,policy=None,clock=None):
        self.repo=repository;self.policy=policy or Policy();self.clock=clock or (lambda:datetime.now(timezone.utc))

    def now(self): return self.clock().astimezone(timezone.utc).isoformat()

    def _time(self,at):
        stamp=time(at)
        if stamp>time(self.now()):raise ValueError('operation timestamp is in the future')
        return stamp

    def capture(self,sports,markets,calibrator_id=None,*,parent=None,reason=None,replay=False,goal_model=None):
        now=self.now();self._time(sports['as_of'])
        if not replay and time(now)>=time(sports['match']['kickoff']):raise ValueError('capture is no longer prematch')
        if calibrator_id is None:
            routes=sorted(self.repo.all('model_routes',now),key=lambda r:(time(r['at']),r['id']))
            if routes:
                active=self.repo.get('model_versions',routes[-1]['model_id'])
                if active['code_hash']!=code_hash():raise ValueError('active model requires its archived code version')
                routed=active.get('goal_model')
                if goal_model is not None and digest(goal_model)!=digest(routed):raise ValueError('explicit goal model differs from active route')
                goal_model=routed
                calibrator_id=active['calibrator_id']
        calibrator=self.repo.get('calibrators',calibrator_id) if calibrator_id else None
        prepared=prepare(sports,markets,self.policy,calibrator,goal_model)
        revision=0
        if parent:
            prior=self.repo.get('predictions',parent)
            if reason not in REASONS:raise ValueError('manual change requires an allowed reason')
            if prior['sports']['match']!=sports['match']:raise ValueError('revision fixture differs')
            if digest(prior['market_pool'])!=digest(markets):raise ValueError('market pool is fixed across revisions')
            if digest(prior['sports'])==digest(sports):raise ValueError('unchanged sports snapshot cannot trigger recalculation')
            if time(sports['as_of'])<=time(prior['as_of']):raise ValueError('revision must advance knowledge time')
            revision=prior['revision']+1
            if revision>self.policy.max_revisions:raise ValueError('recalculation budget exhausted: PASS')
        prepared.update({'sealed_at':now,'captured_prematch':not replay and time(now)<time(sports['match']['kickoff']),
                         'reconstructed':bool(replay),'revision':revision,'parent':parent,'override_reason':reason})
        prepared.pop('id');prepared['id']=digest(prepared)
        model_id=digest([prepared['code_hash'],prepared['policy_hash'],calibrator_id,goal_model['hash'] if goal_model else None])
        prepared['model_id']=model_id
        # id binds model_id too, preventing ambiguity between calibrated versions.
        prepared.pop('id');prepared['id']=digest(prepared)
        match=sports['match']
        with self.repo.transaction():
            prior_fixtures=[p for p in self.repo.all('predictions') if p['sports']['match']['id']==match['id']]
            if any(digest(p['market_pool'])!=digest(markets) for p in prior_fixtures):raise ValueError('cannot shop additional markets for an existing match')
            if not parent:
                same=[p for p in prior_fixtures if p['model_id']==model_id and p['parent'] is None and digest(p['sports'])==digest(sports) and p['reconstructed']==bool(replay)]
                if same:return same[0]
                if any(p['model_id']==model_id and p['id']!=prepared['id'] for p in prior_fixtures):raise ValueError('existing model/fixture requires an explicit revision')
            for team in (match['home'],match['away']):self.repo.insert('teams',team,{'name':team})
            self.repo.insert('matches',match['id'],match,home=match['home'],away=match['away'],kickoff=iso(match['kickoff']),league=match['league'])
            try:self.repo.get('model_versions',model_id)
            except ValueError:self.repo.insert('model_versions',model_id,{'id':model_id,'code_hash':prepared['code_hash'],'model_hash':prepared['model_hash'],'policy_hash':prepared['policy_hash'],'calibrator_id':calibrator_id,'goal_model':goal_model,'registered_at':now},at=now)
            for m in prepared['market_pool']:
                market=market_of(m);self.repo.insert('markets',market.key,m)
            if self.repo.insert('predictions',prepared['id'],prepared,match_id=match['id'],model_id=model_id,at=now):
                self.repo.record_log('predictions',prepared['id'],now,prepared)
            if parent:
                override={'before':parent,'after':prepared['id'],'reason':reason,'at':now}
                self.repo.insert('overrides',digest(override),override,at=now);self.repo.log('OVERRIDE',now,override)
        return prepared

    def reserve(self,match_ids,role,at):
        self._time(at)
        if role not in ('CALIBRATION','HOLDOUT','MONITOR'):raise ValueError('invalid dataset role')
        with self.repo.transaction():
            for mid in match_ids:
                text(mid,'match id')
                if any(p['sports']['match']['id']==mid for p in self.repo.all('predictions')):raise ValueError('split must be reserved before prediction')
                row={'match_id':mid,'role':role,'at':at}
                self.repo.insert('split_assignments',mid,row,at=iso(at));self.repo.log('SPLIT_RESERVED',at,row)

    def _records(self,as_of=None):return self.repo.all('calibration_history',as_of)

    def context(self,prediction,at):
        all_records=self._records(at);health={};releases={};role_ratings={};post=self.repo.all('postmortems',at)
        events=self.repo.all('health_events',at)
        validations=self.repo.all('validation_runs',at)
        for c in prediction['candidates']:
            m=prediction['sports']['match'];profile=profile_of(m);key=context_key(m['league'],c['key'],prediction['scenario']['type'],prediction['model_id'],profile)
            selected=[r for r in all_records if r['context_key']==key]
            relevant=sorted([e for e in events if e['context_key']==key],key=lambda e:(time(e['at']),e['id']))
            previous=relevant[-1]['state'] if relevant else 'UNKNOWN'
            # A successful explicit recovery permits monitoring anew; old failed windows
            # remain auditable but don't immediately refreeze the corrected version.
            if relevant and relevant[-1].get('recovery_after'):
                selected=[r for r in selected if time(r['received_at'])>time(relevant[-1]['recovery_after'])]
            severe=len({p['match_id'] for p in post if p['critical_error'] and p['context_key']==key and (not relevant or not relevant[-1].get('recovery_after') or time(p['at'])>time(relevant[-1]['recovery_after']))})
            health[c['key']]=competence(selected,self.policy,previous,severe)
            role_ratings[c['key']]=ratings(post,m['league'],c['market']['kind'],prediction['scenario']['type'],self.policy,prediction['model_id'],profile)
            candidates=[v for v in validations if v['model_id']==prediction['model_id'] and v['context_key']==key and v['passed'] and not v['synthetic']]
            releases[c['key']]=max(candidates,key=lambda v:time(v['at'])) if candidates else None
        approvals=[a for a in self.repo.all('policy_approvals',at) if a['policy_hash']==prediction['policy_hash'] and a['code_hash']==prediction['code_hash']]
        exposures=[]
        results={r['match_id']:r for r in self.repo.all('results',at)}
        for b in self.repo.all('bets',at):
            exposures.append({**b,**({'settled_at':results[b['match_id']]['received_at']} if b['match_id'] in results else {})})
        return {'journal_ok':self.repo.verify(),'health':health,'releases':releases,'sephirot_ratings':role_ratings,'policy_approved':bool(approvals),
                'captured_prematch':prediction['captured_prematch'],'exposures':exposures}

    def decide(self,prediction_id,quotes,recheck,portfolio,at):
        self._time(at);p=self.repo.get('predictions',prediction_id)
        if time(self.now())>=time(p['sports']['match']['kickoff']):raise ValueError('cannot record a new prematch decision after kickoff; use archived replay or retrospective audit')
        if time(at)<time(p['sealed_at']):raise ValueError('decision precedes stored probability seal')
        strict(portfolio,('bankroll','peak'));number(portfolio['bankroll'],'bankroll',0);number(portfolio['peak'],'peak',portfolio['bankroll'])
        with self.repo.transaction():
            context=self.context(p,at)
            out=decide(p,quotes,recheck,at,context,portfolio,self.policy);out['id']=digest(out)
            for q in quotes:
                market=market_of(q['market']);self.repo.insert('markets',market.key,q['market'])
                qid=digest([prediction_id,q]);self.repo.insert('odds_snapshots',qid,q,prediction_id=prediction_id,market_id=market.key,at=iso(q['received_at']))
            if self.repo.insert('decisions',out['id'],out,prediction_id=prediction_id,at=iso(at)):
                self.repo.record_log('decisions',out['id'],at,out)
        return out

    def replay(self,decision_id):
        stored=self.repo.get('decisions',decision_id);p=self.repo.get('predictions',stored['prediction_id']);inputs=stored['inputs']
        # Replay the captured context, not today's better-known results or current bankroll.
        new=decide(p,inputs['quotes'],inputs['recheck'],stored['at'],inputs['context'],inputs['portfolio'],Policy(**p['policy']))
        new['id']=digest(new)
        return {'matches':new==stored,'id':decision_id,'replayed':new['id']}

    def result(self,result):
        strict(result,('match_id','status','home_goals','away_goals','finished_at','received_at','source'))
        match=self.repo.get('matches',result['match_id']);self._time(result['received_at']);text(result['source'],'result source')
        if result['status'] not in ('FINISHED','VOID'):raise ValueError('unsupported result status')
        if time(result['finished_at'])<=time(match['kickoff']) or time(result['received_at'])<time(result['finished_at']):raise ValueError('result chronology')
        if result['status']=='FINISHED':
            integer(result['home_goals'],'home score',0,50);integer(result['away_goals'],'away score',0,50)
        elif result['home_goals'] is not None or result['away_goals'] is not None:raise ValueError('VOID result has no score')
        at=result['received_at'];new_records=[]
        with self.repo.transaction():
            inserted=self.repo.insert('results',result['match_id'],result,at=iso(at))
            if not inserted:return {'idempotent':True,'records':0}
            self.repo.record_log('results',result['match_id'],at,result)
            predictions=[p for p in self.repo.all('predictions') if p['sports']['match']['id']==match['id']]
            # Latest prematch revision per model; all other sealed predictions stay stored.
            latest={}
            for p in predictions:
                key=p['model_id']
                if key not in latest or time(p['sealed_at'])>time(latest[key]['sealed_at']):latest[key]=p
            for p in latest.values():
                for c in p['candidates']:
                    if result['status']=='VOID':continue
                    market=market_of(c['market']);outcome=settle(market,result['home_goals'],result['away_goals'])
                    baseline=[(1-c['raw'][1])/2,c['raw'][1],(1-c['raw'][1])/2]
                    record={'prediction_id':p['id'],'match_id':match['id'],'model_id':p['model_id'],'market':market.key,'kind':market.kind,
                            'model_hash':p.get('model_hash'),
                            'league':match['league'],'competition_profile':profile_of(match),'scenario':p['scenario']['type'],'context_key':context_key(match['league'],market.key,p['scenario']['type'],p['model_id'],profile_of(match)),
                            'raw_win':c['raw'][0],'raw_probabilities':c['raw'],'probabilities':c['base'],'low':c['low'],'high':c['high'],
                            'prediction_error':[v-int(i==('WIN','PUSH','LOSS').index(outcome)) for i,v in enumerate(c['base'])],
                            'outcome':outcome,'brier':brier(c['base'],outcome),'baseline_brier':brier(baseline,outcome),
                            'baseline_log_loss':log_loss(baseline,('WIN','PUSH','LOSS').index(outcome)),
                            'received_at':at,'synthetic':p['synthetic'],'captured_prematch':p['captured_prematch'],
                            'goal_model_hash':p.get('goal_model',{}).get('hash') if p.get('goal_model') else None,
                            'calibration_status':c['calibration'],'sealed_at':p['sealed_at'],'kickoff':match['kickoff'],
                            'calibrator_id':p['calibrator']['hash'] if p['calibrator'] else None}
                    rid=digest(record);self.repo.insert('calibration_history',rid,record,prediction_id=p['id'],market_id=market.key,at=iso(at));new_records.append(record)
            for decision in self.repo.all('decisions',at):
                if decision['match_id']!=match['id']:continue
                audit={'decision_id':decision['id'],'match_id':match['id'],'at':at,'quality':'UNDETERMINED',
                       'competition_profile':profile_of(match),'model_id':decision.get('inputs',{}).get('context',{}).get('model_id') or self.repo.get('predictions',decision['prediction_id'])['model_id'],
                       'causes':['UNKNOWN'],'decision':decision['decision'],'class':decision['class'],'pre_match_blocks':decision['limiting_factors'],
                       'outcomes':{c['key']:('VOID' if result['status']=='VOID' else settle(market_of(c['market']),result['home_goals'],result['away_goals'])) for c in decision['candidates']},
                       'candidates':[{'market':c['key'],'market_contract':c['market'],'probabilities':c['base'],'raw_probabilities':c['raw'],
                                      'low':c['low'],'high':c['high'],'odds':c.get('odds'),'fair_odds':c.get('fair_odds'),
                                      'base_ev':c.get('ev'),'stress_ev_min':c.get('stress_ev_min'),'stress_ev_max':c.get('stress_ev_max'),'stress_grade':c.get('stress_grade'),
                                      'reasons':[i['code'] for i in c['issues']],'quality':'UNDETERMINED',
                                      'outcome':'VOID' if result['status']=='VOID' else settle(market_of(c['market']),result['home_goals'],result['away_goals']),
                                      'brier':None if result['status']=='VOID' else brier(c['base'],settle(market_of(c['market']),result['home_goals'],result['away_goals']))}
                                     for c in decision['candidates']],
                       'factual_premises':self.repo.get('predictions',decision['prediction_id'])['scenario']['premises'],
                       'premise_assessment':'UNKNOWN_REQUIRES_EVIDENCE',
                       'note':'Result and decision quality are separate; causal attribution needs evidence.'}
                aid=digest(audit);self.repo.insert('postmatch_reports',aid,audit,decision_id=decision['id'],at=iso(at));self.repo.log('AUTOMATIC_POSTMATCH_AUDIT',at,audit)
            for key in sorted({r['context_key'] for r in new_records}):self._monitor(key,at)
            self.repo.log('FEEDBACK',at,{'match_id':match['id'],'metrics':len(new_records)})
        return {'idempotent':False,'records':len(new_records)}

    def _monitor(self,key,at):
        records=[r for r in self._records(at) if r['context_key']==key]
        prior=sorted([h for h in self.repo.all('health_events',at) if h['context_key']==key],key=lambda e:(time(e['at']),e['id']))
        previous=prior[-1]['state'] if prior else 'UNKNOWN'
        severe=len({p['match_id'] for p in self.repo.all('postmortems',at) if p['critical_error'] and p['context_key']==key})
        recovered=next((h.get('recovery_after') for h in reversed(prior) if h.get('recovery_after')),None)
        if recovered:
            records=[r for r in records if time(r['received_at'])>time(recovered)]
            severe=len({p['match_id'] for p in self.repo.all('postmortems',at) if p['critical_error'] and p['context_key']==key and time(p['at'])>time(recovered)})
        report=competence(records,self.policy,previous,severe)
        event={'context_key':key,'at':at,**report,**({'recovery_after':recovered} if recovered else {})};event['id']=digest(event)
        self.repo.insert('health_events',event['id'],event,at=iso(at));self.repo.log('HEALTH',at,event)

    def closing(self,match_id,quote):
        match=self.repo.get('matches',match_id);self._time(quote['received_at'])
        if quote['phase']!='CLOSE':raise ValueError('closing phase required')
        market=validate_quote(quote,match['kickoff'],quote['received_at'],quote['received_at'])
        payload={**quote,'match_id':match_id}
        with self.repo.transaction():
            self.repo.insert('markets',market.key,quote['market'])
            qid=digest(payload)
            if self.repo.insert('closing_odds',qid,payload,match_id=match_id,market_id=market.key,at=iso(quote['received_at'])):self.repo.log('CLOSING',quote['received_at'],payload)
        return {'id':qid}

    def calibrate(self,at):
        self._time(at);assign={a['match_id']:a for a in self.repo.all('split_assignments',at)}
        records=[r for r in self._records(at) if assign.get(r['match_id'],{}).get('role')=='CALIBRATION' and r['calibrator_id'] is None]
        # One frozen base model at a time: mixing different code policies is forbidden.
        if len({r['model_id'] for r in records})!=1:raise ValueError('calibration requires one base model')
        base=self.repo.get('model_versions',records[0]['model_id'])
        if base.get('model_hash')!=model_code_hash() or base['policy_hash']!=self.policy.fingerprint:
            raise ValueError('calibration requires matching probability model and policy; old records cannot be relabelled')
        artifact=fit_calibrator(records,model_code_hash(),self.policy.fingerprint,at)
        with self.repo.transaction():
            if self.repo.insert('calibrators',artifact['hash'],artifact,at=iso(at)):self.repo.record_log('calibrators',artifact['hash'],at,artifact)
        return artifact

    def validate(self,model_id,at):
        self._time(at);model=self.repo.get('model_versions',model_id)
        if model['code_hash']!=code_hash() or model['policy_hash']!=self.policy.fingerprint:raise ValueError('validation requires matching archived code and policy')
        if not model['calibrator_id']:raise ValueError('frozen calibrator required for holdout')
        artifact=self.repo.get('calibrators',model['calibrator_id']);assign={a['match_id']:a for a in self.repo.all('split_assignments',at)}
        records=[r for r in self._records(at) if r['model_id']==model_id and assign.get(r['match_id'],{}).get('role')=='HOLDOUT']
        if any(r['match_id'] in artifact['fit_ids'] or time(artifact['fit_at'])>=time(r['sealed_at']) or time(assign[r['match_id']]['at'])>time(r['sealed_at']) for r in records):raise ValueError('holdout leakage')
        output=[]
        for key in sorted({r['context_key'] for r in records}):
            subset=sorted([r for r in records if r['context_key']==key],key=lambda r:(time(r['kickoff']),r['match_id']))
            s=summary(subset);n=len(subset);delta=[r['brier']-r['baseline_brier'] for r in subset];mean=sum(delta)/n
            se=sqrt(sum((d-mean)**2 for d in delta)/(n-1)/n) if n>1 else 1.
            halves=[subset[:n//2],subset[n//2:]]
            repeatable=all(rows and sum(r['brier']-r['baseline_brier'] for r in rows)<0 for rows in halves)
            reasons=[]
            if n<self.policy.min_holdout:reasons.append('HOLDOUT_TOO_SMALL')
            if mean+1.96*se>=0:reasons.append('NO_CONFIDENT_BASELINE_IMPROVEMENT')
            if not repeatable:reasons.append('PERIOD_STABILITY_FAILED')
            if max(s['calibration_error'],s['multiclass']['ece_macro'])>self.policy.max_calibration_error:reasons.append('CALIBRATION_ERROR_HIGH')
            if any('baseline_log_loss' not in r for r in subset):reasons.append('LOGLOSS_BASELINE_MISSING')
            elif s['multiclass']['log_loss']>=sum(r['baseline_log_loss'] for r in subset)/n:reasons.append('LOGLOSS_BASELINE_NOT_BEATEN')
            if any(r['calibration_status']!='CALIBRATED_BIN' for r in subset):reasons.append('UNCALIBRATED_BIN')
            if any(not r['captured_prematch'] for r in subset):reasons.append('RETROSPECTIVE_CAPTURE')
            synthetic=any(r['synthetic'] for r in subset) or artifact['synthetic']
            if synthetic:reasons.append('SYNTHETIC_NOT_PROOF')
            report={**s,'model_id':model_id,'context_key':key,'at':at,'passed':not reasons,'reasons':reasons,'synthetic':synthetic,
                    'ids':sorted({r['match_id'] for r in subset}),'policy_hash':model['policy_hash'],'code_hash':model['code_hash'],'mean_delta':mean,'delta_interval':[mean-1.96*se,mean+1.96*se]}
            if self.policy.stress_mode=='GRADED':
                from .feedback import validate_stress_classes
                by_prediction={(r['prediction_id'],r['market']):r for r in subset}
                latest={}
                for d in self.repo.all('decisions',at):
                    p=self.repo.get('predictions',d['prediction_id'])
                    if p['model_id']!=model_id:continue
                    for c in d['candidates']:
                        record=by_prediction.get((p['id'],c['key']))
                        if record is None or c.get('ev') is None or c['ev']<self.policy.min_ev:continue
                        pair=(record['match_id'],record['market'])
                        order=(time(d['at']),d['id'])
                        if pair not in latest or order>latest[pair][0]:latest[pair]=(order,d,c,p,record)
                class_rows=[]
                # Ignore only the gates that holdout itself is intended to establish.
                validation_only={'CONTEXT_UNKNOWN','SEPHIRA_HISTORY_INSUFFICIENT','HOLDOUT_UNVALIDATED',
                                 'GRADED_DEATH_TEST_UNVALIDATED','POLICY_NOT_APPROVED','NO_ADMISSIBLE_MAIN_MARKET'}
                for _,d,c,p,r in latest.values():
                    blockers=[i['code'] for i in p['issues']+d['issues']+c['issues'] if i['severity']=='BLOCK' and i['code'] not in validation_only]
                    class_rows.append({**r,'stress_class':c['stress_grade']['class'],'ev':c['ev'],
                                       'ev_low':c['ev_low'],'sports_gates_passed':not blockers,
                                       'unit_return':c['odds']-1 if r['outcome']=='WIN' else 0. if r['outcome']=='PUSH' else -1.})
                report['stress_classes']=validate_stress_classes(class_rows,self.policy)
            report['id']=digest(report);output.append(report)
        with self.repo.transaction():
            for report in output:
                if self.repo.insert('validation_runs',report['id'],report,at=iso(at)):self.repo.record_log('validation_runs',report['id'],at,report)
        return output

    def approve_policy(self,operator,statement,at):
        self._time(at);text(operator,'operator')
        if statement!='I_APPROVE_THIS_EXPERIMENTAL_POLICY':raise ValueError('explicit policy acknowledgement required')
        payload={'operator':operator,'statement':statement,'at':at,'policy_hash':self.policy.fingerprint,'code_hash':code_hash(),'policy':asdict(self.policy)}
        with self.repo.transaction():
            self.repo.insert('policy_approvals',digest(payload),payload,at=iso(at));self.repo.log('POLICY_APPROVAL',at,payload)
        return payload

    def postmortem(self,decision_id,review,at):
        self._time(at);d=self.repo.get('decisions',decision_id);p=self.repo.get('predictions',d['prediction_id']);r=self.repo.get('results',d['match_id'])
        if time(at)<time(r['received_at']):raise ValueError('postmortem before known result')
        strict(review,('market','decision_quality','causes','roles','notes'),('category','category_evidence','premise_observations'))
        if review['decision_quality'] not in ('GOOD','WEAK','ERROR','UNDETERMINED'):raise ValueError('invalid decision quality')
        if not set(review['causes'])<=set(('PROBABILITY','SCENARIO','SOURCE','LATE_INFORMATION','MARKET','RANDOMNESS','UNKNOWN')):raise ValueError('invalid error cause')
        categories=('MODEL_MISS','THRESHOLD_MISS','PRICE_MISS','FACT_MISS','STRUCTURAL_BREAK','GOOD_PASS_BAD_RESULT','BAD_PASS_FALSE_NEGATIVE','NARRATIVE_SUBSTITUTION','MARKET_DIVERGENCE','CORRELATION_EXPOSURE','UNKNOWN')
        category=review.get('category','UNKNOWN')
        if category not in categories:raise ValueError('invalid postmortem category')
        citations=review.get('category_evidence',[])
        if not isinstance(citations,list) or any(not isinstance(ref,str) or not ref.strip() for ref in citations):raise ValueError('category evidence must contain references')
        if category!='UNKNOWN' and not citations:raise ValueError('causal category needs evidence beyond the outcome')
        observations=review.get('premise_observations',[])
        if not isinstance(observations,list) or len({o.get('premise_id') for o in observations if isinstance(o,dict)})!=len(observations):raise ValueError('distinct premise observations required')
        for observation in observations:
            strict(observation,('premise_id','status','evidence'))
            if observation['premise_id'] not in p['scenario']['premises'] or observation['status'] not in ('HELD','FAILED','UNKNOWN'):raise ValueError('invalid premise observation')
            if observation['status']!='UNKNOWN' and not observation['evidence']:raise ValueError('premise assessment needs evidence')
            if not isinstance(observation['evidence'],list) or any(not isinstance(ref,str) or not ref.strip() for ref in observation['evidence']):raise ValueError('premise evidence must contain references')
        for role,obs in review['roles'].items():
            if role not in SEPHIROT:raise ValueError('unknown sephira')
            strict(obs,('correct','severe','evidence'))
            if obs['correct'] is not None and type(obs['correct']) is not bool or type(obs['severe']) is not bool:raise ValueError('role observation type')
            if obs['severe'] and obs['correct'] is not False:raise ValueError('severe error must be explicitly incorrect')
            if (obs['correct'] is not None or obs['severe']) and not obs['evidence']:raise ValueError('attribution needs evidence')
        candidate=next((c for c in p['candidates'] if c['key']==review['market']),None)
        if not candidate:raise ValueError('market absent in prediction')
        m=p['sports']['match'];market=market_of(candidate['market'])
        outcome='VOID' if r['status']=='VOID' else settle(market,r['home_goals'],r['away_goals'])
        payload={**review,'decision_id':decision_id,'at':at,'match_id':m['id'],'outcome':outcome,
                 'league':m['league'],'competition_profile':profile_of(m),'kind':market.kind,'scenario':p['scenario']['type'],'model_id':p['model_id'],'category':category,
                 'critical_error':any(o['severe'] for o in review['roles'].values()),
                 'context_key':context_key(m['league'],market.key,p['scenario']['type'],p['model_id'],profile_of(m))}
        with self.repo.transaction():
            # One attribution per decision-market; corrections require a new explicit review protocol.
            rid=digest([decision_id,market.key])
            if self.repo.insert('postmortems',rid,payload,decision_id=decision_id,at=iso(at)):
                self.repo.log('POSTMORTEM',at,payload);self._monitor(payload['context_key'],at)
        return payload

    def recover(self,context,fix,validation_id,at):
        self._time(at);text(fix,'fix evidence')
        v=self.repo.get('validation_runs',validation_id)
        events=sorted([h for h in self.repo.all('health_events',at) if h['context_key']==context],key=lambda h:time(h['at']))
        if not events or events[-1]['state']!='FROZEN':raise ValueError('context is not frozen')
        frozen=events[-1]
        if not v['passed'] or v['context_key']!=context or time(v['at'])<=time(frozen['at']):raise ValueError('fresh passed validation required')
        rows=[r for r in self._records(at) if r['match_id'] in v['ids'] and r['context_key']==context]
        if not rows or any(time(r['sealed_at'])<=time(frozen['at']) for r in rows):raise ValueError('recovery reuses pre-freeze data')
        event={'context_key':context,'state':'WORKING','reason':'FIX_AND_FRESH_VALIDATION','fix':fix,'validation_id':validation_id,'at':at,'recovery_after':frozen['at']};event['id']=digest(event)
        with self.repo.transaction():self.repo.insert('health_events',event['id'],event,at=iso(at));self.repo.log('RECOVERY',at,event)
        return event

    def report(self,at=None):
        records=self._records(at);grouped={}
        for r in records:grouped.setdefault((r['league'],r['market'],r['scenario'],r['model_id'],r.get('competition_profile','UNKNOWN')),[]).append(r)
        performance=[{'league':k[0],'market':k[1],'scenario':k[2],'model_id':k[3],'competition_profile':k[4],**summary(v)} for k,v in sorted(grouped.items())]
        closes=self.repo.all('closing_odds',at);clv=[]
        for d in self.repo.all('decisions',at):
            for c in d['candidates']:
                if not c.get('quote'):continue
                q=c['quote'];matching=[x for x in closes if x['match_id']==d['match_id'] and market_of(x['market']).key==c['key'] and x['bookmaker']==q['bookmaker'] and time(x['observed_at'])>=time(q['observed_at'])]
                if matching:
                    close=max(matching,key=lambda x:time(x['observed_at']))
                    clv.append({'decision_id':d['id'],'market':c['key'],'entry':q['odds'],'closing':close['odds'],'clv':q['odds']/close['odds']-1,'kind':'DECISION_QUOTE_NOT_EXECUTION'})
        for bet in self.repo.all('bets',at):
            matching=[x for x in closes if x['match_id']==bet['match_id'] and market_of(x['market']).key==bet['market'] and x['bookmaker']==bet['bookmaker'] and time(x['observed_at'])>=time(bet['at'])]
            if matching:
                close=max(matching,key=lambda x:time(x['observed_at']))
                clv.append({'bet_id':bet['id'],'decision_id':bet['decision_id'],'market':bet['market'],'entry':bet['odds'],
                            'closing':close['odds'],'clv':bet['odds']/close['odds']-1,'kind':'RECORDED_EXECUTION',
                            'origin':bet['origin'],'policy_flags':bet['flags']})
        results={r['match_id']:r for r in self.repo.all('results',at)};latest={};observations=[]
        for d in self.repo.all('decisions',at):
            if d['match_id'] not in results or results[d['match_id']]['status']!='FINISHED':continue
            prediction=self.repo.get('predictions',d['prediction_id']);key=(d['match_id'],prediction['model_id'])
            if key not in latest or (time(d['at']),d['id'])>(time(latest[key][0]['at']),latest[key][0]['id']):latest[key]=(d,prediction)
        for d,p in latest.values():
            result=results[d['match_id']]
            for c in d['candidates']:
                if c.get('ev') is None:continue
                outcome=settle(market_of(c['market']),result['home_goals'],result['away_goals'])
                observations.append({'match_id':d['match_id'],'model_id':p['model_id'],'competition_profile':profile_of(p['sports']['match']),
                                     'kind':c['market']['kind'],'stress_class':c.get('stress_grade',{}).get('class','UNCLASSIFIED_LEGACY'),'ev':c['ev'],
                                     'outcome':outcome,'decision':d['decision'],
                                     'unit_return':c['odds']-1 if outcome=='WIN' else 0. if outcome=='PUSH' else -1.})
        cohorts=[]
        keys={(r['competition_profile'],r['kind'],r['model_id'],r['stress_class']) for r in observations}
        for profile,kind,model_id,risk in sorted(keys):
            rows=[r for r in observations if (r['competition_profile'],r['kind'],r['model_id'],r['stress_class'])==(profile,kind,model_id,risk)]
            positives=[r for r in rows if r['decision']=='PASS' and r['ev']>=self.policy.min_ev]
            cohorts.append({'competition_profile':profile,'kind':kind,'model_id':model_id,'stress_class':risk,'n':len(rows),
                            'expected_ev':sum(r['ev'] for r in rows)/len(rows),'realized_unit_return':sum(r['unit_return'] for r in rows)/len(rows),
                            'positive_ev_pass_n':len(positives),'positive_ev_pass_win_rate':sum(r['outcome']=='WIN' for r in positives)/len(positives) if positives else None,
                            'kind_of_record':'LATEST_DECISION_QUOTE_DIAGNOSTIC; not execution P/L or a causal false-negative rate'})
        return {'integrity':self.repo.verify(),'performance':performance,'clv':clv,'health':self.repo.all('health_events',at),'validation':self.repo.all('validation_runs',at),
                'risk_cohorts':cohorts,
                'postmatch_audits':self.settlement_audits(at),'ratings':{str(k):ratings(self.repo.all('postmortems',at),k[0],market_of({'kind':k[1].split(':')[0],'side':k[1].split(':')[1],**({'line':float(k[1].split(':')[2])} if len(k[1].split(':'))>2 else {})}).kind,k[2],self.policy,k[3],k[4]) for k in grouped}}

    def settlement_audits(self,at=None):
        """Current read view over immutable result/quote/execution/review records.

        Late closing and causal evidence enrich the view without rewriting the
        automatic postmatch snapshot or pretending a quote was an execution.
        """
        results={r['match_id']:r for r in self.repo.all('results',at)}
        closes=self.repo.all('closing_odds',at);bets=self.repo.all('bets',at)
        reviews=self.repo.all('postmortems',at);output=[]
        for saved in self.repo.all('postmatch_reports',at):
            d=self.repo.get('decisions',saved['decision_id']);p=self.repo.get('predictions',d['prediction_id'])
            result=results[d['match_id']];candidates=[]
            def closing(market,book,observed):
                matching=[q for q in closes if q['match_id']==d['match_id'] and market_of(q['market']).key==market
                          and q['bookmaker']==book and time(q['observed_at'])>=time(observed)]
                return max(matching,key=lambda q:(time(q['observed_at']),time(q['received_at']),digest(q))) if matching else None
            for stored in saved['candidates']:
                c=next(c for c in d['candidates'] if c['key']==stored['market'])
                q=c.get('quote');close=closing(c['key'],q['bookmaker'],q['observed_at']) if q else None
                review=next((r for r in reviews if r['decision_id']==d['id'] and r['market']==c['key']),None)
                observations={o['premise_id']:o for o in (review or {}).get('premise_observations',[])}
                premises=[]
                for fact in p['witness']['resolved'].values():
                    premises.append({**fact,'assessment':observations.get(fact['id'],{'status':'UNKNOWN','evidence':[]})})
                executions=[]
                for b in bets:
                    if b['decision_id']!=d['id'] or b['market']!=c['key']:continue
                    bc=closing(c['key'],b['bookmaker'],b['at'])
                    outcome=stored['outcome']
                    payout=b['stake']*b['odds'] if outcome=='WIN' else b['stake'] if outcome in ('PUSH','VOID') else 0.
                    executions.append({'id':b['id'],'entry_odds':b['odds'],'bookmaker':b['bookmaker'],'stake':b['stake'],
                                       'origin':b['origin'],'flags':b['flags'],'outcome':outcome,'payout':payout,'pnl':payout-b['stake'],
                                       'closing_odds':bc['odds'] if bc else None,'clv':b['odds']/bc['odds']-1 if bc else None})
                candidates.append({**stored,'decision_odds':c.get('odds'),
                                   'entry_odds':executions[0]['entry_odds'] if len(executions)==1 else None,
                                   'closing_odds':close['odds'] if close else None,
                                   'quote_clv':q['odds']/close['odds']-1 if q and close else None,
                                   'executions':executions,'factual_premises':premises,
                                   'premise_assessment':'REVIEWED' if observations else 'UNKNOWN_REQUIRES_EVIDENCE',
                                   'postmortem_category':(review or {}).get('category','UNKNOWN'),
                                   'quality':(review or {}).get('decision_quality','UNDETERMINED'),
                                   'category_evidence':(review or {}).get('category_evidence',[])})
            output.append({**saved,'result':result,'candidates':candidates,'view':'IMMUTABLE_RECORD_JOIN'})
        return output

    def execution(self,decision_id,entry,at):
        """Record a human execution; never place a bet or convert PASS into permission."""
        self._time(at);d=self.repo.get('decisions',decision_id);p=self.repo.get('predictions',d['prediction_id'])
        strict(entry,('id','market','odds','stake','bookmaker','origin'))
        text(entry['id'],'execution id');text(entry['bookmaker'],'bookmaker')
        number(entry['odds'],'odds',1.00000001);number(entry['stake'],'stake',.01)
        if entry['origin'] not in ('SYSTEM_RECOMMENDATION','EXTERNAL'):raise ValueError('execution origin')
        candidate=next((c for c in d['candidates'] if c['key']==entry['market']),None)
        if not candidate or not candidate.get('quote'):raise ValueError('execution market missing')
        if time(at)<time(d['at']) or time(at)>=time(p['sports']['match']['kickoff']):raise ValueError('prematch execution window')
        flags=[]
        if time(self.now())>=time(p['sports']['match']['kickoff']):flags.append('RETROSPECTIVE_EXECUTION_RECORD')
        if d['decision']!='BET':flags.append('EXECUTED_AGAINST_PASS')
        if entry['market']!=d['selected_market']:flags.append('DIFFERENT_MARKET')
        if entry['odds']<candidate['odds']:flags.append('WORSE_PRICE_RECHECK_REQUIRED')
        if entry['bookmaker']!=candidate['quote']['bookmaker']:flags.append('BOOKMAKER_CHANGED')
        if entry['stake']>d['risk']['stake']:flags.append('STAKE_EXCEEDS_LIMIT')
        if (time(at)-time(candidate['quote']['observed_at'])).total_seconds()>self.policy.quote_max_age_seconds:flags.append('STALE_EXECUTION_PRICE')
        from .risk import groups
        payload={**entry,'decision_id':decision_id,'match_id':d['match_id'],'at':at,'flags':flags,
                 'groups':groups(p['sports']['match'],p['model_version'],p['scenario']['type'],p['scenario']['novelty'])}
        with self.repo.transaction():
            try: recorded=self.repo.get('bets',entry['id'])
            except ValueError: recorded=None
            if recorded is not None:
                if any(recorded[k]!=entry[k] for k in entry) or recorded['decision_id']!=decision_id or recorded['at']!=at:raise ValueError('immutable execution conflict')
                return recorded
            # Check portfolio inside the same write transaction as exposure recording.
            existing=self.repo.all('bets',at)
            if any(b['match_id']==d['match_id'] and b['id']!=entry['id'] for b in existing):flags.append('DUPLICATE_EVENT_EXPOSURE')
            if entry['origin']=='SYSTEM_RECOMMENDATION':
                if p['code_hash']!=code_hash() or p['policy_hash']!=self.policy.fingerprint:
                    flags.append('EXECUTION_VERSION_MISMATCH')
                fresh=self.context(p,at);state=fresh['health'].get(entry['market'],{}).get('state','UNKNOWN')
                if not fresh['journal_ok'] or state!='WORKING':flags.append('ADMISSION_STATE_CHANGED')
                if self.policy.stress_mode=='GRADED':
                    release=fresh['releases'].get(entry['market']) or {}
                    if not release.get('stress_classes',{}).get(candidate['stress_grade']['class'],{}).get('passed'):flags.append('STRESS_CLASS_RELEASE_CHANGED')
                from .risk import size_risk
                bounds=candidate.get('admission_low',candidate['low'])
                upper=candidate.get('admission_high',candidate['high'])
                adverse=worst_case_probabilities(bounds,upper,entry['odds'])
                quality=min(.5 if d['conditions'] else 1.,candidate.get('stake_multiplier',1.))
                remaining=size_risk(win=adverse[0],push=adverse[1],odds=entry['odds'],bankroll=d['inputs']['portfolio']['bankroll'],peak=d['inputs']['portfolio']['peak'],quality=quality,exposures=fresh['exposures'],match=p['sports']['match'],model=p['model_version'],scenario=p['scenario']['type'],factors=p['scenario']['novelty'],at=at,policy=self.policy)
                if entry['stake']>remaining['stake']:flags.append('PORTFOLIO_LIMIT_CHANGED')
            if entry['origin']=='SYSTEM_RECOMMENDATION' and flags:raise ValueError('execution failed current permission: '+','.join(flags))
            if self.repo.insert('bets',entry['id'],payload,decision_id=decision_id,at=iso(at)):self.repo.record_log('bets',entry['id'],at,payload)
        return payload

    def accounting(self,at=None):
        results={r['match_id']:r for r in self.repo.all('results',at)};rows=[]
        for b in self.repo.all('bets',at):
            result=results.get(b['match_id'])
            if not result:continue
            p=self.repo.get('decisions',b['decision_id']);c=next(c for c in p['candidates'] if c['key']==b['market'])
            outcome='VOID' if result['status']=='VOID' else settle(market_of(c['market']),result['home_goals'],result['away_goals'])
            payout=b['stake']*b['odds'] if outcome=='WIN' else b['stake'] if outcome in ('PUSH','VOID') else 0.
            rows.append({'bet_id':b['id'],'outcome':outcome,'stake':b['stake'],'payout':payout,'pnl':payout-b['stake'],'policy_flags':b['flags']})
        total=sum(r['stake'] for r in rows);pnl=sum(r['pnl'] for r in rows)
        return {'settled':rows,'turnover':total,'pnl':pnl,'roi':pnl/total if total else None}

    def activate(self,model_id,at,reason='VALIDATED_PROMOTION'):
        self._time(at);model=self.repo.get('model_versions',model_id)
        if model['code_hash']!=code_hash() or model['policy_hash']!=self.policy.fingerprint:raise ValueError('install matching archived code and policy before activation')
        passed=[v for v in self.repo.all('validation_runs',at) if v['model_id']==model_id and v['passed'] and not v['synthetic']]
        if not passed:raise ValueError('model has no certified holdout context')
        event={'model_id':model_id,'at':at,'reason':reason,'validation_ids':[v['id'] for v in passed]};event['id']=digest(event)
        with self.repo.transaction():self.repo.insert('model_routes',event['id'],event,at=iso(at));self.repo.log('MODEL_ROUTE',at,event)
        return event

    def compare_and_rollback(self,old_model,new_model,at):
        self._time(at);rows=self._records(at)
        report=compare_versions([r for r in rows if r['model_id']==old_model],[r for r in rows if r['model_id']==new_model],self.policy)
        routes=sorted(self.repo.all('model_routes',at),key=lambda r:(time(r['at']),r['id']))
        report['rolled_back']=False
        if report['recommendation']=='ROLLBACK' and routes and routes[-1]['model_id']==new_model:
            report['route']=self.activate(old_model,at,'PAIRED_HOLDOUT_ROLLBACK');report['rolled_back']=True
        with self.repo.transaction():self.repo.log('VERSION_COMPARISON',at,report)
        return report

"""Threshold, Witness and Scenario. Sports inputs never include prices."""
from __future__ import annotations
from .contracts import strict,text,time,iso,number,integer,finding,digest,PROFILES

REQUIRED = ('home_team','away_team','format','lineup','injuries','coach','rotation','tactics')


def profile_of(match):
    profile=match.get('competition_profile','UNKNOWN')
    if profile not in PROFILES: raise ValueError('invalid competition profile')
    return profile


def inspect(sports, policy):
    strict(sports,('match','as_of','sources','evidence','history'),('synthetic','thesis_links'))
    match=sports['match']
    strict(match,('id','home','away','league','kickoff','sport','format'),('competition_profile',))
    for k in match: text(match[k],k)
    if match['home']==match['away']: raise ValueError('distinct teams required')
    cutoff=time(sports['as_of']); kickoff=time(match['kickoff'])
    issues=[]
    if profile_of(match)=='UNKNOWN': issues.append(finding('competence','COMPETITION_PROFILE_UNKNOWN'))
    if cutoff>=kickoff: issues.append(finding('threshold','LIVE_FORBIDDEN'))
    if match['sport']!='football' or match['format']!='REGULATION_90': issues.append(finding('threshold','UNSUPPORTED_FORMAT'))
    sources={}
    for s in sports['sources']:
        strict(s,('id','independence_group','reliability','enabled'))
        text(s['id'],'source');text(s['independence_group'],'source group');number(s['reliability'],'source reliability',0,1)
        if type(s['enabled']) is not bool: raise ValueError('source enabled must be boolean')
        if s['id'] in sources: raise ValueError('duplicate source')
        sources[s['id']]=s
    evidence={}; buckets={}; usable=[]
    for e in sports['evidence']:
        strict(e,('id','key','value','kind','source_id','published_at','received_at','observed_at','critical','supports'),('supersedes',))
        text(e['id'],'evidence id');text(e['key'],'evidence key')
        if e['id'] in evidence: raise ValueError('duplicate evidence id')
        if e['key'] not in REQUIRED+('novelty','context','market_news','matchup_signal'): raise ValueError('unknown sports evidence key')
        if e['kind'] not in ('FACT','INFERENCE','ASSUMPTION') or type(e['critical']) is not bool or not isinstance(e['supports'],list): raise ValueError('invalid evidence type')
        if e['source_id'] not in sources: raise ValueError('unknown source')
        published,received,observed=(time(e[k]) for k in ('published_at','received_at','observed_at'))
        if observed>published or published>received or received>cutoff: raise ValueError('future or impossible evidence chronology')
        evidence[e['id']]=e
    for e in evidence.values():
        if any(ref not in evidence or ref==e['id'] for ref in e['supports']): raise ValueError('invalid supporting evidence')
        # Inferences may cite facts only; this eliminates support cycles.
        if any(evidence[ref]['kind']!='FACT' for ref in e['supports']): raise ValueError('support must cite FACT records')
        if any(time(evidence[ref]['received_at'])>time(e['received_at']) for ref in e['supports']):raise ValueError('inference cites information not yet received')
        src=sources[e['source_id']]
        bad=not src['enabled'] or src['reliability']<policy.min_source_reliability
        stale=(cutoff-time(e['observed_at'])).total_seconds()>policy.fact_max_age_minutes*60
        if e['key']=='matchup_signal':
            if e['kind']!='INFERENCE' or not isinstance(e['value'],dict) or e['value'].get('status') not in ('CONFLICT','CONSISTENT'):
                raise ValueError('matchup signal must be an explicit inference')
            if not e['supports'] or any(sources[evidence[ref]['source_id']]['reliability']<policy.min_source_reliability or not sources[evidence[ref]['source_id']]['enabled'] or (cutoff-time(evidence[ref]['observed_at'])).total_seconds()>policy.fact_max_age_minutes*60 for ref in e['supports']):
                issues.append(finding('witness','MATCHUP_SUPPORT_INSUFFICIENT','BLOCK',[e['id']]))
            elif not bad and not stale and e['value']['status']=='CONFLICT':
                issues.append(finding('opponent','MODEL_MATCHUP_CONFLICT','BLOCK',[e['id']],'RECALCULATE with independent sports data'))
        if e['critical'] and (bad or stale or e['kind']=='ASSUMPTION'):
            issues.append(finding('witness','CRITICAL_EVIDENCE_UNRELIABLE',( 'BLOCK'),[e['id']]))
        elif bad or stale:
            issues.append(finding('witness','WEAK_EVIDENCE','WARN',[e['id']]))
        if not bad and not stale and e['kind']=='FACT':
            buckets.setdefault(e['key'],[]).append(e);usable.append(e)
    resolved={}; conflicts=[]; eligible_fact_ids=[]
    for key, es in buckets.items():
        active=[]
        for e in es:
            superseded=False
            for newer in es:
                if e['id'] in newer.get('supersedes',[]):
                    if newer['source_id']!=e['source_id'] or time(newer['received_at'])<=time(e['received_at']): raise ValueError('invalid supersession')
                    superseded=True
            if not superseded: active.append(e)
        values={digest(e['value']) for e in active}
        if len(values)>1:
            conflict={'key':key,'evidence':[e['id'] for e in active],'resolution':'RECALCULATE_OR_PASS'}
            conflicts.append(conflict);issues.append(finding('opponent','UNRESOLVED_CONFLICT','BLOCK',conflict['evidence'],key))
        elif active:
            resolved[key]=max(active,key=lambda e:(time(e['received_at']),e['id']))
            eligible_fact_ids.extend(e['id'] for e in active)
    for key in REQUIRED:
        if key not in resolved: issues.append(finding('witness','MISSING_'+key.upper()))
    for key,target in (('home_team','home'),('away_team','away'),('format','format')):
        if key in resolved and resolved[key]['value']!=match[target]: issues.append(finding('witness','FIXTURE_IDENTITY_CONFLICT','BLOCK',[resolved[key]['id']]))
    if 'lineup' in resolved:
        lineup=resolved['lineup']['value']
        valid=isinstance(lineup,dict) and lineup.get('status')=='CONFIRMED'
        if valid:
            squads=[lineup.get(side,[]) for side in ('home','away')]
            valid=all(isinstance(squad,list) and len(squad)==11 and all(isinstance(player,str) and player for player in squad) and len(set(squad))==11 for squad in squads)
            if valid:valid=not (set(squads[0]) & set(squads[1]))
        if not valid:issues.append(finding('witness','LINEUP_NOT_CONFIRMED','BLOCK',[resolved['lineup']['id']]))
    if 'injuries' in resolved:
        injuries=resolved['injuries']['value']
        if not isinstance(injuries,dict) or any(not isinstance(injuries.get(side),list) for side in ('home','away')):
            issues.append(finding('witness','INJURY_REPORT_INCOMPLETE','BLOCK',[resolved['injuries']['id']]))
    if 'tactics' in resolved:
        tactical=resolved['tactics']['value']
        if not isinstance(tactical,dict) or tactical.get('fit')!='SUPPORTED' or not all(tactical.get(k) for k in ('home_style','away_style','key_factor')):
            issues.append(finding('scenario','TACTICAL_FIT_UNSUPPORTED','BLOCK',[resolved['tactics']['id']]))
    novelty=[]
    if 'novelty' in resolved:
        if not isinstance(resolved['novelty']['value'],list): raise ValueError('novelty must be a list')
        novelty.extend(resolved['novelty']['value'])
    for key in ('coach','rotation'):
        if key in resolved and resolved[key]['value'] not in ('STABLE','NORMAL'): novelty.append(key.upper()+'_CHANGE')
    groups=sorted({sources[e['source_id']]['independence_group'] for e in usable})
    scenario={'type':'BASELINE','description':'Historical goals with explicit low/base/high rate stress; no inferred tactical boost',
              'premises':[resolved[k]['id'] for k in sorted(resolved)],'critical_assumptions':[e['id'] for e in evidence.values() if e['critical'] and e['kind']=='ASSUMPTION'],
              'tactical_evidence':resolved.get('tactics',{}).get('id'),'novelty':novelty,
              'sports_digest':digest(sports)}
    return {'issues':issues,'resolved':resolved,'conflicts':conflicts,'sources':sources,'groups':groups,'novelty':novelty,'scenario':scenario,
            'eligible_fact_ids':sorted(eligible_fact_ids)}


def eligible_history(sports,policy):
    cutoff=time(sports['as_of']); seen=set(); rows=[]; excluded=[]
    for row in sports['history']:
        strict(row,('id','home','away','league','kickoff','finished_at','received_at','home_goals','away_goals','source_id'),('competition_profile',))
        for k in ('id','home','away','league','source_id'): text(row[k],k)
        if row['id'] in seen: raise ValueError('duplicate history id')
        seen.add(row['id'])
        if row['home']==row['away']: raise ValueError('history teams must differ')
        integer(row['home_goals'],'home goals',0,50);integer(row['away_goals'],'away goals',0,50)
        start,end,received=(time(row[k]) for k in ('kickoff','finished_at','received_at'))
        if start>=end or end>received: raise ValueError('history result chronology')
        if row['id']==sports['match']['id']: raise ValueError('target result must never be provided as history')
        if received>cutoff or start>=cutoff or (cutoff-start).days>policy.history_days or row['league']!=sports['match']['league'] or profile_of(row)!=profile_of(sports['match']):
            excluded.append(row['id']);continue
        sources={s['id']:s for s in sports['sources']}
        src=sources.get(row['source_id'])
        if src is None or not src['enabled'] or src['reliability']<policy.min_source_reliability:
            excluded.append(row['id']);continue
        rows.append(row)
    return sorted(rows,key=lambda r:(time(r['kickoff']),r['id'])),sorted(excluded)

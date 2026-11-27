"""Receipt-cut replay and daily sports dossier. Offline, never produces a seal."""
import argparse
from collections import defaultdict
from datetime import timedelta
import json
from pathlib import Path
from statistics import mean

from scripts.arena_shadow import ROLE_SPECS
from sefirot.contracts import Policy, time
from sefirot.probability import estimate
from sefirot.research import elo_predictions, frequency_predictions
from research.prediction_edge_v3 import models
from research.prediction_edge_v3.benchmark import outcome, project, proper_scores, reliability
from .archive_audit import verify_archive
from .tactical import profile

LEAGUES = (39, 140, 135, 78)


def snapshot(directory, manifest, at):
    keys = {r['raw_sha256'] for r in manifest['packets']
            if max(time(r['imported_at']), *(time(k['linked_at']) for k in r['links'])) <= time(at)}
    report = verify_archive(directory, manifest, as_of=at, only=keys)
    if report['packet_rejections'] or report['duplicate_raw_records']:
        raise ValueError('archive integrity failure')
    return report


def training(row, arrivals):
    source = row['fixture_sources'][0]
    return dict(id=str(row['fixture_id']), home=str(row['teams']['home']), away=str(row['teams']['away']),
                league=str(row['league']), season=row['season'], competition_profile='MEN',
                kickoff=row['kickoff'], finished_at=row['last_received_at'], received_at=arrivals[source],
                home_goals=row['goals']['home'], away_goals=row['goals']['away'],
                source_id=source, receipt_sha=source.split(':')[1], synthetic=False)


def rubric(target, tactical, n):
    venues = [s['evidence'] for s in tactical['venue_split'].values()]
    # Each readiness check is an observable prerequisite, never an outcome probability.
    checks = {'calendar within 24h': target['calendar_fresh'],
              'both venue histories observed': all(v['VENUE_FORM']['sample_n'] > 0 for v in venues),
              'both venue xG observed': all(v['CHANCE_QUALITY_XG']['sample_n'] for v in venues),
              'confirmed lineups': bool(target['lineups']), 'assigned referee': bool(target['referee'])}
    return {'football_intelligence': 100 * sum(bool(v) for v in checks.values()) / len(checks),
            'data_confidence': 100 * sum(bool(v) for v in (checks['calendar within 24h'],
                checks['confirmed lineups'], checks['assigned referee'])) / 3,
            'model_reliability': None, 'market_fit': None, 'agent_consensus': None,
            'price_evidence': None, 'risk_uncertainty': {'model_home_away_games': n,
                'calibrated_interval': None}, 'checks': checks}


def forecast(report, arrivals, days):
    at = report['as_of']
    end = time(at) + timedelta(days=days)
    dossiers = []
    for league in LEAGUES:
        cohort = [r for r in report['fixtures'] if r['league'] == league]
        targets = [r for r in cohort if r['state'] == 'NS' and time(at) < time(r['kickoff']) <= end]
        if not targets:
            continue
        history = sorted((training(r, arrivals) for r in cohort if r['ft_receipted']),
                         key=lambda r: (r['kickoff'], r['id']))
        fits = {m: models.fit(m, history, cutoff=at, league=str(league), profile='MEN', season=2026)
                for m in models.MODELS[1:]}
        simple = [dict(r, date=r['kickoff'][:10], y=outcome('1X2',(r['home_goals'],r['away_goals'])))
                  for r in history]
        core_history = [{k:v for k,v in r.items() if k not in ('season','receipt_sha','synthetic')} for r in history]
        sources = [dict(id=s, enabled=True, reliability=1) for s in sorted({r['source_id'] for r in history})]
        for target in targets:
            fid = str(target['fixture_id'])
            home, away = (str(target['teams'][s]) for s in ('home','away'))
            match = dict(id=fid, home=home, away=away, league=str(league), competition_profile='MEN')
            sports = dict(as_of=at, history=core_history, sources=sources, match=match)
            mass, _, summary = estimate(sports, Policy())
            # Target placeholder is consumed only after Elo emitted its final prediction.
            batch = simple + [dict(id=fid, date=target['kickoff'][:10], season=2026, home=home, away=away,y=0)]
            market_probs = project(mass)
            probabilities = {'Poisson': market_probs['1X2'], 'Elo': elo_predictions(batch)[fid],
                             'frequency': frequency_predictions(batch)[fid]}
            unavailable = {}
            for name, artifact in fits.items():
                pred = models.predict(artifact, match_id=fid, home=home, away=away, league=str(league),
                                      profile='MEN', season=2026, as_of=at, kickoff=target['kickoff'])
                if pred['mass']:
                    probabilities[name] = project(pred['mass'])['1X2']
                else:
                    unavailable[name] = pred['status']
            tactics = profile(report,target['fixture_id'])
            scores = rubric(target,tactics,summary['team_games'])
            role_sources = {'history': sorted({r['source_id'] for r in history if home in (r['home'],r['away']) or away in (r['home'],r['away'])}),
                            'lineups':target['lineups'], 'schedule':target['fixture_sources'],
                            'tactics':sorted({s for v in tactics['venue_split'].values()
                                for f in v['evidence'].values() for s in f['source_ids']})}
            dossiers.append(dict(id=fid, teams=target['team_names'], team_ids=target['teams'], league=league,kickoff=target['kickoff'],
                as_of=at, probabilities=probabilities, unsupported=unavailable, scores=scores,
                goal_markets=market_probs, scenarios=summary['score_scenarios'], tactics=tactics, decision='PASS',
                reasons=['ORIGINAL_SEAL_MISSING','PRICE_UNKNOWN','TACTICAL_FIT_UNVERIFIED'],
                role_inputs=[dict(role=name,phase=phase,mandate=mandate,sources=role_sources.get(name,[]),
                                  assessment=None,status='AWAITING_ORIGINAL_SEAL') for name,phase,mandate in ROLE_SPECS]))
    return dossiers


def evaluate(rows, final):
    labels = {str(r['fixture_id']):r for r in final['fixtures'] if r['ft_receipted']}
    paired = {}
    postmatch = {}
    markets = defaultdict(list)
    observed = defaultdict(int)
    bands = defaultdict(list)
    for r in rows:
        label = labels.get(r['id'])
        if not label or (label['league'],label['teams']) != (r['league'],r['team_ids']) or time(label['kickoff']) != time(r['kickoff']):
            continue
        y = outcome('1X2', [label['goals'][s] for s in ('home','away')])
        bands[r['scores']['football_intelligence']].append(proper_scores(r['probabilities']['Poisson'],y)['brier'])
        paired[r['id']] = (r['probabilities'],y)
        goals = tuple(label['goals'][s] for s in ('home','away'))
        for key, p in r['goal_markets'].items():
            markets[key].append(proper_scores(p,outcome(key,goals)))
        observed['halftime'] += label['halftime'] is not None
        for field, available in label['paired_fields'].items():
            observed[field] += available
        postmatch[r['id']] = dict(result_sources=label['fixture_sources'],
            prematch_data=r['scores']['checks'], model=proper_scores(r['probabilities']['Poisson'],y),
            tactical_scenario='NO_FALSIFIABLE_TACTICAL_PREMISE',
            decision='PASS_CONSISTENT_WITH_MISSING_SEAL_AND_PRICE', legacy_score=None)
    output = {}
    for group in [('Poisson','Elo','frequency'),('Poisson','Elo','frequency',*models.MODELS[1:])]:
        sample = [(p,y) for p,y in paired.values() if all(m in p for m in group)]
        output['+'.join(group)] = {m: dict(n=len(sample),
            **{key:mean(proper_scores(p[m],y)[key] for p,y in sample) if sample else None
               for key in ('brier','log_loss')}, calibration=reliability([(p[m],y) for p,y in sample]))
            for m in group}
    return dict(postmatch=postmatch, outcome_coverage=dict(observed),
                goal_market_scores={k:{m:mean(s[m] for s in values) for m in ('brier','log_loss')}
                                    for k,values in markets.items()}, paired=output, intelligence_bands={str(k):dict(n=len(v),poisson_brier=mean(v)) for k,v in bands.items()},
                original_seal_pairs=0, arena_increment=None, false_deviation_rate=None)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('archive',type=Path)
    cli.add_argument('manifest',type=Path)
    cli.add_argument('at')
    cli.add_argument('--days',type=int,choices=range(1,8),default=1)
    cli.add_argument('--evaluate-at')
    args = cli.parse_args()
    manifest = json.loads(args.manifest.read_bytes())
    arrivals = {'football-source:'+r['raw_sha256']:min(r['links'],key=lambda l:time(l['linked_at']))['linked_at']
                for r in manifest['packets']}
    report = snapshot(args.archive,manifest,args.at)
    rows = forecast(report,arrivals,args.days)
    result = dict(as_of=args.at,packets=report['accepted_packets'],matches=rows,mode='OFFLINE_RECEIPT_REPLAY')
    if args.evaluate_at:
        if time(args.evaluate_at) <= time(args.at):
            raise ValueError('evaluation must follow forecast cutoff')
        result['evaluation'] = evaluate(rows,snapshot(args.archive,manifest,args.evaluate_at))
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))


if __name__ == '__main__':
    main()

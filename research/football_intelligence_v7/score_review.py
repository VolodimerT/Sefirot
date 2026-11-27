"""Evidence completeness per existing ARENA role for an original sealed prediction."""
from research.arena1.diagnostics import diagnose
from scripts.arena_shadow import ROLE_SPECS


def score_original(prediction, quotes, at):
    report = diagnose(prediction, quotes, at)
    roles = {}
    for role, _, _ in ROLE_SPECS:
        findings = [f for f in report['findings'] if f['role'] == role]
        supported = [f for f in findings if f['evidence_ids'] and f['state'] != 'UNKNOWN']
        roles[role] = dict(evidence_completeness=round(100*len(supported)/len(findings)) if findings else None,
                           findings=[{k:f[k] for k in ('state','mechanism','evidence_ids','unknowns',
                                     'counterexample','test_condition','independence_groups')} for f in findings])
    return dict(original_id=prediction['id'], diagnostic_hash=report['hash'], roles=roles,
                blockers=report['markets'], consensus=None, monetary_permission=False)

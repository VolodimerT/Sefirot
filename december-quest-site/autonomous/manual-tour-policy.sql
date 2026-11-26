-- The current autonomous database constraint allows only PASS. Enforce the same
-- ceiling on new tour receipts, including direct PostgREST inserts. Existing
-- research and historical receipts are not scanned, rewritten or reclassified.
alter table public.sefirot_december_quest_seals add constraint dq_v212_tour_policy
check (kind is distinct from 'tour' or (
  payload->>'kind'='tour' and payload#>>'{snapshot,mode}'='pass'
  and payload#>>'{snapshot,verdict}'='пропуск'
  and payload#>>'{snapshot,riskClass}' in ('C','D','RED')
  and jsonb_typeof(payload#>'{snapshot,decisionNote}')='string'
  and length(trim(payload#>>'{snapshot,decisionNote}'))>0
  and payload#>'{snapshot,legs}'='[]'::jsonb
) is true) not valid;

// Map the three PostgREST endpoints to their actual SQL for the local QA servers.
export async function flightRpc(rows,resource,p) {
  if(resource==='rpc/dq_claim_predictor_run')
    return (await rows('select public.dq_claim_predictor_run($1) as r',[p.p_model_version]))[0].r;
  if(resource==='rpc/dq_release_predictor_run'){
    await rows('select public.dq_release_predictor_run($1)',[p.p_token]);
    return null;
  }
  if(resource==='rpc/dq_finish_predictor_run')
    return (await rows('select public.dq_finish_predictor_run($1,$2,$3,$4,$5) as r',
      [p.p_token,...[p.p_run,p.p_forecasts,p.p_validation,p.p_settlements].map(x=>JSON.stringify(x))]))[0].r;
}

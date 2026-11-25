import assert from 'node:assert/strict';

const listen = Deno.serve.bind(Deno);
const settings = {hostname:'127.0.0.1',port:0,onListen(){}};
const token = 'a'.repeat(64);
const roles = [];
const auth = listen(settings, async request => {
  roles.push([request.method,new URL(request.url).pathname,request.headers.get('apikey')]);
  const payload = await request.json();
  return Response.json(payload.p_token === token);
});
let edge;
try {
  Deno.env.set('SUPABASE_URL', `http://127.0.0.1:${auth.addr.port}`);
  Deno.env.set('SUPABASE_SERVICE_ROLE_KEY', 'qa-rest-role');
  Deno.env.delete('DQ_ODDS_API_FREE_KEY');
  Deno.env.delete('DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN');
  Deno.serve = handler => (edge = listen(settings, handler));
  await import('../paper-index.js');
  const url = `http://127.0.0.1:${edge.addr.port}`;
  const call = async (method, body, credential) => {
    const headers = credential ? {'x-dq-predictor-token':credential} : {};
    const response = await fetch(url,{method,body,headers,signal:AbortSignal.timeout(5000)});
    assert.equal(response.headers.get('cache-control'),'no-store');
    return {status:response.status,body:await response.json()};
  };
  assert.deepEqual(await call('GET'),{status:200,body:{ok:true,mode:'DAILY_PAPER_TEST',publication_allowed:false,
    database_writes:false,financial_operations:false,odds_configured:false,context_configured:false}});
  assert.equal((await call('PUT')).status,405);
  assert.equal((await call('POST','{}')).status,401);
  assert.equal((await call('POST','{}','b'.repeat(64))).status,401);
  assert.equal((await call('POST','not JSON',token)).body.error,'INVALID_PAPER_INPUT');
  assert.equal((await call('POST','{"mode":"HISTORICAL_REPLAY"}',token)).body.error,'DAILY_PAPER_TEST_REQUIRED');
  const valid = await call('POST',JSON.stringify({mode:'DAILY_PAPER_TEST',date:'2027-01-06',fixtures:[]}),token);
  assert.equal(valid.status,200);
  assert.equal(valid.body.status,'NO_UPCOMING_FIXTURES');
  assert.equal(valid.body.verdict,'PASS');
  assert.equal(valid.body.real_cost,0);
  assert.equal(roles.length,4);
  for(const request of roles)assert.deepEqual(request,['POST','/rest/v1/rpc/dq_predictor_cron_authorized','qa-rest-role']);
  console.log('Paper Edge HTTP isolation, auth, invalid mode and empty PASS: PASS');
} finally {
  if(edge)await edge.shutdown();
  await auth.shutdown();
}

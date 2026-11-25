/* Private paper endpoint. The only database call verifies the existing runner token. */
import { executeDaily, modes } from './paper-runner.js';
import { paperSources } from './paper-sources.js';

const project=Deno.env.get('SUPABASE_URL')||'';
const role=Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')||'';
const oddsKey=Deno.env.get('DQ_ODDS_API_FREE_KEY')?.trim()||'';
const contextToken=Deno.env.get('DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN')?.trim()||'';
const json=(body,status=200)=>Response.json(body,{status,headers:{'Cache-Control':'no-store'}});
async function authorised(token){
  if(!project||!role||!/^[a-f0-9]{64}$/i.test(token))return false;
  try{
    const r=await fetch(project+'/rest/v1/rpc/dq_predictor_cron_authorized',{
      method:'POST',signal:AbortSignal.timeout(8000),
      headers:{apikey:role,Authorization:'Bearer '+role,'Content-Type':'application/json'},
      body:JSON.stringify({p_token:token})
    });
    return r.ok&&await r.json()===true;
  }catch{return false;}
}

Deno.serve(async req=>{
  if(req.method==='GET')return json({ok:true,mode:modes.daily,publication_allowed:false,database_writes:false,
    financial_operations:false,odds_configured:Boolean(oddsKey),context_configured:Boolean(contextToken)});
  if(req.method!=='POST')return json({ok:false,error:'METHOD_NOT_ALLOWED'},405);
  if(!await authorised(req.headers.get('x-dq-predictor-token')||''))return json({ok:false,error:'UNAUTHORIZED'},401);
  try{
    if(Number(req.headers.get('content-length'))>250000)return json({ok:false,error:'REQUEST_TOO_LARGE'},413);
    const raw=await req.text();
    if(raw.length>250000)return json({ok:false,error:'REQUEST_TOO_LARGE'},413);
    const input=JSON.parse(raw);
    if(input?.mode!==modes.daily)return json({ok:false,error:'DAILY_PAPER_TEST_REQUIRED'},400);
    const paper=await executeDaily({date:input.date,calendar:input.fixtures,sources:paperSources(),oddsKey,
      contextGateway:{project,token:contextToken}});
    const sealedAt=new Date().toISOString();
    if(paper.fixtures.some(f=>Date.parse(f.kickoff)<=Date.parse(sealedAt)))return json({ok:false,error:'PAPER_SEAL_AFTER_KICKOFF'},409);
    return json({...paper,sealed_at:sealedAt});
  }catch(error){
    const invalidInput=error instanceof SyntaxError||/^INVALID_PAPER_/.test(error?.message);
    return json({ok:false,error:invalidInput?'INVALID_PAPER_INPUT':'PAPER_RUN_FAILED'},invalidInput?400:503);
  }
});

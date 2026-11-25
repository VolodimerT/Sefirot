/* Isolated December Quest runner. POST requires the Vault-stored cron token. */
import Core from "./core.js";
import { execute } from "./run.js";
import { collectGateway } from "./gateway.js";
import { fetchCsvWithRetry } from "./csv-source.js";
import { fetchResultBackup } from './result-backups.js';
import { collectTimestampedOdds, oddsHorizonHours } from "./odds-gateway.js";
const PROJECT=Deno.env.get("SUPABASE_URL")||"";
const SECRET=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
const cors={"Access-Control-Allow-Origin":"https://sefirot-december-quest-2026.vercel.app","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"content-type,apikey,x-dq-predictor-token"};
function json(x,status=200){return new Response(JSON.stringify(x),{status,headers:{...cors,"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});}
const headers=()=>({"apikey":SECRET,"Authorization":"Bearer "+SECRET,"Content-Type":"application/json","Accept":"application/json"});
async function rest(path,options={}){
 if(!PROJECT||!SECRET)throw Error('SUPABASE_SERVER_ENV_UNAVAILABLE');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
 try{
  const r=await fetch(PROJECT+"/rest/v1/"+path,{...options,headers:{...headers(),...(options.headers||{})},signal:controller.signal});
  const text=await r.text();
  if(!r.ok)throw Error('SUPABASE_HTTP_'+r.status);
  return text?JSON.parse(text):null;
 }finally{clearTimeout(timer);}
}
async function authenticate(token){
 if(typeof token!=='string'||!/^[a-f0-9]{64}$/i.test(token))return false;
 try{
  const data=await rest('rpc/dq_predictor_cron_authorized',{method:'POST',body:JSON.stringify({p_token:token})});
  return data===true;
 }catch(_e){return false;}
}
const gatewayToken=Deno.env.get('DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN')||'';
const oddsKey=Deno.env.get('DQ_ODDS_API_FREE_KEY')?.trim()||'';
Deno.serve(async req=>{
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers:cors});
 if(req.method==='GET')return json({ok:true,name:'december-quest-autonomous-predictor',model_version:Core.MODEL_VERSION,method:'POST_AUTH_ONLY',money_permission:false,live:false,betting_enabled:false,provider:'football-data.co.uk',history_backups:['openfootball','openligadb.de'],odds_window_hours:oddsHorizonHours,team_form_windows:[5,10,20],sports_gateway_configured:Boolean(gatewayToken),odds_gate:{timestamped_source_configured:Boolean(oddsKey),csv_mode:'INDICATIVE_ONLY',max_quote_age_minutes:60}});
 if(req.method!=='POST')return json({ok:false,error:'POST_REQUIRED'},405);
 const token=req.headers.get('x-dq-predictor-token')||'';
 if(!(await authenticate(token)))return json({ok:false,error:'UNAUTHORIZED'},401);
 try{
  const query=new URL(req.url).searchParams;
  const recovery=query.has('retry_until');
  const deadline=query.get('retry_until')??query.get('run_until');
  const retryUntil=deadline===null?null:Number(deadline);
  if(deadline!==null && (!/^\d{13}$/.test(deadline)||Date.now()>=retryUntil||retryUntil-Date.now()>600000))
    return json({ok:false,error:'RECOVERY_WINDOW_CLOSED'},409);
  const result=await execute({rest,retryUntil,recoveryProviderContextUnavailable:recovery&&Boolean(gatewayToken||oddsKey),
   csv:url=>fetchCsvWithRetry(url,true),
   gateway:(fixtures,clock)=>collectGateway(PROJECT,recovery?null:gatewayToken,fixtures,clock),
   odds:(fixtures,clock)=>collectTimestampedOdds(fixtures,clock,recovery?null:oddsKey),backup:recovery?null:fetchResultBackup});
  if(result.skipped==='RUN_IN_PROGRESS'){
   const response=json({ok:true,...result},202);
   response.headers.set('Retry-After',String(result.retry_after_seconds));
   return response;
  }
  return json({ok:result.status!=='SOURCE_ERROR',...result},result.status==='SOURCE_ERROR'?503:200);
 }catch(e){
  const reason=/^SUPABASE_HTTP_\d{3}$/.test(e.message) || ['RECOVERY_WINDOW_CLOSED','INVALID_RUN_CLAIM','FIXTURE_SOURCE_LIMIT','PREMATCH_POLICY_CONFLICT'].includes(e.message)
    ? e.message : 'PREDICTOR_FAILED';
  console.error('DQ_AUTOPREDICTOR_FAILURE',reason);
  return json({ok:false,error:'RUN_FAILED',reason},503);
 }
});

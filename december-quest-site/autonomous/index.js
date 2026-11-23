/* Isolated December Quest model runner: public CSV only, POST requires Vault-stored cron token. */
import Core from "./core.js";
const PROJECT=Deno.env.get("SUPABASE_URL")||"";
const SECRET=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
const STATIC_BASE="https://football-data.co.uk";
const CSV_CODES=Core.LEAGUE_FILES;
const cors={"Access-Control-Allow-Origin":"https://sefirot-december-quest-2026.vercel.app","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"content-type,apikey,x-dq-predictor-token"};
function json(x,status=200){return new Response(JSON.stringify(x),{status,headers:{...cors,"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});}
const headers=()=>({"apikey":SECRET,"Authorization":"Bearer "+SECRET,"Content-Type":"application/json","Accept":"application/json"});
async function rest(path,options={}){
 if(!PROJECT||!SECRET)throw Error('SUPABASE_SERVER_ENV_UNAVAILABLE');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
 try{
  const r=await fetch(PROJECT+"/rest/v1/"+path,{...options,headers:{...headers(),...(options.headers||{})},signal:controller.signal});
  const text=await r.text();
  if(!r.ok)throw Error('SUPABASE_HTTP_'+r.status+'_'+text.slice(0,100));
  return text?JSON.parse(text):null;
 }finally{clearTimeout(timer);}
}
async function getCsv(url){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),11000);
 try{
  const r=await fetch(url,{redirect:"follow",signal:c.signal,headers:{Accept:"text/csv,text/plain;q=0.9,*/*;q=0.1"}});
  if(!r.ok||r.url&&!/^https:\/\/(www\.)?football-data\.co\.uk\//.test(r.url))throw Error("PROVIDER_HTTP_OR_REDIRECT_"+r.status);
  const len=Number(r.headers.get("content-length")||"0");if(len>4500000)throw Error('CSV_TOO_LARGE');
  const text=await r.text();if(text.length>4500000)throw Error('CSV_TOO_LARGE');
  if(text.slice(0,120).toLowerCase().includes('<html'))throw Error('PROVIDER_HTML_NOT_CSV');
  return text;
 }finally{clearTimeout(timer);}
}
async function authenticate(token){
 if(typeof token!=='string'||!/^[a-f0-9]{64}$/i.test(token))return false;
 try{
  const data=await rest('rpc/dq_predictor_cron_authorized',{method:'POST',body:JSON.stringify({p_token:token})});
  return data===true;
 }catch(_e){return false;}
}
async function execute(){
 const runStarted=new Date(),now=runStarted.getTime();
 const recent=await rest("sefirot_december_quest_auto_runs?select=started_at,run_status&order=started_at.desc&limit=1");
 if(Array.isArray(recent)&&recent[0]?.run_status==='OK'&&now-Date.parse(recent[0].started_at)<6*3600*1000)return {ok:true,skipped:"RUN_WITHIN_SIX_HOURS",at:recent[0].started_at};
 const fixtures=await rest("sefirot_december_quest_fixtures?select=fixture_key,competition,home_team,away_team,kickoff,source_name,source_url,source_quality,timing_status&kickoff=gt."+encodeURIComponent(new Date(now+30*60000).toISOString())+"&order=kickoff.asc&limit=200");
 if(!Array.isArray(fixtures)||fixtures.length>200)throw Error('FIXTURE_SOURCE_SHAPE');
 const leagues=[...new Set(fixtures.map(f=>f.competition))].filter(x=>Object.hasOwn(CSV_CODES,x));
 const urls=[];
 for(const code of leagues){for(const season of ['2627','2526'])urls.push({code,season,url:STATIC_BASE+'/mmz4281/'+season+'/'+CSV_CODES[code]+'.csv'});}
 urls.push({code:"weekly",season:"weekly",url:STATIC_BASE+'/fixtures.csv'});
 if(urls.length>12)throw Error('TOO_MANY_SOURCE_FILES');
 const fetched=await Promise.all(urls.map(async row=>{
  try{const text=await getCsv(row.url);return {...row,ok:true,records:Core.parseCsv(text),text};}
  catch(e){return {...row,ok:false,error:String(e.message||e).slice(0,100)};}
 }));
 let dataByLeague={};
 for(const league of leagues){
  let all=[];
  for(const pack of fetched.filter(x=>x.code===league&&x.ok)){
   try{all.push(...Core.resultsFromCsv(pack.text,league,now));}catch(e){/* do not invent */} 
  }
  // Exact deduplication across current and previous CSV snapshots. Only completed games are used.
  const uniq=new Map();for(const row of all)uniq.set(row.date+'|'+row.home+'|'+row.away,row);
  dataByLeague[league]=[...uniq.values()];
 }
 const weekly=fetched.find(x=>x.code==='weekly'&&x.ok)?.records||[];
 const rows=[];let ready=0,insufficient=0;
 for(const g of fixtures){
  let r=Core.forecast(g,dataByLeague[g.competition]||[],now);
  r=Core.attachQuotes(r,weekly,g,now);
  r.evidence={...r.evidence,upstream_sources:fetched.filter(p=>p.code===g.competition).map(p=>({season:p.season,url:p.url,ok:p.ok})),
   fixture_source:g.source_url,fixture_source_quality:g.source_quality,fixture_timing_status:g.timing_status,
   public_history_only:true,provider_not_betting_exchange:true,not_fitted_on_future_results:true};
  if(r.status==='MODEL_ONLY'||r.status==='WAITING_ODDS')ready++;else insufficient++;
  // Evidence fields are model-only; P has no bookmaker-derived calibration.
  rows.push(r);
 }
 // Abort on total provider failure: do not overwrite credible data with unverified zeroes.
 const sourceGood=fetched.filter(x=>x.ok).length,sourceErrors=fetched.filter(x=>!x.ok).map(x=>x.code+':'+x.season+' '+x.error);
 if(sourceGood===0)throw Error('ALL_PUBLIC_CSV_SOURCES_UNAVAILABLE');
 const slices=[];for(let i=0;i<rows.length;i+=30)slices.push(rows.slice(i,i+30));
 for(const slice of slices){
  await rest('sefirot_december_quest_auto_forecasts?on_conflict=fixture_key',{method:'POST',headers:{Prefer:'resolution=merge-duplicates,return=minimal'},body:JSON.stringify(slice)});
 }
 const snapshotRows=rows.filter(x=>['MODEL_ONLY','WAITING_ODDS'].includes(x.status)).map(x=>({
  fixture_key:x.fixture_key,model_version:x.model_version,kickoff:x.kickoff,generated_day:new Date(now).toISOString().slice(0,10),
  probabilities:x.probabilities,markets:x.markets,status:x.status,evidence:x.evidence
 }));
 for(let i=0;i<snapshotRows.length;i+=30){
  await rest('sefirot_december_quest_auto_snapshots?on_conflict=fixture_key,generated_day',{method:'POST',headers:{Prefer:'resolution=ignore-duplicates,return=minimal'},body:JSON.stringify(snapshotRows.slice(i,i+30))});
 }
 const runStatus=sourceErrors.length?'PARTIAL':'OK';
 await rest('sefirot_december_quest_auto_runs',{method:'POST',headers:{Prefer:'return=minimal'},body:JSON.stringify({
  model_version:Core.MODEL_VERSION,provider:'football-data.co.uk',
  started_at:runStarted.toISOString(),completed_at:new Date().toISOString(),sources_attempted:urls.length,fetch_ok:sourceGood,
  scanned:fixtures.length,forecasted:ready,insufficient,errors:sourceErrors.slice(0,20),run_status:runStatus
 })});
 return {ok:true,status:runStatus,model_version:Core.MODEL_VERSION,fixture_count:fixtures.length,with_model:ready,missing_data:insufficient,
  sources_ok:sourceGood,sources_attempted:urls.length,source_errors:sourceErrors,
  odds_provider_timestamp_verified:false,action:'SHADOW_ONLY',wagers_executed:0};
}
Deno.serve(async req=>{
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers:cors});
 if(req.method==='GET')return json({ok:true,name:'december-quest-autonomous-predictor',model_version:Core.MODEL_VERSION,method:'POST_AUTH_ONLY',money_permission:false,live:false,betting_enabled:false,provider:'football-data.co.uk'});
 if(req.method!=='POST')return json({ok:false,error:'POST_REQUIRED'},405);
 const token=req.headers.get('x-dq-predictor-token')||'';
 if(!(await authenticate(token)))return json({ok:false,error:'UNAUTHORIZED'},401);
 try{
  const result=await execute();return json(result,200);
 }catch(e){
  console.error('DQ_AUTOPREDICTOR_FAILURE',String(e.message||e).slice(0,100));
  return json({ok:false,error:'RUN_FAILED',reason:String(e.message||e).slice(0,150)},503);
 }
});

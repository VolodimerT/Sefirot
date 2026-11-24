/* Isolated December Quest model runner: public CSV only, POST requires Vault-stored cron token. */
import Core from "./core.js";
import { execute } from "./run.js";
import { collectGateway } from "./gateway.js";
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
  if(!r.ok)throw Error('SUPABASE_HTTP_'+r.status+'_'+text.slice(0,100));
  return text?JSON.parse(text):null;
 }finally{clearTimeout(timer);}
}
async function getCsv(url){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),11000);
 try{
  const r=await fetch(url,{redirect:"error",signal:c.signal,headers:{Accept:"text/csv,text/plain;q=0.9,*/*;q=0.1"}});
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
async function fetchCsvWithRetry(url){
 try{return await getCsv(url);}
 catch(error){
  if(!['AbortError','TypeError'].includes(error.name)&&!/^PROVIDER_HTTP_OR_REDIRECT_5/.test(error.message))throw error;
  await new Promise(resolve=>setTimeout(resolve,250));
  return getCsv(url);
 }
}
const gatewayToken=Deno.env.get('DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN')||'';
Deno.serve(async req=>{
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers:cors});
 if(req.method==='GET')return json({ok:true,name:'december-quest-autonomous-predictor',model_version:Core.MODEL_VERSION,method:'POST_AUTH_ONLY',money_permission:false,live:false,betting_enabled:false,provider:'football-data.co.uk'});
 if(req.method!=='POST')return json({ok:false,error:'POST_REQUIRED'},405);
 const token=req.headers.get('x-dq-predictor-token')||'';
 if(!(await authenticate(token)))return json({ok:false,error:'UNAUTHORIZED'},401);
 try{
  const result=await execute({rest,csv:fetchCsvWithRetry,
   gateway:(fixtures,clock)=>collectGateway(PROJECT,gatewayToken,fixtures,clock)});
  return json({ok:result.status!=='SOURCE_ERROR',...result},result.status==='SOURCE_ERROR'?503:200);
 }catch(e){
  console.error('DQ_AUTOPREDICTOR_FAILURE',String(e.message||e).slice(0,100));
  return json({ok:false,error:'RUN_FAILED',reason:String(e.message||e).slice(0,150)},503);
 }
});

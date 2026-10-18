/* Reviewable source template for the existing private PR #22 store relay.
 * No deployed credential, key provisioning or production rollout in P1.
 */
const DEPLOYED_AUTH = []; // operator-enrolled token SHA256s, default fail closed
const MAX_BODY = 2900000;
const MAX_RESPONSE = 4100000;
const json = (data, status = 200) => Response.json(data, {status, headers: {
  "cache-control": "no-store", "x-content-type-options": "nosniff"
}});
async function sha256(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, "0")).join("");
}
function constantEqual(a,b) {
  if(a.length!==b.length) return false;
  let mismatch=0;
  for(let i=0;i<a.length;i++) mismatch |= a.charCodeAt(i)^b.charCodeAt(i);
  return mismatch===0;
}
async function bounded(response, limit) {
  const reader=response.body?.getReader();
  if(!reader) return "";
  const chunks=[];let size=0;
  try {
    while(true) {
      const {done,value}=await reader.read();if(done)break;
      size+=value.byteLength;
      if(size>limit){await reader.cancel();throw new Error("SIZE");}
      chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes=new Uint8Array(size);let at=0;
  for(const part of chunks){bytes.set(part,at);at+=part.byteLength;}
  return new TextDecoder("utf-8",{fatal:true}).decode(bytes);
}

export function createStoreHandler({credentialHashes=DEPLOYED_AUTH,
    env=(name)=>Deno.env.get(name), fetcher=fetch, timeoutMs=12000}={}) {
  return async function handle(req) {
    if(req.method!=="POST") return json({ok:false,error:"POST_REQUIRED"},405);
    const token=req.headers.get("x-sefirot-bridge-store-token")??"";
    const hash=await sha256(token);
    if(!/^[A-Za-z0-9_-]{48,128}$/.test(token) ||
       !credentialHashes.some(value=>constantEqual(value,hash)))
      return json({ok:false,error:"UNAUTHORIZED"},401);
    const length=Number(req.headers.get("content-length")||"0");
    if(!Number.isSafeInteger(length)||length<2||length>MAX_BODY)
      return json({ok:false,error:"INVALID_REQUEST_SIZE"},413);
    let body;
    try {body=JSON.parse(await bounded(req,MAX_BODY));}
    catch {return json({ok:false,error:"INVALID_JSON"},400);}
    if(!body||typeof body!=="object"||Array.isArray(body))return json({ok:false,error:"INVALID_JSON"},400);
    const keys=Object.keys(body).sort().join(",");
    const pull=body.action==="pull"&&keys==="action";
    const save=body.action==="save"&&keys==="action,checksum,revision,snapshot"
      &&Number.isSafeInteger(body.revision)&&body.revision>=0
      &&typeof body.snapshot==="string"&&body.snapshot.length>20&&body.snapshot.length<=2800000
      &&typeof body.checksum==="string"&&/^[0-9a-f]{64}$/.test(body.checksum);
    const claim=body.action==="claim"&&keys==="action";
    const sourceStatus=body.action==="source_status"&&keys==="action";
    const sourceExport=body.action==="source_export"&&keys==="action,after"
      &&typeof body.after==="string"&&/^(?:[0-9a-f]{64})?$/.test(body.after);
    const probeComplete=body.action==="probe_complete"&&keys==="action,attempt,error,id,response,success"
      &&Number.isInteger(body.attempt)&&body.attempt>=1&&body.attempt<=3;
    const complete=(body.action==="complete" || probeComplete) &&
      (keys==="action,error,id,response,success" || keys==="action,attempt,error,id,response,success")
      &&typeof body.id==="string"&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body.id)
      &&typeof body.success==="boolean"
      &&(body.response===null||body.response&&typeof body.response==="object"&&!Array.isArray(body.response))
      &&(body.error===null||typeof body.error==="string"&&body.error.length<=300)
      &&(!Object.hasOwn(body,"attempt")||Number.isInteger(body.attempt)&&body.attempt>=1&&body.attempt<=3);
    const source=body.action==="situation_source"&&keys==="action,receipt_id"
      &&typeof body.receipt_id==="string"&&/^[0-9a-f]{64}$/.test(body.receipt_id);
    const enqueue=body.action==="situation_enqueue"&&keys==="action,request"
      &&body.request&&typeof body.request==="object"&&!Array.isArray(body.request)
      &&new TextEncoder().encode(JSON.stringify(body.request)).length<=16384;
    if(!pull&&!save&&!claim&&!complete&&!source&&!enqueue&&!sourceStatus&&!sourceExport)return json({ok:false,error:"INVALID_ACTION"},422);
    const url=env("SUPABASE_URL"), service=env("SUPABASE_SERVICE_ROLE_KEY");
    if(!url||!service)return json({ok:false,error:"SERVER_CONFIGURATION"},503);
    let origin;
    try {
      origin=new URL(url);
      if(origin.protocol!=="https:" || origin.username || origin.password ||
         origin.search || origin.hash || origin.pathname!=="/" ||
         origin.port && origin.port!=="443") throw new Error("URL");
    } catch {return json({ok:false,error:"SERVER_CONFIGURATION"},503);}
    const leased=complete&&Object.hasOwn(body,"attempt");
    const endpoint=sourceStatus?"sefirot_source_status":sourceExport?"sefirot_source_export":
      pull?"sefirot_bridge_pull":save?"sefirot_bridge_save":claim?"sefirot_chat_claim":
      source?"sefirot_situation_source":enqueue?"sefirot_situation_enqueue":
      probeComplete?"sefirot_probe_complete":leased?"sefirot_situation_complete":"sefirot_chat_complete";
    const params=sourceStatus?{}:sourceExport?{p_after:body.after}:
      pull||claim?{}:save?{p_revision:body.revision,p_snapshot:body.snapshot,p_checksum:body.checksum}:
      source?{p_receipt_id:body.receipt_id}:enqueue?{p_request:body.request}:
      {p_id:body.id,p_success:body.success,p_response:body.response,p_error:body.error,
       ...(leased?{p_attempt:body.attempt}:{})};
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try {
      const response=await fetcher(origin.origin+"/rest/v1/rpc/"+endpoint,{
        method:"POST",redirect:"error",signal:controller.signal,
        headers:{apikey:service,authorization:"Bearer "+service,"content-type":"application/json"},
        body:JSON.stringify(params)});
      if(!response.ok) {
        if(probeComplete&&response.status>=400&&response.status<500)
          return json({ok:false,error:response.status===429?"STORE_RATE_LIMITED":"PROBE_COMPLETION_REJECTED"},
            response.status===429?429:409);
        return json({ok:false,error:response.status===429?"STORE_RATE_LIMITED":"DATABASE_UNAVAILABLE"},503);
      }
      const value=JSON.parse(await bounded(response,MAX_RESPONSE));
      if(!value||typeof value!=="object"||Array.isArray(value)
        ||(sourceStatus&&(value.schema!=="football-source-store-v1"||typeof value.ready!=="boolean"))
        ||(sourceExport&&!(value.next===null||typeof value.next==="string"&&/^[0-9a-f]{64}$/.test(value.next)))
        ||((pull||save)&&!Number.isSafeInteger(value.revision))
        ||(claim&&!Object.hasOwn(value,"job"))||(complete&&value.completed!==true)
        ||(probeComplete&&(value.id!==body.id||value.attempts!==body.attempt))
        ||(source&&(!Object.hasOwn(value,"receipt")||
            value.receipt!==null&&new TextEncoder().encode(JSON.stringify(value.receipt)).length>65536))
        ||(enqueue&&(typeof value.job_id!=="string"||typeof value.request_key!=="string")))
        return json({ok:false,error:"INVALID_STORE_RESPONSE"},502);
      return json({ok:true,data:value});
    } catch {return json({ok:false,error:"STORE_UPSTREAM_UNAVAILABLE"},503);}
    finally {clearTimeout(timer);}
  };
}

if(typeof Deno!=="undefined") Deno.serve(createStoreHandler());

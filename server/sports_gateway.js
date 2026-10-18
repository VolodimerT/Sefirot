/* Private API-Football bridge. Deployment inserts hashes, never key values. */
const DEPLOYED_AUTH = []; // SEFIROT_DEPLOY_AUTH
const HOST = "v3.football.api-sports.io";
const MAX_BODY = 16384;
const MAX_RESPONSE = 2000000;
const TIMEOUT_MS = 9000;
const ALLOWED = {
  status: [],
  leagues: ["id", "name", "country", "code", "season", "team", "type", "current", "search", "last"],
  teams: ["id", "name", "league", "season", "country", "code", "venue", "search"],
  fixtures: ["id", "ids", "date", "league", "season", "team", "last", "next", "from", "to", "round", "status", "venue", "timezone"],
  "fixtures/lineups": ["fixture", "team", "player", "type"],
  "fixtures/statistics": ["fixture", "team", "type", "half"],
  injuries: ["league", "season", "fixture", "team", "player", "date", "ids", "timezone"],
  // Research context and post-match evidence. Odds and live feeds remain excluded.
  standings: ["league", "season", "team"],
  "teams/statistics": ["league", "season", "team", "date"],
  "fixtures/headtohead": ["h2h", "last", "league", "season", "from", "to", "status", "venue"],
  "fixtures/events": ["fixture", "team", "player", "type"],
  "fixtures/players": ["fixture", "team"],
  coachs: ["id", "team", "search"],
  "players/squads": ["team", "player"],
  "players/topscorers": ["league", "season"],
  "players/topassists": ["league", "season"],
  "players/topyellowcards": ["league", "season"],
  "players/topredcards": ["league", "season"],
};
const REQUIRED = {
  standings: ["league", "season"],
  "teams/statistics": ["league", "season", "team"],
  "fixtures/headtohead": ["h2h"],
  "fixtures/events": ["fixture"],
  "fixtures/players": ["fixture"],
  "players/topscorers": ["league", "season"],
  "players/topassists": ["league", "season"],
  "players/topyellowcards": ["league", "season"],
  "players/topredcards": ["league", "season"],
};
const OBJECT_RESPONSE_ENDPOINTS = new Set(["teams/statistics"]);

function validNewParams(endpoint, params) {
  if (!Object.hasOwn(REQUIRED, endpoint) && !["coachs", "players/squads"].includes(endpoint)) return true;
  if (REQUIRED[endpoint]?.some(key => !Object.hasOwn(params, key))) return false;
  if (["coachs", "players/squads"].includes(endpoint) && !Object.keys(params).length) return false;
  for (const key of ["fixture", "league", "season", "team", "id", "player", "last"]) {
    if (Object.hasOwn(params, key) && !/^[0-9]{1,10}$/.test(String(params[key]))) return false;
    if (Object.hasOwn(params, key) && Number(params[key]) <= 0) return false;
  }
  if (Object.hasOwn(params, "last") && Number(params.last) > 50) return false;
  if (endpoint === "fixtures/headtohead") {
    const pair = params.h2h;
    if (typeof pair !== "string" || !/^[1-9][0-9]{0,9}-[1-9][0-9]{0,9}$/.test(pair)) return false;
    if (pair.split("-")[0] === pair.split("-")[1]) return false;
  }
  if (endpoint === "coachs" && Object.hasOwn(params, "search") &&
      (typeof params.search !== "string" || params.search.length < 3)) return false;
  if (endpoint === "teams/statistics" && Object.hasOwn(params, "date") &&
      (typeof params.date !== "string" || !/^20[0-9]{2}-[01][0-9]-[0-3][0-9]$/.test(params.date))) return false;
  if (endpoint === "teams/statistics" && Object.hasOwn(params, "date")) {
    const parsed = new Date(params.date + "T00:00:00Z");
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== params.date) return false;
  }
  return true;
}
const QUOTA_HEADERS = ["x-requests-remaining", "x-requests-used", "x-requests-last",
  "x-ratelimit-requests-remaining", "x-ratelimit-requests-limit",
  "x-ratelimit-remaining", "x-ratelimit-limit"];

// Python canonical JSON of the values carried over the JSON wire: integers
// stay integers; small fractional exponents use the same two-digit exponent.
function sourceCanonical(v) {
  if(v===null||typeof v==='boolean'||typeof v==='string')return JSON.stringify(v);
  if(typeof v==='number') {
    if(!Number.isFinite(v))throw new GatewayError('SOURCE_UNSAFE');
    const s=!Number.isInteger(v)&&Math.abs(v)<1e-4?v.toExponential():JSON.stringify(v);
    return s.replace(/e([+-])(\d)$/,(_,sign,n)=>'e'+sign+'0'+n);
  }
  if(Array.isArray(v))return '['+v.map(sourceCanonical).join(',')+']';
  const cmp=(a,b)=>{const x=Array.from(a),y=Array.from(b);for(let i=0;i<Math.min(x.length,y.length);i++){
    const d=x[i].codePointAt(0)-y[i].codePointAt(0);if(d)return d;}return x.length-y.length;};
  return '{'+Object.keys(v).sort(cmp).map(k=>JSON.stringify(k)+':'+sourceCanonical(v[k])).join(',')+'}';
}
function sourceSafe(data,endpoint) {
  const labels=new Set(['Total Shots','Shots on Goal','Shots off Goal','Blocked Shots','Shots insidebox',
    'Shots outsidebox','Corner Kicks','Yellow Cards','Red Cards','Fouls','Offsides','Ball Possession',
    'Expected Goals','expected_goals','Goals Prevented','goals_prevented','Total passes','Passes accurate',
    'Passes %','Goalkeeper Saves']);
  if(endpoint==='fixtures/statistics'&&(!Array.isArray(data.response)||data.response.some(r=>
    !Array.isArray(r.statistics)||r.statistics.some(s=>!labels.has(s.type)))))return false;
  const todo=[[data,0]];
  while(todo.length){const [v,d]=todo.pop();if(d>24)return false;
    if(v&&typeof v==='object')for(const [k,x] of Object.entries(v)){
      const label=k.toLowerCase().replace(/[^a-z0-9]/g,'');
      if(['apikey','authorization','password','headers'].includes(label)||label.includes('secret')||label.includes('token'))return false;
      todo.push([x,d+1]);}}
  return true;
}

class GatewayError extends Error {
  constructor(code) { super(code); this.code = code; }
}

function json(data, status = 200) {
  return Response.json(data, {status, headers: {"cache-control": "no-store"}});
}

function checkFixtureEcho(data, params) {
  if (data.get !== "fixtures") throw new GatewayError("ENDPOINT_ECHO_MISMATCH");
  const echoed = data.parameters;
  if (!echoed || typeof echoed !== "object" || Array.isArray(echoed) ||
      Object.keys(echoed).length !== Object.keys(params).length ||
      Object.entries(echoed).some(([key, value]) => !Object.hasOwn(params, key) ||
        !(typeof value === "string" || Number.isSafeInteger(value)) || String(value) !== String(params[key]))) {
    throw new GatewayError("QUERY_ECHO_MISMATCH");
  }
}

async function sha256(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}

async function readBounded(response, limit) {
  const reader = response.body?.getReader();
  if (!reader) return "";
  let total = 0;
  const chunks = [];
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        throw new GatewayError("RESPONSE_TOO_LARGE");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return new TextDecoder("utf-8", {fatal: true}).decode(bytes); }
  catch { throw new GatewayError("INVALID_JSON"); }
}

async function fetchBounded(url, options, limit, timeout = TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {...options, redirect: "error", signal: controller.signal});
    return {response, text: await readBounded(response, limit)};
  } catch (error) {
    if (error instanceof GatewayError) throw error;
    throw new GatewayError(controller.signal.aborted || error?.name === "AbortError"
      ? "UPSTREAM_TIMEOUT" : "UPSTREAM_UNAVAILABLE");
  } finally { clearTimeout(timer); }
}

function parse(text) {
  try { return JSON.parse(text); }
  catch { throw new GatewayError("INVALID_JSON"); }
}

async function serverRpc(name, body) {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !/^https:\/\/[a-z0-9]{20}\.supabase\.co\/?$/.test(url) || !key) {
    throw new GatewayError("SERVER_CONFIGURATION_UNAVAILABLE");
  }
  const result = await fetchBounded(url.replace(/\/$/, "") + "/rest/v1/rpc/" + name, {
    method: "POST", headers: {apikey: key, authorization: "Bearer " + key,
      "content-type": "application/json"}, body: JSON.stringify(body),
  }, MAX_BODY, 3000);
  if (result.response.status !== 200) throw new GatewayError("SERVER_RPC_UNAVAILABLE");
  return parse(result.text);
}

async function apiKey() {
  let value;
  try { value = await serverRpc("sefirot_api_football_secret", {}); }
  catch (error) {
    if (error.code === "SERVER_CONFIGURATION_UNAVAILABLE") throw error;
    throw new GatewayError("API_FOOTBALL_KEY_NOT_CONFIGURED");
  }
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,256}$/.test(value.trim())) {
    throw new GatewayError("API_FOOTBALL_KEY_NOT_CONFIGURED");
  }
  return value.trim();
}

const BUDGET_REASONS = ["PAUSED", "BUSY", "UNFINISHED_ATTEMPT", "STALE_BUDGET",
  "DAILY_LIMIT", "MINUTE_LIMIT"];
async function reserveBudget() {
  try {
    const value = await serverRpc("sefirot_sports_budget_reserve", {});
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    if (value.allowed === false && Object.keys(value).length === 2 &&
        BUDGET_REASONS.includes(value.reason)) return value;
    if (value.allowed !== true || Object.keys(value).length !== 2 ||
        typeof value.permit !== "string" ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.permit)) {
      throw new Error();
    }
    return value;
  } catch { throw new GatewayError("SHARED_BUDGET_UNAVAILABLE"); }
}
async function finishBudget(permit, observation) {
  try {
    const value = await serverRpc("sefirot_sports_budget_finish", {permit, ...observation});
    if (!value || value.ok !== true || Object.keys(value).length !== 1) throw new Error();
  } catch { throw new GatewayError("SHARED_BUDGET_UNAVAILABLE"); }
}

function accountSuspended(errors) {
  const access = Object.entries(errors).find(([key]) => key.toLowerCase() === "access")?.[1];
  return typeof access === "string" &&
    /\baccount\s+(?:(?:is|has been)\s+)?(?:(?:temporarily|permanently)\s+)?suspended\b/i.test(access);
}

function safeProviderErrors(errors) {
  const keys = Object.keys(errors).map(key => key.toLowerCase());
  if (keys.includes("plan") && String(errors.plan ?? "").toLowerCase().includes("season")) {
    return {plan: "season access denied"};
  }
  if (keys.some(key => ["requests", "ratelimit", "rate_limit", "rate limit"].includes(key))) {
    return {requests: "provider quota exhausted"};
  }
  if (keys.some(key => ["token", "key", "api_key"].includes(key))) {
    return {token: "provider authentication rejected"};
  }
  if (keys.includes("access")) return {access: accountSuspended(errors)
    ? "provider account suspended" : "provider access denied"};
  return {request: "provider rejected request"};
}

function errorDiagnostics(errors) {
  const known = ["plan", "requests", "ratelimit", "rate_limit", "rate limit", "token", "key", "api_key",
    "message", "access", "ip", "account", "subscription", "endpoint"];
  const words = JSON.stringify(errors).toLowerCase();
  return {fields: [...new Set(Object.keys(errors).map(key =>
      known.includes(key.toLowerCase()) ? key.toLowerCase() : "OTHER"))],
    mentions_ip_restriction: /whitelist|blacklist|ip address/.test(words),
    mentions_credential: /api.key|authentication|unauthorized|invalid.token/.test(words),
    mentions_quota: /quota|rate.limit|request.limit|too many requests/.test(words),
    mentions_subscription: /plan|subscription/.test(words),
    mentions_inactivity: /expired|inactive|activation|activate/.test(words),
    provider_account_state: accountSuspended(errors) ? "ACCOUNT_SUSPENDED" : "NOT_ESTABLISHED"};
}

Deno.serve(async req => {
  if (req.method !== "POST") return json({ok: false, error: "POST_REQUIRED"}, 405);
  const supplied = req.headers.get("x-sefirot-runner-token") ?? "";
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(supplied)) return json({ok: false, error: "UNAUTHORIZED"}, 401);
  const hash = await sha256(supplied);
  if (!DEPLOYED_AUTH.some(row => row.hash === hash &&
      (row.expires_at === null || Number.isFinite(row.expires_at) && Date.now() < row.expires_at))) {
    return json({ok: false, error: "UNAUTHORIZED"}, 401);
  }
  try {
    const job=req.headers.get('x-sefirot-source-job-id');
    const attempt=req.headers.get('x-sefirot-source-attempt');
    if((job!==null||attempt!==null)&&(!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(job??'')
        ||!/^[1-3]$/.test(attempt??'')||String(Number(attempt))!==attempt))
      throw new GatewayError('SOURCE_CONTEXT_INVALID');
    if(job!==null){const status=await serverRpc('sefirot_source_status',{});
      if(status.schema!=='football-source-store-v1'||status.ready!==true)throw new GatewayError('SOURCE_STORE_NOT_READY');}
    const body = parse(await readBounded(req, MAX_BODY));
    const endpoint = body?.endpoint;
    const params = body?.params ?? {};
    if (typeof endpoint !== "string" || !Object.hasOwn(ALLOWED, endpoint)) {
      return json({ok: false, error: "UNSUPPORTED_ENDPOINT"}, 400);
    }
    if (!params || typeof params !== "object" || Array.isArray(params) ||
        Object.keys(body).some(key => !["endpoint", "params"].includes(key))) {
      return json({ok: false, error: "INVALID_PARAMS"}, 400);
    }
    for (const [name, value] of Object.entries(params)) {
      if (!ALLOWED[endpoint].includes(name)) return json({ok: false, error: "UNSUPPORTED_PARAM"}, 400);
      if (!(typeof value === "string" && value.length <= 256 || Number.isSafeInteger(value))) {
        return json({ok: false, error: "INVALID_PARAM_VALUE"}, 400);
      }
    }
    if (!validNewParams(endpoint, params)) return json({ok: false, error: "INVALID_PARAMS"}, 400);
    if(job!==null) {
      const intent=await serverRpc('sefirot_source_begin',{p_job:job,p_attempt:Number(attempt),p_endpoint:endpoint,p_params:params});
      if(intent.authorized!==true)throw new GatewayError('SOURCE_DISPATCH_NOT_AUTHORIZED');
    }
    const secret = await apiKey();
    const budget = await reserveBudget();
    if (!budget.allowed) return json({ok: false, error: "SHARED_BUDGET_STOP",
      budget_reason: budget.reason}, 429);
    const observation = {outcome: "FAILURE", remaining_day: null, remaining_minute: null, observed_minute_limit: null};
    try {
    const startedAt=new Date().toISOString();
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) query.set(name, String(value));
    const url = "https://" + HOST + "/" + endpoint + (query.size ? "?" + query : "");
    const packet = await fetchBounded(url, {headers: {"x-apisports-key": secret,
      accept: "application/json"}}, MAX_RESPONSE);
    const receivedAt = new Date().toISOString();
    if (packet.response.status !== 200) return json({ok: false, error: "UPSTREAM_HTTP_ERROR",
      upstream_http_status: packet.response.status}, 502);
    const data = parse(packet.text);
    if (!data || typeof data !== "object" || Array.isArray(data) || !data.errors || !("response" in data)) {
      return json({ok: false, error: "MALFORMED_PROVIDER_RESPONSE"}, 502);
    }
    if (Object.keys(data.errors).length) return json({ok: false, error: "PROVIDER_REJECTED_REQUEST",
      provider_errors: safeProviderErrors(data.errors), diagnostics: errorDiagnostics(data.errors)}, 422);
    if (endpoint !== "status") {
      const objectResponse = OBJECT_RESPONSE_ENDPOINTS.has(endpoint);
      const validShape = objectResponse
        ? data.response && typeof data.response === "object" && !Array.isArray(data.response) &&
          Number.isSafeInteger(data.results) && data.results >= 0
        : Array.isArray(data.response) && data.results === data.response.length;
      if (!validShape || !Number.isSafeInteger(data.results) || data.paging?.current !== 1 ||
          ![0, 1].includes(data.paging?.total)) {
        return json({ok: false, error: "INCOMPLETE_PROVIDER_RESPONSE"}, 422);
      }
    }
    if (endpoint === "fixtures") checkFixtureEcho(data, params);
    if (endpoint === "status") {
      if (!data.response || typeof data.response !== "object" || Array.isArray(data.response)) {
        return json({ok: false, error: "MALFORMED_PROVIDER_RESPONSE"}, 502);
      }
      data.response = {subscription: data.response.subscription, requests: data.response.requests};
    }
    const quota = {};
    for (const name of QUOTA_HEADERS) {
      const value = packet.response.headers.get(name);
      if (value === null) continue;
      if (!/^[0-9]{1,12}$/.test(value)) throw new GatewayError("INVALID_QUOTA_HEADER");
      quota[name] = value;
    }
    // Missing/unknown quota may be returned as evidence but cannot authorize another call.
    const daily = quota["x-ratelimit-requests-remaining"];
    const minute = quota["x-ratelimit-remaining"];
    const dayLimit = quota["x-ratelimit-requests-limit"];
    const minuteLimit = quota["x-ratelimit-limit"];
    if (dayLimit !== undefined && minuteLimit !== undefined && daily !== undefined && minute !== undefined &&
        Number(dayLimit) >= 1 && Number(dayLimit) <= 1000000 &&
        Number(daily) <= Number(dayLimit) && Number(minuteLimit) >= 1 &&
        Number(minuteLimit) <= 300 && Number(minute) <= Number(minuteLimit) &&
        (endpoint !== "status" || data.response.subscription?.active === true)) {
      observation.outcome = "SUCCESS";
      observation.remaining_day = Number(daily);
      observation.remaining_minute = Number(minute);
      observation.observed_minute_limit = Number(minuteLimit);
    }
    let sourceArchive=null,sourceReceipt=null;
    if(job!==null) {
      if(!sourceSafe(data,endpoint))throw new GatewayError('SOURCE_UNSAFE');
      sourceReceipt={provider:'API_FOOTBALL_V3',provider_host:HOST,endpoint:'/'+endpoint,parameters:params,
        request_started_at:startedAt,received_at:receivedAt,upstream_received_at:receivedAt,
        payload_hash:await sha256(sourceCanonical(data)),http_status:200,sports_only:true,
        transport:'SUPABASE_GATEWAY',quota};
      const raw=sourceCanonical({data,receipt:sourceReceipt}),key=await sha256(raw);
      const stored=await serverRpc('sefirot_source_append',{p_raw:raw,p_hash:key,p_job:job,p_attempt:Number(attempt)});
      if(stored.stored!==true||stored.raw_sha256!==key)throw new GatewayError('SOURCE_APPEND_NOT_ACKNOWLEDGED');
      sourceArchive=stored;
    }
    return json({ok: true, provider: "API_FOOTBALL_V3", provider_host: HOST,
      endpoint: "/" + endpoint, params, received_at: receivedAt, data, quota,
      ...(sourceArchive?{source_archive:sourceArchive,source_archive_receipt:sourceReceipt}:{}),
      shared_budget_guard: "POSTGRES_RESERVATION_V1",
      sports_only: true, monetary_permission: false, execution_enabled: false});
    } catch(error) { observation.outcome='FAILURE'; throw error;
    } finally { await finishBudget(budget.permit, observation); }
  } catch (error) {
    return json({ok: false, error: error instanceof GatewayError ? error.code : "GATEWAY_UNAVAILABLE"}, 502);
  }
});

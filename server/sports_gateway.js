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
};
const QUOTA_HEADERS = ["x-requests-remaining", "x-requests-used", "x-requests-last",
  "x-ratelimit-requests-remaining", "x-ratelimit-requests-limit",
  "x-ratelimit-remaining", "x-ratelimit-limit"];

class GatewayError extends Error {
  constructor(code) { super(code); this.code = code; }
}

function json(data, status = 200) {
  return Response.json(data, {status, headers: {"cache-control": "no-store"}});
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

async function apiKey() {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !/^https:\/\/[a-z0-9]{20}\.supabase\.co\/?$/.test(url) || !key) {
    throw new GatewayError("SERVER_CONFIGURATION_UNAVAILABLE");
  }
  const result = await fetchBounded(url.replace(/\/$/, "") + "/rest/v1/rpc/sefirot_api_football_secret", {
    method: "POST", headers: {apikey: key, authorization: "Bearer " + key,
      "content-type": "application/json"}, body: "{}",
  }, MAX_BODY, 3000);
  if (result.response.status !== 200) throw new GatewayError("API_FOOTBALL_KEY_NOT_CONFIGURED");
  const value = parse(result.text);
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,256}$/.test(value.trim())) {
    throw new GatewayError("API_FOOTBALL_KEY_NOT_CONFIGURED");
  }
  return value.trim();
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
    const secret = await apiKey();
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
    if (endpoint !== "status" && (!Array.isArray(data.response) || !Number.isSafeInteger(data.results) ||
        data.results !== data.response.length || data.paging?.current !== 1 ||
        ![0, 1].includes(data.paging?.total))) {
      return json({ok: false, error: "INCOMPLETE_PROVIDER_RESPONSE"}, 422);
    }
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
    return json({ok: true, provider: "API_FOOTBALL_V3", provider_host: HOST,
      endpoint: "/" + endpoint, params, received_at: receivedAt, data, quota,
      sports_only: true, monetary_permission: false, execution_enabled: false});
  } catch (error) {
    return json({ok: false, error: error instanceof GatewayError ? error.code : "GATEWAY_UNAVAILABLE"}, 502);
  }
});

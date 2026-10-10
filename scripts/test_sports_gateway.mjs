/* Execute the deployed handler offline against hostile transport fixtures. */
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash, webcrypto} from "node:crypto";
import vm from "node:vm";

const source = readFileSync(new URL("../server/sports_gateway.js", import.meta.url), "utf8");
const marker = "const DEPLOYED_AUTH = []; // SEFIROT_DEPLOY_AUTH";
const token = "TEST_SESSION_TOKEN";
const hash = value => createHash("sha256").update(value).digest("hex");
const auth = [{hash: hash(token), expires_at: null}];
const fixtures = {get: "fixtures", parameters: {}, errors: [], results: 0,
  paging: {current: 1, total: 1}, response: []};
const status = {errors: [], response: {account: {email: "PRIVATE_ACCOUNT_VALUE"},
  subscription: {active: true}, requests: {current: 1, limit_day: 100}}};

function setup({upstream = Response.json(fixtures), authRows = auth, env = true, rpc = null} = {}) {
  const calls = [];
  let handler;
  const sandbox = {Request, Response, TextEncoder, TextDecoder, AbortController, URLSearchParams,
    setTimeout, clearTimeout, crypto: webcrypto,
    Deno: {env: {get: key => env ? ({SUPABASE_URL: "https://abcdefghijklmnopqrst.supabase.co",
      SUPABASE_SERVICE_ROLE_KEY: "PRIVATE_SERVICE_ROLE_KEY"})[key] : undefined},
      serve: value => { handler = value; }},
    fetch: async (url, options) => {
      calls.push({url, options});
      assert.equal(options.redirect, "error");
      assert.ok(options.signal instanceof AbortSignal);
      if (url.includes("/rpc/")) return rpc ?? Response.json("PRIVATE_API_KEY");
      if (upstream instanceof Error) throw upstream;
      return upstream;
    }};
  vm.runInNewContext(source.replace(marker, "const DEPLOYED_AUTH = " + JSON.stringify(authRows) + ";"), sandbox);
  return {calls, call: async ({body = {endpoint: "fixtures", params: {}},
      credential = token, method = "POST", queryToken = false} = {}) => {
    const req = new Request("https://gateway.test/" + (queryToken ? "?t=" + token : ""), {
      method, headers: credential === null ? {} : {"x-sefirot-runner-token": credential},
      ...(method === "POST" ? {body: typeof body === "string" ? body : JSON.stringify(body)} : {})});
    const response = await handler(req);
    return {status: response.status, body: await response.json()};
  }};
}

let tests = 0;
async function test(name, fn) {
  await fn(); tests += 1;
  process.stdout.write("ok " + name + "\n");
}

await test("unauthorized and query-token callers make no upstream request", async () => {
  for (const args of [{credential: null}, {credential: "wrong"}, {credential: null, queryToken: true}]) {
    const s = setup(); assert.equal((await s.call(args)).status, 401); assert.equal(s.calls.length, 0);
  }
});
await test("empty deployment and expired session reject before secret lookup", async () => {
  for (const authRows of [[], [{hash: hash(token), expires_at: Date.now() - 1000}]]) {
    const s = setup({authRows}); assert.equal((await s.call()).status, 401); assert.equal(s.calls.length, 0);
  }
});
await test("old credential remains valid beside a temporary session", async () => {
  const rows = [...auth, {hash: hash("OLD_CLIENT"), expires_at: null}];
  for (const credential of [token, "OLD_CLIENT"]) {
    const s = setup({authRows: rows}); assert.equal((await s.call({credential})).status, 200);
  }
});
await test("GET does not access provider or secrets", async () => {
  const s = setup(); assert.equal((await s.call({method: "GET"})).status, 405); assert.equal(s.calls.length, 0);
});
await test("odds, unknown paths and prototype names are rejected", async () => {
  for (const endpoint of ["odds", "live", "__proto__", "constructor", "https://evil.test"]) {
    const s = setup(); assert.equal((await s.call({body: {endpoint}})).status, 400); assert.equal(s.calls.length, 0);
  }
});
await test("unknown, boolean and composite parameters are rejected", async () => {
  for (const params of [{live: 1}, {league: true}, {league: []}, {league: {}}, [], {league: "x".repeat(257)}]) {
    const s = setup(); assert.equal((await s.call({body: {endpoint: "fixtures", params}})).status, 400);
    assert.equal(s.calls.length, 0);
  }
});
await test("oversized and malformed input make no provider request", async () => {
  for (const body of ["not_json PRIVATE_TOKEN", "x".repeat(16385)]) {
    const s = setup(); const out = await s.call({body}); assert.equal(out.body.ok, false);
    assert.equal(s.calls.length, 0); assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("fixed host and encoded parameters never send auth in the URL", async () => {
  const params = {league: 5, timezone: "Europe/Kyiv"};
  const s = setup({upstream: Response.json({...fixtures, parameters: params})});
  const out = await s.call({body: {endpoint: "fixtures", params}});
  assert.equal(out.status, 200); assert.equal(s.calls.length, 2);
  assert.equal(s.calls[1].url, "https://v3.football.api-sports.io/fixtures?league=5&timezone=Europe%2FKyiv");
  assert.equal(s.calls[1].options.headers["x-apisports-key"], "PRIVATE_API_KEY");
  assert.ok(!s.calls[1].url.includes("PRIVATE"));
  assert.ok(!JSON.stringify(out).includes("PRIVATE")); assert.equal(out.body.execution_enabled, false);
});
await test("fixture endpoint echo must match before successful response", async () => {
  for (const get of [undefined, "odds", "PRIVATE_TOKEN"]) {
    const s = setup({upstream: Response.json({...fixtures, get})}); const out = await s.call();
    assert.equal(out.status, 502); assert.equal(out.body.error, "ENDPOINT_ECHO_MISMATCH");
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("timezone fallback is rejected even for an empty provider packet", async () => {
  const params = {date: "2026-10-05", timezone: "Europe/Kyiv"};
  const s = setup({upstream: Response.json({...fixtures, parameters: {...params, timezone: "UTC"}})});
  const out = await s.call({body: {endpoint: "fixtures", params}});
  assert.equal(out.status, 502); assert.equal(out.body.error, "QUERY_ECHO_MISMATCH");
  assert.equal(s.calls.length, 2); assert.equal(out.body.data, undefined);
});
await test("fixture parameter keys and scalar values must match without private error text", async () => {
  for (const parameters of [null, [], {id: true}, {id: []}, {id: "PRIVATE_TOKEN"},
      {}, {id: "10", extra: "PRIVATE_TOKEN"}]) {
    const s = setup({upstream: Response.json({...fixtures, parameters})});
    const out = await s.call({body: {endpoint: "fixtures", params: {id: 10}}});
    assert.equal(out.body.error, "QUERY_ECHO_MISMATCH");
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("stringified fixture parameter echo is preserved without relabeling", async () => {
  const data = {...fixtures, parameters: {id: "10", timezone: "UTC"}};
  const s = setup({upstream: Response.json(data)});
  const out = await s.call({body: {endpoint: "fixtures", params: {id: 10, timezone: "UTC"}}});
  assert.equal(out.status, 200); assert.deepEqual(out.body.data, data);
  assert.deepEqual(out.body.params, {id: 10, timezone: "UTC"});
});
await test("status redacts account while preserving subscription and quota", async () => {
  const s = setup({upstream: Response.json(status)}); const out = await s.call({body: {endpoint: "status"}});
  assert.equal(out.status, 200); assert.deepEqual(out.body.data.response.requests, status.response.requests);
  assert.ok(!JSON.stringify(out).includes("PRIVATE_ACCOUNT_VALUE"));
});
await test("observed quota is preserved and malformed values fail closed", async () => {
  let s = setup({upstream: Response.json(fixtures, {headers: {"x-ratelimit-requests-remaining": "5"}})});
  assert.equal((await s.call()).body.quota["x-ratelimit-requests-remaining"], "5");
  s = setup({upstream: Response.json(fixtures, {headers: {
    "X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "10"}})});
  const minute = await s.call();
  assert.equal(minute.body.quota["x-ratelimit-remaining"], "0");
  assert.equal(minute.body.quota["x-ratelimit-limit"], "10");
  s = setup({upstream: Response.json(fixtures, {headers: {"x-ratelimit-requests-remaining": "-1 PRIVATE"}})});
  const out = await s.call(); assert.equal(out.status, 502); assert.equal(out.body.error, "INVALID_QUOTA_HEADER");
  s = setup({upstream: Response.json(fixtures, {headers: {"x-ratelimit-remaining": "PRIVATE"}})});
  assert.equal((await s.call()).body.error, "INVALID_QUOTA_HEADER");
});
await test("HTTP failure preserves code without upstream body", async () => {
  for (const code of [201, 302, 401, 403, 429]) {
    const s = setup({upstream: new Response("PRIVATE_API_KEY", {status: code})}); const out = await s.call();
    assert.equal(out.status, 502); assert.equal(out.body.upstream_http_status, code);
    assert.ok(!JSON.stringify(out).includes("PRIVATE_API_KEY"));
  }
});
await test("provider errors are classified without raw text", async () => {
  for (const [errors, expected] of [[{plan: "PRIVATE_TOKEN season blocked"}, "plan"],
      [{requests: "PRIVATE_TOKEN"}, "requests"], [{rateLimit: "PRIVATE_TOKEN"}, "requests"],
      [{token: "PRIVATE_TOKEN"}, "token"],
      [{access: "PRIVATE_TOKEN"}, "access"],
      [{unknown: "PRIVATE_TOKEN"}, "request"]]) {
    const s = setup({upstream: Response.json({...fixtures, errors})}); const out = await s.call();
    assert.equal(out.status, 422); assert.deepEqual(Object.keys(out.body.provider_errors), [expected]);
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("account suspension is explicit without copying private messages or negations", async () => {
  for (const [text, suspended] of [["Your account has been suspended. PRIVATE_TOKEN", true],
      ["Account temporarily suspended PRIVATE_TOKEN", true],
      ["Your account is not suspended PRIVATE_TOKEN", false],
      ["Account status unknown PRIVATE_TOKEN", false]]) {
    const s = setup({upstream: Response.json({...fixtures, errors: {access: text}})});
    const out = await s.call(); assert.equal(out.status, 422);
    assert.equal(out.body.diagnostics.provider_account_state, suspended ? "ACCOUNT_SUSPENDED" : "NOT_ESTABLISHED");
    assert.equal(out.body.provider_errors.access, suspended ? "provider account suspended" : "provider access denied");
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("incomplete and inconsistent fixture packets are rejected", async () => {
  for (const data of [{...fixtures, results: 1}, {...fixtures, paging: {current: 1, total: 2}},
      {...fixtures, paging: {current: true, total: 1}}, {...fixtures, response: {}}, {...fixtures, errors: null}]) {
    const s = setup({upstream: Response.json(data)}); assert.notEqual((await s.call()).status, 200);
  }
});
await test("diagnostics contain only fixed flags and allowed field labels", async () => {
  const s = setup({upstream: Response.json({...fixtures, errors: {
    PRIVATE_ACCOUNT_VALUE: "API key inactive on this subscription", message: "IP address whitelist"}})});
  const out = await s.call();
  assert.deepEqual(out.body.diagnostics.fields, ["OTHER", "message"]);
  assert.equal(out.body.diagnostics.mentions_ip_restriction, true);
  assert.equal(out.body.diagnostics.mentions_credential, true);
  assert.equal(out.body.diagnostics.mentions_inactivity, true);
  assert.ok(!JSON.stringify(out).includes("PRIVATE_ACCOUNT_VALUE"));
});
await test("oversized upstream stream is cancelled", async () => {
  let cancelled = false;
  const stream = new ReadableStream({start(c) {c.enqueue(new Uint8Array(2000001));}, cancel() {cancelled = true;}});
  const s = setup({upstream: new Response(stream)}); const out = await s.call();
  assert.equal(out.body.error, "RESPONSE_TOO_LARGE"); assert.equal(cancelled, true);
});
await test("network and timeout exceptions do not leak URLs or values", async () => {
  for (const name of ["TypeError", "AbortError"]) {
    const error = new Error("PRIVATE_API_KEY https://private.test"); error.name = name;
    const s = setup({upstream: error}); const out = await s.call();
    assert.equal(out.body.error, name === "AbortError" ? "UPSTREAM_TIMEOUT" : "UPSTREAM_UNAVAILABLE");
    assert.ok(!JSON.stringify(out).includes("PRIVATE"));
  }
});
await test("invalid UTF-8 and non-JSON are sanitized", async () => {
  for (const raw of [new Uint8Array([255]), "PRIVATE_TOKEN"]) {
    const s = setup({upstream: new Response(raw)}); assert.equal((await s.call()).body.error, "INVALID_JSON");
  }
});
await test("server configuration and secret lookup fail closed", async () => {
  let s = setup({env: false}); assert.equal((await s.call()).body.error, "SERVER_CONFIGURATION_UNAVAILABLE");
  assert.equal(s.calls.length, 0);
  s = setup({rpc: Response.json("bad key PRIVATE_TOKEN")});
  assert.equal((await s.call()).body.error, "API_FOOTBALL_KEY_NOT_CONFIGURED"); assert.equal(s.calls.length, 1);
});
process.stdout.write("GATEWAY_CONTRACTS_PASSED=" + tests + "\n");

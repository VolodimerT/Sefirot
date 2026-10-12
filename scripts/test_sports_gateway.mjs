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
const fixtures = {errors: [], results: 0, paging: {current: 1, total: 1}, response: []};
const status = {errors: [], response: {account: {email: "PRIVATE_ACCOUNT_VALUE"},
  subscription: {active: true}, requests: {current: 1, limit_day: 100}}};

function setup({upstream = Response.json(fixtures), authRows = auth, env = true, rpc = null, budget = null, finish = null} = {}) {
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
      if (url.endsWith("/sefirot_sports_budget_reserve")) return budget ?? Response.json({allowed: true,
        permit: "00000000-0000-0000-0000-000000000001"});
      if (url.endsWith("/sefirot_sports_budget_finish")) return finish ?? Response.json({ok: true});
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
  const s = setup(); const out = await s.call({body: {endpoint: "fixtures", params: {league: 5, timezone: "Europe/Kyiv"}}});
  assert.equal(out.status, 200); assert.equal(s.calls.length, 4);
  assert.equal(s.calls[2].url, "https://v3.football.api-sports.io/fixtures?league=5&timezone=Europe%2FKyiv");
  assert.equal(s.calls[2].options.headers["x-apisports-key"], "PRIVATE_API_KEY");
  assert.ok(!s.calls[2].url.includes("PRIVATE"));
  assert.ok(!JSON.stringify(out).includes("PRIVATE")); assert.equal(out.body.execution_enabled, false);
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
await test("shared budget refusals make zero provider calls", async () => {
  for (const reason of ["PAUSED", "BUSY", "UNFINISHED_ATTEMPT", "STALE_BUDGET", "DAILY_LIMIT", "MINUTE_LIMIT"]) {
    const s = setup({budget: Response.json({allowed: false, reason})});
    const out = await s.call();
    assert.equal(out.status, 429); assert.equal(out.body.budget_reason, reason);
    assert.equal(s.calls.length, 2); assert.ok(s.calls.every(c => c.url.includes("/rpc/")));
  }
});
await test("malformed or unavailable budget fails before provider IO", async () => {
  for (const budget of [Response.json({allowed: true}), Response.json({allowed: "true"}),
      Response.json({allowed: true, permit: "PRIVATE_TOKEN"}), Response.json(null),
      Response.json({allowed: true, permit: "00000000-0000-0000-0000-000000000001", extra: 1}),
      Response.json({allowed: false, reason: "PRIVATE_TOKEN"}), new Response("PRIVATE_TOKEN", {status: 503})]) {
    const s = setup({budget}); const out = await s.call();
    assert.equal(out.body.error, "SHARED_BUDGET_UNAVAILABLE"); assert.equal(s.calls.length, 2);
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});
await test("every uncertain upstream attempt opens the shared circuit without refund or retry", async () => {
  for (const upstream of [new Error("PRIVATE_TOKEN"), new Response("PRIVATE_TOKEN", {status: 429}),
      Response.json({...fixtures, errors: {access: "account suspended"}}),
      Response.json({...fixtures, results: 1}), new Response("not json")]) {
    const s = setup({upstream}); const out = await s.call(); assert.equal(out.body.ok, false);
    assert.equal(s.calls.length, 4);
    const final = JSON.parse(s.calls[3].options.body);
    assert.equal(final.outcome, "FAILURE"); assert.equal(final.remaining_day, null);
    assert.equal(final.remaining_minute, null);
    assert.ok(s.calls[1].url.endsWith("/sefirot_sports_budget_reserve"));
    assert.ok(s.calls[3].url.endsWith("/sefirot_sports_budget_finish"));
  }
});
await test("only observed numeric quota can keep the circuit active", async () => {
  for (const [headers, active, expected] of [[{}, true, "FAILURE"],
      [{"x-ratelimit-requests-remaining": "50", "x-ratelimit-remaining": "2",
        "x-ratelimit-requests-limit": "7500", "x-ratelimit-limit": "300"}, true, "SUCCESS"],
      [{"x-ratelimit-requests-remaining": "50", "x-ratelimit-remaining": "2",
        "x-ratelimit-requests-limit": "7500", "x-ratelimit-limit": "300"}, false, "FAILURE"],
      [{"x-ratelimit-requests-remaining": "1000001", "x-ratelimit-remaining": "2"}, true, "FAILURE"]]) {
    const data = {...status, response: {...status.response, subscription: {active}}};
    const s = setup({upstream: Response.json(data, {headers})});
    assert.equal((await s.call({body: {endpoint: "status"}})).status, 200);
    assert.equal(JSON.parse(s.calls[3].options.body).outcome, expected);
  }
});
await test("observed limit and counter contradictions cannot authorize another call", async () => {
  for (const [daily, dayLimit, minute, minuteLimit] of [["2", "1", "1", "300"],
      ["1", "7500", "2", "1"], ["1", "7500", "1", "0"], ["1", "7500", "1", "301"],
      ["1", "7500", "1", "1"]]) {
    const s = setup({upstream: Response.json(fixtures, {headers: {
      "x-ratelimit-requests-remaining": daily, "x-ratelimit-requests-limit": dayLimit,
      "x-ratelimit-remaining": minute, "x-ratelimit-limit": minuteLimit}})});
    assert.equal((await s.call()).status, 200);
    const observed = JSON.parse(s.calls[3].options.body);
    assert.equal(observed.outcome, minuteLimit === "1" && minute === "1" ? "SUCCESS" : "FAILURE");
    if (observed.outcome === "SUCCESS") assert.equal(observed.observed_minute_limit, 1);
  }
});
await test("failed finalization returns fixed error and makes no retry", async () => {
  for (const finish of [Response.json({ok: false}), new Response("PRIVATE_TOKEN", {status: 503}),
      Response.json({ok: true, extra: "PRIVATE_TOKEN"})]) {
    const s = setup({finish}); const out = await s.call();
    assert.equal(out.body.error, "SHARED_BUDGET_UNAVAILABLE"); assert.equal(s.calls.length, 4);
    assert.ok(!JSON.stringify(out).includes("PRIVATE_TOKEN"));
  }
});

const enrichment = [
  ["standings", {league: 39, season: 2026}],
  ["teams/statistics", {league: 39, season: 2026, team: 101, date: "2026-10-12"}],
  ["fixtures/headtohead", {h2h: "101-202", last: 5}],
  ["fixtures/events", {fixture: 50001}], ["fixtures/players", {fixture: 50001}],
  ["coachs", {team: 101}], ["players/squads", {team: 101}],
  ...["players/topscorers", "players/topassists", "players/topyellowcards", "players/topredcards"]
    .map(endpoint => [endpoint, {league: 39, season: 2026}]),
];
const validQuota = {"x-ratelimit-requests-remaining": "90", "x-ratelimit-requests-limit": "100",
  "x-ratelimit-remaining": "10", "x-ratelimit-limit": "300"};
function dataFor(endpoint) {
  return {...fixtures, ...(endpoint === "teams/statistics" ? {response: {team: {id: 101}}, results: 11} : {})};
}
await test("all enrichment endpoints preserve the shared reservation and finish order", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({upstream: Response.json(dataFor(endpoint), {headers: validQuota})});
    const out = await s.call({body: {endpoint, params}});
    assert.equal(out.status, 200); assert.equal(s.calls.length, 4);
    assert.ok(s.calls[0].url.endsWith("/sefirot_api_football_secret"));
    assert.ok(s.calls[1].url.endsWith("/sefirot_sports_budget_reserve"));
    assert.ok(s.calls[2].url.startsWith("https://v3.football.api-sports.io/" + endpoint + "?"));
    assert.ok(s.calls[3].url.endsWith("/sefirot_sports_budget_finish"));
    assert.equal(out.body.monetary_permission, false); assert.equal(out.body.execution_enabled, false);
  }
});
await test("every budget refusal protects every enrichment endpoint", async () => {
  for (const [endpoint, params] of enrichment) {
    for (const reason of ["PAUSED", "BUSY", "UNFINISHED_ATTEMPT", "STALE_BUDGET", "DAILY_LIMIT", "MINUTE_LIMIT"]) {
      const s = setup({budget: Response.json({allowed: false, reason})});
      const out = await s.call({body: {endpoint, params}});
      assert.equal(out.status, 429); assert.equal(out.body.budget_reason, reason);
      assert.equal(s.calls.length, 2); assert.ok(s.calls.every(c => c.url.includes("/rpc/")));
    }
  }
});
await test("malformed shared permits block enrichment before provider IO", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({budget: Response.json({allowed: true, permit: "PRIVATE_PERMIT"})});
    const out = await s.call({body: {endpoint, params}});
    assert.equal(out.body.error, "SHARED_BUDGET_UNAVAILABLE"); assert.equal(s.calls.length, 2);
    assert.ok(!JSON.stringify(out).includes("PRIVATE_PERMIT"));
  }
});
await test("known valid quota completes each enrichment reservation successfully", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({upstream: Response.json(dataFor(endpoint), {headers: validQuota})});
    assert.equal((await s.call({body: {endpoint, params}})).status, 200);
    const finish = JSON.parse(s.calls[3].options.body);
    assert.equal(finish.outcome, "SUCCESS"); assert.equal(finish.remaining_day, 90);
    assert.equal(finish.remaining_minute, 10); assert.equal(finish.observed_minute_limit, 300);
  }
});
await test("unknown quota latches FAILURE for every enrichment endpoint", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({upstream: Response.json(dataFor(endpoint))});
    assert.equal((await s.call({body: {endpoint, params}})).status, 200);
    const finish = JSON.parse(s.calls[3].options.body);
    assert.equal(finish.outcome, "FAILURE"); assert.equal(finish.remaining_day, null);
    assert.equal(finish.remaining_minute, null);
  }
});
await test("enrichment provider failures are finalized once with sanitized errors", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({upstream: new Error("PRIVATE_ACCOUNT_OR_URL")});
    const out = await s.call({body: {endpoint, params}});
    assert.equal(out.body.error, "UPSTREAM_UNAVAILABLE"); assert.equal(s.calls.length, 4);
    assert.equal(JSON.parse(s.calls[3].options.body).outcome, "FAILURE");
    assert.ok(!JSON.stringify(out).includes("PRIVATE_ACCOUNT_OR_URL"));
  }
});
await test("failed enrichment finalization cannot return successful evidence or retry", async () => {
  for (const [endpoint, params] of enrichment) {
    const s = setup({upstream: Response.json(dataFor(endpoint), {headers: validQuota}),
      finish: Response.json({ok: false})});
    const out = await s.call({body: {endpoint, params}});
    assert.equal(out.body.error, "SHARED_BUDGET_UNAVAILABLE"); assert.equal(s.calls.length, 4);
  }
});
await test("new required selectors are enforced without budget or provider IO", async () => {
  for (const [endpoint, params] of [["standings", {}], ["teams/statistics", {team: 101}],
      ["fixtures/headtohead", {h2h: "101-101"}], ["fixtures/events", {}],
      ["fixtures/players", {fixture: 0}], ["coachs", {}], ["players/squads", {}],
      ["players/topscorers", {league: 39, season: true}]]) {
    const s = setup(); assert.equal((await s.call({body: {endpoint, params}})).status, 400);
    assert.equal(s.calls.length, 0);
  }
});
await test("legitimate team statistics object shape is distinct from arrays", async () => {
  for (const [response, expected] of [[{team: {id: 101}}, 200], [[], 422], [null, 422]]) {
    const s = setup({upstream: Response.json({...fixtures, response, results: 11}, {headers: validQuota})});
    assert.equal((await s.call({body: {endpoint: "teams/statistics", params: enrichment[1][1]}})).status, expected);
    assert.equal(JSON.parse(s.calls[3].options.body).outcome, expected === 200 ? "SUCCESS" : "FAILURE");
  }
});
await test("invalid dates and oversized new history selectors never consume quota", async () => {
  for (const [endpoint, params] of [["teams/statistics", {...enrichment[1][1], date: "2026-02-30"}],
      ["teams/statistics", {...enrichment[1][1], date: "2026-19-39"}],
      ["fixtures/headtohead", {h2h: "101-202", last: 51}]]) {
    const s = setup(); assert.equal((await s.call({body: {endpoint, params}})).status, 400);
    assert.equal(s.calls.length, 0);
  }
});
await test("partial pages and bool results cannot become enrichment observations", async () => {
  for (const [endpoint, params] of enrichment) {
    for (const malformed of [{paging: {current: 2, total: 1}}, {paging: {current: 1, total: true}},
        {results: true}]) {
      const s = setup({upstream: Response.json({...dataFor(endpoint), ...malformed}, {headers: validQuota})});
      const out = await s.call({body: {endpoint, params}});
      assert.equal(out.status, 422); assert.equal(s.calls.length, 4);
      assert.equal(JSON.parse(s.calls[3].options.body).outcome, "FAILURE");
    }
  }
});
await test("shared guard marker is issued only on successfully finalized legacy and new replies", async () => {
  for (const [endpoint, params] of [["fixtures", {id: 50001}], ...enrichment]) {
    const s = setup({upstream: Response.json(dataFor(endpoint), {headers: validQuota})});
    const out = await s.call({body: {endpoint, params}});
    assert.equal(out.body.shared_budget_guard, "POSTGRES_RESERVATION_V1");
    assert.equal(s.calls.length, 4);
  }
});

process.stdout.write("GATEWAY_CONTRACTS_PASSED=" + tests + "\n");

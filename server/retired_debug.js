/* The legacy fixed-date debug route performs no provider requests. */
Deno.serve(() => Response.json({ok: false, error: "RETIRED_USE_SPORTS_GATEWAY"},
  {status: 410, headers: {"cache-control": "no-store"}}));

// Adapter for the HTTP test. Production runs autonomous/index.js directly.
const now = Date.parse('2026-12-01T17:00:00Z');
Date.now = () => now;
const serve = Deno.serve.bind(Deno);
Deno.serve = handler => serve({ hostname:'127.0.0.1', port:0, onListen:({port})=>console.log('DQ_PORT='+port) }, handler);
const fetchNetwork = globalThis.fetch.bind(globalThis);
globalThis.fetch = async (url, options) => {
  if (typeof url !== 'string' || !url.startsWith('https://football-data.co.uk/')) {
    return fetchNetwork(url,options);
  }
  const output = await fetchNetwork(Deno.env.get('DQ_QA_REST') + '/source' + new URL(url).pathname,options);
  Object.defineProperty(output,'url',{value:url});
  return output;
};
await import('../index.js');

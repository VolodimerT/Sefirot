// IPC barrier keeps process startup outside the measured interval.
import {pathToFileURL} from 'node:url';
const {execute} = await import(pathToFileURL(process.argv[2] + '/run.js'));
const endpoint = process.argv[3];
process.once('message', async stamp => {
  try {
    const rest = async (path, options) => {
      const response = await fetch(endpoint + '/rest/' + path, {...options,
        signal:process.argv[4]==='timeout' && !options ? AbortSignal.timeout(50) : AbortSignal.timeout(60000)});
      if (!response.ok) throw Error(await response.text());
      return response.json();
    };
    const csv = async url => {
      const response = await fetch(endpoint + '/csv' + new URL(url).pathname);
      if (!response.ok) throw Error('CSV_HTTP_' + response.status);
      return response.text();
    };
    const result = await execute({rest, csv, clock: () => Date.parse(stamp)});
    process.send({result, rssKiB:process.resourceUsage().maxRSS});
  } catch (error) { process.send({error:error.message}); }
  process.disconnect();
});
process.send('ready');

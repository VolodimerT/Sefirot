// IPC barrier keeps process startup outside the measured interval.
import {pathToFileURL} from 'node:url';
const {execute} = await import(pathToFileURL(process.argv[2] + '/run.js'));
const endpoint = process.argv[3];
process.once('message', async stamp => {
  const profile=process.argv[4]==='profile'?{stringify:0,http:0,upload:0,download:0}:null;
  const stringify=JSON.stringify;
  if(profile)JSON.stringify=(...args)=>{
    const start=performance.now();
    try{return stringify(...args);}finally{profile.stringify+=performance.now()-start;}
  };
  try {
    const rest = async (path, options) => {
      const start=performance.now();
      const response = await fetch(endpoint + '/rest/' + path, {...options,
        signal:process.argv[4]==='timeout' && !options ? AbortSignal.timeout(50) : AbortSignal.timeout(60000)});
      if (!response.ok) throw Error(await response.text());
      if(!profile)return response.json();
      const bytes=await response.arrayBuffer();
      profile.http+=performance.now()-start;
      profile.upload+=Buffer.byteLength(options?.body??'');
      profile.download+=bytes.byteLength;
      return JSON.parse(new TextDecoder().decode(bytes));
    };
    const csv = async url => {
      const response = await fetch(endpoint + '/csv' + new URL(url).pathname);
      if (!response.ok) throw Error('CSV_HTTP_' + response.status);
      return response.text();
    };
    const result = await execute({rest, csv, clock: () => Date.parse(stamp),
      retryUntil:process.argv[5]==='scheduled'?Date.parse(stamp)+600000:null});
    JSON.stringify=stringify;
    process.send({result, profile, rssKiB:process.resourceUsage().maxRSS});
  } catch (error) { process.send({error:error.message}); }
  process.disconnect();
});
process.send('ready');

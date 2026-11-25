import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { executeDaily, executeReplay, modes } from './paper-runner.js';
import { paperSources } from './paper-sources.js';

const [mode, date, input, output]=process.argv.slice(2);
if(!output)throw Error('Usage: paper-cli.mjs MODE DATE INPUT OUTPUT');
const raw=await readFile(input,'utf8');
const decoded=JSON.parse(raw);
const sources=paperSources();
let result;
if(mode===modes.daily) {
  result=await executeDaily({date,calendar:decoded,sources,oddsKey:process.env.DQ_ODDS_API_FREE_KEY??'',
    reserveOddsKey:process.env.DQ_ODDSBUNCH_FREE_KEY??'',
    contextGateway:{project:process.env.SUPABASE_URL,token:process.env.DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN}});
}else if(mode===modes.replay) {
  const cutoff=Date.parse(date);
  if(!date.endsWith('Z')||cutoff>Date.now())throw Error('Historical cutoff must be UTC and no later than now');
  result=await executeReplay({competitions:decoded,sources,cutoff});
}else{
  throw Error('December Quest uses the existing production executor');
}
const sealedAt=new Date().toISOString();
if(mode===modes.daily&&result.fixtures.some(f=>Date.parse(f.kickoff)<=Date.parse(sealedAt)))throw Error('PAPER_SEAL_AFTER_KICKOFF');
const record={...result,sealed_at:sealedAt,input_sha256:createHash('sha256').update(raw).digest('hex')};
const digest=createHash('sha256').update(JSON.stringify(record)).digest('hex');
await writeFile(output,JSON.stringify({...record,sha256:digest},null,2)+'\n',{flag:'wx',mode:0o600});
console.log(JSON.stringify({mode,verdict:result.verdict,seal:sealedAt,sha256:digest,fixtures:result.fixtures?.length,
  predictions:result.fixtures?.filter(row=>row.forecast).length,verified_odds:result.fixtures?.filter(row=>row.forecast?.evidence?.quote_price_verified).length}));

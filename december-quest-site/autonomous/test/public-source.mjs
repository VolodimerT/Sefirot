import Core from '../core.js';
import { fetchCsvWithRetry } from '../csv-source.js';

const origin = 'https://football-data.co.uk';
const leagues = Object.entries(Core.LEAGUE_FILES);
const files = leagues.flatMap(([league,code])=>['2627','2526'].map(year=>({
  league, year, url:origin + '/mmz4281/' + year + '/' + code + '.csv'
})));
files.push({league:'weekly',url:origin + '/fixtures.csv'});
const cutoff = Date.now();
const results = await Promise.all(files.map(async file=>{
  try {
    const csv = await fetchCsvWithRetry(file.url);
    const rows = file.league==='weekly' ? Core.parseCsv(csv) : Core.resultsFromCsv(csv,file.league,cutoff);
    if (!rows.length) throw Error('VALID_ROWS_MISSING');
    return {league:file.league,year:file.year,status:'OK',rows:rows.length};
  } catch(error) {
    return {league:file.league,year:file.year,status:'ERROR',detail:error.message};
  }
}));
const ok = results.filter(row=>row.status==='OK').length;
console.log(JSON.stringify({source:origin,csv_ok:ok,csv_attempted:files.length,results}));
if (ok!==files.length) Deno.exit(1);

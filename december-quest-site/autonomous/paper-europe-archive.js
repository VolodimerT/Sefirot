import { europeTeam } from './paper-europe.js';

const month=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const titles={UCL:'Champions League',UEL:'Europa League',UECL:'Conference League'};
const dateLine=/^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Z][a-z]{2}) (\d{1,2})(?: (\d{4}))?\s*$/;
const round=/^▪\s*(?:(?:[1-4]\. Round|Round [1-4])\b|Play[ -]?offs?)/i;
const phase=/^▪\s*League(?: phase|,\s*Matchday \d+)/i;
const match=/^\s*(?:\d\d:\d\d\s+)?(.+?)\s+\(([A-Z]{3})\)\s+v\s+(.+?)\s+\(([A-Z]{3})\)\s+(\d{1,2})-(\d{1,2})(?:\s+\(\d{1,2}-\d{1,2}\))?\s*$/;

export function readEuropeArchive(text,tournament,season,qualifying,cutoff){
  const edition=season+'/'+String(season+1).slice(-2), competition=tournament+(qualifying?'_QUAL':'');
  const heading='= UEFA '+titles[tournament]+(qualifying?' - Quali ':' ')+edition;
  if(typeof text!=='string'||text.length>1000000||text.split(/\r?\n/,1)[0].trim()!==heading)
    throw Error('ARCHIVE_COMPETITION_MISMATCH');
  const end=new Date(cutoff).toISOString().slice(0,10), seen=new Set(), rows=[];
  let allowed=false,date=null,when=0;
  for(const line of text.split(/\r?\n/)){
    if(line.startsWith('▪')){allowed=(qualifying?round:phase).test(line);date=null;continue;}
    if(!allowed)continue;
    const m=line.match(dateLine);
    if(m){
      const mm=month.indexOf(m[1]),dd=Number(m[2]),y=mm>=6?season:season+1;
      when=Date.UTC(y,mm,dd,12);
      date=mm>=0&&(!m[3]||Number(m[3])===y)&&new Date(when).getUTCDate()===dd
        ?new Date(when).toISOString().slice(0,10):null;
      continue;
    }
    if(!date||date>=end||when>=cutoff)continue;
    const card=line.match(match);
    if(!card)continue; // extra-time, penalties and records with ambiguous scores are excluded
    const home=europeTeam(card[1]),away=europeTeam(card[3]),hg=Number(card[5]),ag=Number(card[6]);
    const id=[date,home,away].join('|');
    if(!home||!away||home===away||hg>12||ag>12||seen.has(id))throw Error('ARCHIVE_RESULT_INVARIANT');
    seen.add(id);
    rows.push({competition,season,home,away,hg,ag,date,when,homeCountry:card[2]==='MCO'?'FRA':card[2],
      awayCountry:card[4]==='MCO'?'FRA':card[4]});
  }
  return rows;
}

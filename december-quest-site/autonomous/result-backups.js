import Core from './core.js';

const root = 'https://raw.githubusercontent.com/openfootball/football.json/master/';
const dayMs = 86400000;
const ligaUrl = 'https://api.openligadb.de/getmatchdata/bl1/';
const seasons = {'2627':['2026-27','2026/27',2026],'2526':['2025-26','2025/26',2025]};
const leagues = {
  EPL:['en.1','English Premier League'],
  LALIGA:['es.1','Spain Primera División'],
  SERIEA:['it.1','Italian Serie A'],
  BUNDES:['de.1','Deutsche Bundesliga'],
  LIGUE1:['fr.1','French Ligue 1']
};

// Provider-specific names checked against the two season files and Football-Data.
const teams = {
  EPL:{
    'AFC Bournemouth':'Bournemouth','Arsenal FC':'Arsenal','Aston Villa FC':'Aston Villa',
    'Brentford FC':'Brentford','Brighton & Hove Albion FC':'Brighton','Burnley FC':'Burnley','Chelsea FC':'Chelsea',
    'Coventry City FC':'Coventry','Crystal Palace FC':'Crystal Palace','Everton FC':'Everton','Fulham FC':'Fulham',
    'Hull City AFC':'Hull','Ipswich Town FC':'Ipswich','Leeds United FC':'Leeds','Liverpool FC':'Liverpool',
    'Manchester City FC':'Man City','Manchester United FC':'Man United','Newcastle United FC':'Newcastle',
    'Nottingham Forest FC':"Nott'm Forest",'Sunderland AFC':'Sunderland','Tottenham Hotspur FC':'Tottenham',
    'West Ham United FC':'West Ham','Wolverhampton Wanderers FC':'Wolves'
  },
  LALIGA:{
    'Athletic Club':'Ath Bilbao','CA Osasuna':'Osasuna','Club Atlético de Madrid':'Ath Madrid','Deportivo Alavés':'Alaves',
    'Elche CF':'Elche','FC Barcelona':'Barcelona','Getafe CF':'Getafe','Girona FC':'Girona','Levante UD':'Levante',
    'Málaga CF':'Malaga','RC Celta de Vigo':'Celta','RC Deportivo La Coruña':'La Coruna','RCD Espanyol de Barcelona':'Espanol',
    'RCD Mallorca':'Mallorca','Rayo Vallecano de Madrid':'Vallecano','Real Betis Balompié':'Betis','Real Madrid CF':'Real Madrid',
    'Real Oviedo':'Oviedo','Real Racing Club de Santander':'Santander','Real Sociedad de Fútbol':'Sociedad',
    'Sevilla FC':'Sevilla','Valencia CF':'Valencia','Villarreal CF':'Villarreal'
  },
  SERIEA:{
    'AC Milan':'Milan','AC Monza':'Monza','AC Pisa 1909':'Pisa','ACF Fiorentina':'Fiorentina','AS Roma':'Roma',
    'Atalanta BC':'Atalanta','Bologna FC 1909':'Bologna','Cagliari Calcio':'Cagliari','Como 1907':'Como',
    'FC Internazionale Milano':'Inter','Frosinone Calcio':'Frosinone','Genoa CFC':'Genoa','Hellas Verona FC':'Verona',
    'Juventus FC':'Juventus','Parma Calcio 1913':'Parma','SS Lazio':'Lazio','SSC Napoli':'Napoli','Torino FC':'Torino',
    'US Cremonese':'Cremonese','US Lecce':'Lecce','US Sassuolo Calcio':'Sassuolo','Udinese Calcio':'Udinese','Venezia FC':'Venezia'
  },
  BUNDES:{
    '1. FC Heidenheim 1846':'Heidenheim','1. FC Köln':'FC Koln','1. FC Union Berlin':'Union Berlin','1. FSV Mainz 05':'Mainz',
    'Bayer 04 Leverkusen':'Leverkusen','Borussia Dortmund':'Dortmund','Borussia Mönchengladbach':"M'gladbach",
    'Eintracht Frankfurt':'Ein Frankfurt','FC Augsburg':'Augsburg','FC Bayern München':'Bayern Munich','FC Schalke 04':'Schalke 04',
    'FC St. Pauli 1910':'St Pauli','Hamburger SV':'Hamburg','RB Leipzig':'RB Leipzig','SC Freiburg':'Freiburg',
    'SC Paderborn 07':'Paderborn','SV 07 Elversberg':'Elversberg','SV Werder Bremen':'Werder Bremen',
    'TSG 1899 Hoffenheim':'Hoffenheim','VfB Stuttgart':'Stuttgart','VfL Wolfsburg':'Wolfsburg'
  },
  LIGUE1:{
    'AJ Auxerre':'Auxerre','AS Monaco FC':'Monaco','Angers SCO':'Angers','ES Troyes AC':'Troyes','FC Lorient':'Lorient',
    'FC Metz':'Metz','FC Nantes':'Nantes','Le Havre AC':'Le Havre','Le Mans FC':'Le Mans','Lille OSC':'Lille',
    'OGC Nice':'Nice','Olympique Lyonnais':'Lyon','Olympique de Marseille':'Marseille','Paris FC':'Paris FC',
    'Paris Saint-Germain FC':'Paris SG','RC Strasbourg Alsace':'Strasbourg','Racing Club de Lens':'Lens',
    'Stade Brestois 29':'Brest','Stade Rennais FC 1901':'Rennes','Toulouse FC':'Toulouse'
  }
};

export const resultKey = row => [row.date,row.home,row.away].join('|');
const time = game => typeof game?.date==='string' && /^\d{4}-\d{2}-\d{2}$/.test(game.date)
  ? Date.parse(game.date+'T12:00:00Z') : NaN;
const scoreEqual = (a,b) => a.hg===b.hg&&a.ag===b.ag;
const cache = new Map();

export function openFootballUrl(code, season) {
  return root+seasons[season][0]+'/'+leagues[code][0]+'.json';
}

export function parseOpenFootball(payload, code, season, cutoff) {
  const [,yearLabel,year] = seasons[season];
  if (payload?.name!==leagues[code][1]+' '+yearLabel || !Array.isArray(payload.matches) || payload.matches.length>500) {
    throw Error('INVALID_LEAGUE_OR_SEASON');
  }
  const cutoffDay=new Date(cutoff).toISOString().slice(0,10);
  const first=year+'-07-01', last=(year+1)+'-07-01', found=new Map();
  for (const game of payload.matches) {
    const when=time(game);
    if (!Number.isFinite(when)||new Date(when).toISOString().slice(0,10)!==game.date||
      game.date<first||game.date>=last||game.date>=cutoffDay||when>=cutoff) continue;
    const score=Array.isArray(game.score)?game.score:game.score?.ft;
    if (!Array.isArray(score)||score.length!==2||score.some(n=>!Number.isInteger(n)||n<0||n>12)) continue;
    const aliases=teams[code];
    if (!Object.hasOwn(aliases,game.team1)||!Object.hasOwn(aliases,game.team2)) throw Error('UNMAPPED_TEAM');
    const home=Core.canonical(code,aliases[game.team1]),away=Core.canonical(code,aliases[game.team2]);
    if(home===away)throw Error('INVALID_TEAMS');
    const [hg,ag]=score;
    const row={home,away,hg,ag,date:game.date,when,season,kickoff:null};
    const key=resultKey(row);
    if(found.has(key)&&!scoreEqual(found.get(key),row))throw Error('CONFLICTING_RESULTS');
    if(!found.has(key))found.set(key,row);
  }
  if (!found.size) throw Error('EMPTY_RESULT_SOURCE');
  return [...found.values()];
}

export function parseOpenLigaDB(games, season, cutoff) {
  if(!Array.isArray(games)||games.length<1||games.length>306)throw Error('INVALID_LEAGUE_OR_SEASON');
  const [, ,year]=seasons[season];
  const cutoffDay=new Date(cutoff).toISOString().slice(0,10), results=new Map(), ids=new Set();
  for(const game of games){
    if(game.leagueShortcut!=='bl1'||String(game.leagueSeason)!==String(year)||
      !Number.isSafeInteger(game.matchID)||ids.has(game.matchID))throw Error('INVALID_LEAGUE_OR_SEASON');
    ids.add(game.matchID);
    if(game.matchIsFinished!==true||typeof game.matchDateTimeUTC!=='string'||!game.matchDateTimeUTC.endsWith('Z'))continue;
    const kickoff=Date.parse(game.matchDateTimeUTC);
    if(!Number.isFinite(kickoff)||kickoff>=cutoff-3*3600000)continue;
    const date=new Date(kickoff).toISOString().slice(0,10);
    if(date>=cutoffDay||date<year+'-07-01'||date>=(year+1)+'-07-01')continue;
    const grades=(game.matchResults||[]).filter(result=>result.resultTypeKind==='After90Minutes');
    if(grades.length!==1)continue;
    const {pointsTeam1:hg,pointsTeam2:ag}=grades[0];
    if([hg,ag].some(n=>!Number.isInteger(n)||n<0||n>12))continue;
    const name=team=>({'FC St. Pauli':'FC St. Pauli 1910','TSG Hoffenheim':'TSG 1899 Hoffenheim'})[team?.teamName]||team?.teamName;
    const homeName=name(game.team1),awayName=name(game.team2);
    if(!Object.hasOwn(teams.BUNDES,homeName)||!Object.hasOwn(teams.BUNDES,awayName))throw Error('UNMAPPED_TEAM');
    const home=Core.canonical('BUNDES',teams.BUNDES[homeName]),away=Core.canonical('BUNDES',teams.BUNDES[awayName]);
    if(home===away)throw Error('INVALID_TEAMS');
    const row={home,away,hg,ag,date,when:Date.parse(date+'T12:00:00Z'),season,kickoff};
    const key=resultKey(row);
    if(results.has(key))throw Error('CONFLICTING_RESULTS');
    results.set(key,row);
  }
  if(!results.size)throw Error('EMPTY_RESULT_SOURCE');
  return [...results.values()];
}

export function backupStatus(pack, primary, cutoff) {
  if(!pack?.ok||!Number.isFinite(pack.observedAt)||pack.observedAt>cutoff||cutoff-pack.observedAt>15*60000) return 'UNAVAILABLE';
  const rows=pack.rows;
  if(pack.season==='2627'){
    if(!rows.some(row=>cutoff-row.when<=8*dayMs))return 'STALE';
    if(rows.length<24||rows.length<0.9*pack.expectedGames)return 'INCOMPLETE_CURRENT_SEASON';
  }
  if(pack.season==='2526'&&rows.length<(pack.code==='BUNDES'||pack.code==='LIGUE1'?304:378))return 'INCOMPLETE_ARCHIVE';
  const reference=new Map(primary.map(row=>[resultKey(row),row]));
  return rows.some(row=>reference.has(resultKey(row))&&!scoreEqual(reference.get(resultKey(row)),row))
    ? 'CONFLICT' : 'FALLBACK';
}

async function fetchPack(code,season,url,parser,cutoff,fetcher,clock) {
  let cached=cache.get(url);
  try {
    const stamp=clock();
    const useCache=cached&&cached.observedAt<=stamp&&stamp-cached.observedAt<=5*60000;
    if(!useCache){
      const response=await fetcher(url,{redirect:'error',headers:{Accept:'application/json'},signal:AbortSignal.timeout(6000)});
      if(!response.ok)throw Error('HTTP_'+response.status);
      if(Number(response.headers.get('content-length'))>1000000)throw Error('RESPONSE_TOO_LARGE');
      const content=await response.text();
      if(content.length>1000000)throw Error('RESPONSE_TOO_LARGE');
      cached={payload:JSON.parse(content),observedAt:clock()};
    }
    const rows=parser(cached.payload,code,season,cutoff);
    const games=Array.isArray(cached.payload)?cached.payload:cached.payload.matches;
    const cutoffDay=new Date(cutoff).toISOString().slice(0,10);
    const expectedGames=games.filter(game=>{
      const date=game.date??game.matchDateTimeUTC?.slice(0,10);
      return typeof date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(date)&&date<cutoffDay;
    }).length;
    cache.set(url,cached);
    return {code,season,url,ok:true,rows,expectedGames,observedAt:cached.observedAt,cached:Boolean(useCache)};
  } catch(error) {
    const known=['INVALID_LEAGUE_OR_SEASON','UNMAPPED_TEAM','INVALID_TEAMS','CONFLICTING_RESULTS','EMPTY_RESULT_SOURCE','RESPONSE_TOO_LARGE'];
    const reason=known.includes(error.message)||/^HTTP_\d{3}$/.test(error.message)?error.message:'FETCH_OR_FORMAT_ERROR';
    return {code,season,url,ok:false,error:reason};
  }
}

export function fetchResultBackup(code,season,cutoff,fetcher=fetch,clock=Date.now){
  if(code==='BUNDES'&&season==='2627'){
    return fetchPack(code,season,ligaUrl+seasons[season][2],
      (payload,_code,season,cutoff)=>parseOpenLigaDB(payload,season,cutoff),cutoff,fetcher,clock);
  }
  return fetchPack(code,season,openFootballUrl(code,season),parseOpenFootball,cutoff,fetcher,clock);
}

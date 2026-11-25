import Core from './core.js';
import { modelMarkets } from './markets.js';
import { leagueWalkForward, paperPolicy } from './paper-validation.js';

export const europeVersion='DQ-EUROPE-ELO-0.1';
const groups={
  ENG:'Aston Villa|FC Arsenal|FC Liverpool|Chelsea FC|Manchester City|Manchester United FC|Newcastle United FC|Tottenham Hotspur|Tottenham Hotspur FC|AFC Bournemouth|Crystal Palace FC|Sunderland AFC|Brighton & Hove Albion F.C.',
  ESP:'Atletico Madrid|FC Barcelona|FC Girona|FC Villareal|Villarreal CF|Real Madrid|Real Betis|Celta Vigo|Real Sociedad|FC Getafe',
  GER:'Bayer 04 Leverkusen|Borussia Dortmund|FC Bayern München|Eintracht Frankfurt|RB Leipzig|VfB Stuttgart|TSG Hoffenheim|SC Freiburg',
  ITA:'AC Mailand|AC Milan|Atalanta Bergamo|FC Bologna|Como 1907|Inter Mailand|Juventus Turin|SSC Neapel|SSC Napoli|AS Rom|Lazio Rom',
  FRA:'AS Monaco|OSC Lille|Lille OSC|Olympique Marseille|Paris Saint-Germain|Paris St. Germain|RC Lens|Stade Brest|Olympique Lyon|Stade Rennes|OGC Nizza',
  NED:'AFC Ajax|Ajax Amsterdam|Feyenoord Rotterdam|PSV Eindhoven|AZ Alkmaar|FC Twente Enschede|NEC Nijmegen',
  POR:'Benfica Lissabon|SL Benfica|Sporting CP|FC Porto|Sporting Braga|SC União Torreense',
  BEL:'FC Brügge|Union Saint-Gilloise|RSC Anderlecht|KAA Gent|VV Sint-Truiden',
  AUT:'FC Red Bull Salzburg|LASK|SK Puntigamer Sturm Graz', CZE:'Slavia Prag|Sparta Prag|Viktoria Pilsen|FK Jablonec',
  TUR:'Fenerbahçe SK|Galatasaray Istanbul|Besiktas Istanbul|Trabzonspor', GRE:'Olympiakos Piräus|AEK Athen|OFI Kreta|PAOK Saloniki|Panathinaikos FC',
  UKR:'Shakhtar Donetsk|Schachtjor Donezk|Dynamo Kiew', NOR:'FK Bodö/Glimt|Viking|Lillestrøm SK|Brann',
  SUI:'BSC Young Boys|FC Thun|FC Lugano', CRO:'Dinamo Zagreb|Hajduk Split', SRB:'Roter Stern Belgrad', KAZ:'FK Kairat',
  CYP:'Paphos FC|Omonia Nikosia', AZE:'Qarabag FK|Sabah', SVK:'Slovan Bratislava', SCO:'Celtic Glasgow|Glasgow Rangers|Heart of Midlothian FC',
  DEN:'FC Kopenhagen|FC Midtjylland|AGF Aarhus|FC Nordsjaelland', ARM:'FC Ararat-Armenia', HUN:'Ferencváros Budapest',
  ISR:'Hapoel Beer Scheva|Maccabi Tel Aviv', POL:'Lech Poznan|Jagiellonia Bialystok', BUL:'Levski Sofia|Ludogorez Rasgrad|ZSKA Sofia',
  SVN:'NK Celje', SWE:'IF Elfsborg|Malmö FF|Mjällby AIF', ROU:'FCSB Bukarest|Universitatea Craiova',
  LVA:'Rigas Futbola Skola|Riga FC', BIH:'Borac Banja Luka', GEO:'FC Iberia 1999 Tiflis', LTU:'FK Kauno Žalgiris',
  AND:"Inter Club d’Escaldes", ALB:'KF Egnatia', FIN:'KuPS Kuopio', GIB:'Lincoln Red Imps'
};
const namePairs={
  'AC Mailand':'AC Milan','AFC Ajax':'Ajax Amsterdam','OSC Lille':'Lille OSC','Lille':'Lille OSC',
  'SL Benfica':'Benfica Lissabon','Paris St. Germain':'Paris Saint-Germain','FC Villareal':'Villarreal CF','Villarreal':'Villarreal CF',
  'FC Bayern München':'Bayern Munich','Bayern München':'Bayern Munich','Schachtjor Donezk':'Shakhtar Donetsk',
  'FC Brügge':'Club Brugge','Inter Mailand':'Inter','AS Rom':'AS Roma','FC Liverpool':'Liverpool',
  'FC Barcelona':'Barcelona','FC Arsenal':'Arsenal','SSC Neapel':'SSC Napoli','Manchester United':'Manchester United FC',
  'Sabah FK':'Sabah','Slavia Prague':'Slavia Prag','Fenerbahçe':'Fenerbahçe SK','Atlético de Madrid':'Atletico Madrid',
  'Tottenham Hotspur FC':'Tottenham Hotspur'
};
const canonical=name=>Core.canonical('UCL',Object.hasOwn(namePairs,name?.trim())?namePairs[name.trim()]:name);
const association=new Map(Object.entries(groups).flatMap(([country,names])=>names.split('|').map(n=>[canonical(n),country])));
const clamped=x=>Math.min(3.2,Math.max(.35,x));

export function europeResults(games, competition, league, season, cutoff) {
  if(!Array.isArray(games)||games.length>250)throw Error('INTERNATIONAL_SOURCE_SHAPE');
  const rows=new Map(),ids=new Set(),day=new Date(cutoff).toISOString().slice(0,10);
  for(const match of games){
    if(match.leagueShortcut!==league||Number(match.leagueSeason)!==season||!Number.isSafeInteger(match.matchID)
      ||ids.has(match.matchID))throw Error('INTERNATIONAL_COMPETITION_MISMATCH');
    ids.add(match.matchID);
    if(match.matchIsFinished!==true||!/^\d{1,2}\.\s*Spieltag$/i.test(match.group?.groupName)||!match.matchDateTimeUTC?.endsWith('Z'))continue;
    const kickoff=Date.parse(match.matchDateTimeUTC);
    if(!Number.isFinite(kickoff)||kickoff>=cutoff-3*3600000)continue;
    const date=new Date(kickoff).toISOString().slice(0,10);
    if(date>=day||date<season+'-07-01'||date>=(season+1)+'-07-01')continue;
    const finals=match.matchResults?.filter(x=>x.resultTypeKind==='After90Minutes');
    if(finals?.length!==1)continue;
    const {pointsTeam1:hg,pointsTeam2:ag}=finals[0];
    if([hg,ag].some(n=>!Number.isInteger(n)||n<0||n>12))continue;
    const home=canonical(match.team1?.teamName),away=canonical(match.team2?.teamName);
    if(!home||!away||home===away)throw Error('INTERNATIONAL_TEAM_MAPPING');
    const key=[competition,date,home,away].join('|');
    if(rows.has(key))throw Error('DUPLICATE_INTERNATIONAL_RESULT');
    rows.set(key,{home,away,hg,ag,kickoff,date,when:kickoff,season,competition});
  }
  return [...rows.values()];
}

function transnationalForecast(fixture,history,now,includeMarkets){
  const home=canonical(fixture.home_team),away=canonical(fixture.away_team), day=new Date(now).toISOString().slice(0,10);
  const matches=history.filter(x=>x.date<day&&x.when<now).sort((a,b)=>a.when-b.when);
  const relevant=matches.filter(x=>x.competition===fixture.competition);
  const teams=new Map(), nations=new Map(), recent=new Map();
  const homeNation=association.get(home),awayNation=association.get(away);
  if(!homeNation||!awayNation)return {reason:'UNMAPPED_ASSOCIATION'};
  if(relevant.length<60)return {reason:'INSUFFICIENT_INTERNATIONAL_HISTORY'};
  if(fixture.displaced_home===true)return {reason:'VENUE_OUTSIDE_VALIDATION'};
  const rating=(team,country)=>(teams.get(team)??0)+.35*(nations.get(country)??0);
  // Only past head-to-head fixtures contribute to club and association ratings.
  for(const game of matches){
    const a=association.get(game.home),b=association.get(game.away);
    if(!a||!b)continue;
    const same=game.competition===fixture.competition;
    recent.set(game.home,(recent.get(game.home)||0)+Number(same));
    recent.set(game.away,(recent.get(game.away)||0)+Number(same));
    const homeEdge=a==='UKR'?0:55;
    const expectation=1/(1+10**((rating(game.away,b)-rating(game.home,a)-homeEdge)/400));
    const actual=game.hg===game.ag ? 0.5 : Number(game.hg>game.ag);
    const error=actual-expectation;
    teams.set(game.home,(teams.get(game.home)||0)+20*error);
    teams.set(game.away,(teams.get(game.away)||0)-20*error);
    if(a!==b){
      nations.set(a,(nations.get(a)||0)+8*error);
      nations.set(b,(nations.get(b)||0)-8*error);
    }
  }
  const n=Math.min(recent.get(home)||0,recent.get(away)||0);
  if(n<4)return {reason:'INSUFFICIENT_TEAM_INTERNATIONAL_HISTORY'};
  const homeGoals=relevant.reduce((sum,x)=>sum+x.hg,0)/relevant.length;
  const awayGoals=relevant.reduce((sum,x)=>sum+x.ag,0)/relevant.length;
  const delta=(rating(home,homeNation)-rating(away,awayNation))/600;
  const h=clamped(homeGoals*Math.exp(delta)),a=clamped(awayGoals*Math.exp(-delta));
  return {probabilities:{...Core.outcomes(h,a),expected_goals_home:h,expected_goals_away:a},sample_n:n,
    markets:includeMarkets?modelMarkets(Core.scoreGrid(h,a),Core.scoreGrid(clamped(homeGoals),clamped(awayGoals))):[],
    evidence:{source:'OpenLigaDB (ODbL 1.0)',history_matches:relevant.length,home_association:homeNation,
      away_association:awayNation,latest_training_date:relevant.at(-1).date}};
}

export function europeReplay(competition,rows,cutoff){
  const policy={...paperPolicy,archive:{...paperPolicy.archive,since:'2025-08-01'}};
  const same=rows.filter(x=>x.competition===competition);
  return leagueWalkForward(same,(game,_training,asof)=>{
    return transnationalForecast({competition,home_team:game.home,away_team:game.away,displaced_home:association.get(game.home)==='UKR'},
      rows,asof,false).probabilities;
  },cutoff,policy);
}

export { transnationalForecast };

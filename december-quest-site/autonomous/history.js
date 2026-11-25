const day = 86400000;
const fields = {
  shots: ['HS','AS'], shots_on_target: ['HST','AST'], corners: ['HC','AC'],
  fouls: ['HF','AF'], yellow_cards: ['HY','AY']
};
const round = value => Number(value.toFixed(2));
const toCount = value => typeof value === 'string' && /^\d+$/.test(value.trim()) &&
  Number(value) <= 100 ? Number(value) : null;

export function matchStatistics(raw) {
  const metrics = Object.fromEntries(Object.entries(fields).flatMap(([key,columns])=>{
    const pair = columns.map(column=>toCount(raw[column]));
    return pair.every(value=>value !== null) ? [[key,pair]] : [];
  }));
  if (metrics.shots && metrics.shots_on_target &&
      metrics.shots_on_target.some((n,side)=>n>metrics.shots[side])) {
    delete metrics.shots_on_target;
  }
  return metrics;
}

function average(pairs, prefix = '') {
  if (!pairs.length) return null;
  const [forTotal,againstTotal] = pairs.reduce(([a,b],[x,y])=>[a+x,b+y],[0,0]);
  return { [prefix+'for']:round(forTotal/pairs.length), [prefix+'against']:round(againstTotal/pairs.length) };
}

function teamProfile(rows, name, venue, kickoff) {
  const games = rows.flatMap(game=>{
    if (game.home===name) return [{...game,side:0,scored:[game.hg,game.ag]}];
    if (game.away===name) return [{...game,side:1,scored:[game.ag,game.hg]}];
    return [];
  }).sort((a,b)=>b.when-a.when);
  const homeAway = games.filter(game=>game.side===venue).slice(0,20);
  const form = [5,10,20].map(window=>{
    const sample=games.slice(0,window);
    const wins=sample.filter(({scored:[goals,against]})=>goals>against).length;
    const draws=sample.filter(({scored:[goals,against]})=>goals===against).length;
    return {window,n:sample.length,wins,draws,losses:sample.length-wins-draws,
      points_per_game:sample.length?round((wins*3+draws)/sample.length):null,
      goals:average(sample.map(row=>row.scored))};
  });
  const metrics=Object.fromEntries(Object.keys(fields).map(key=>{
    const observed=homeAway.filter(row=>row.metrics?.[key]);
    const pairs=observed.map(row=>[row.metrics[key][row.side],row.metrics[key][1-row.side]]);
    return [key,{n:observed.length,total:homeAway.length,rate:average(pairs)}];
  }));
  const rest=games[0] ? Math.floor(Date.parse(kickoff.slice(0,10)+'T00:00:00Z')/day) - Math.floor(games[0].when/day) : null;
  return {form,venue:venue===0?'HOME':'AWAY',venue_n:homeAway.length,
    venue_goals:average(homeAway.map(row=>row.scored)), latest_league_result:games[0]?.date??null,
    days_since_latest_league_result:rest,metrics};
}

function refereeProfile(rows, referee) {
  if (!referee) return null;
  const normalize=name=>name?.normalize('NFKC').trim().toLowerCase().replace(/\s+/g,' ');
  const sample=rows.filter(row=>normalize(row.referee)===normalize(referee)&&
    row.metrics?.yellow_cards&&row.metrics?.fouls);
  const sum=pair=>pair[0]+pair[1];
  const yellows=sample.reduce((total,row)=>total+sum(row.metrics.yellow_cards),0);
  const fouls=sample.reduce((total,row)=>total+sum(row.metrics.fouls),0);
  return {name:referee,n:sample.length,yc_per_game:sample.length?round(yellows/sample.length):null,
    yc_per_foul:fouls?round(yellows/fouls):null,
    low_card_matches:sample.filter(row=>sum(row.metrics.yellow_cards)<=1).length};
}

export function historyProfile(rows, home, away, kickoff, cutoff, referee = null) {
  const cutoffDay = new Date(cutoff).toISOString().slice(0,10);
  const completed = rows.filter(row=>row.date<cutoffDay && row.when<cutoff);
  if (!completed.length) return null;
  return {scope:'LEAGUE_RESULTS_ONLY', source:'football-data.co.uk',
    home:teamProfile(completed,home,0,kickoff), away:teamProfile(completed,away,1,kickoff),
    referee:refereeProfile(completed,referee)};
}

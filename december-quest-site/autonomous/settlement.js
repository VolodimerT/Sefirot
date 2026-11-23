/* Independent settlement of earliest prospective model snapshot from secondary finished-result CSV. */
import Core from './core.js';
const reduce=(x,d=4)=>Math.round(x*10**d)/10**d;
function resultFromFixture(fixture,history,snapshots,now=Date.now()){
 if(!Core.LEAGUE_FILES[fixture.competition])return null;
 const kickoff=Date.parse(fixture.kickoff);
 if(!Number.isFinite(kickoff)||kickoff>=now-3*3600000)return null;
 const date=new Date(kickoff).toISOString().slice(0,10);
 if(date>=new Date(now).toISOString().slice(0,10))return null; // require next day, no live inference
 const h=Core.canonical(fixture.competition,fixture.home_team),a=Core.canonical(fixture.competition,fixture.away_team);
 const actual=history.filter(r=>r.date===date&&r.home===h&&r.away===a);
 if(actual.length!==1)return null;
 const eligible=snapshots.filter(s=>s.fixture_key===fixture.fixture_key&&
  ['MODEL_ONLY','WAITING_ODDS'].includes(s.status)&&
  Number.isFinite(Date.parse(s.generated_at))&&Date.parse(s.generated_at)<kickoff&&
  s.probabilities&&['home','draw','away'].every(k=>typeof s.probabilities[k]==='number'&&s.probabilities[k]>0&&s.probabilities[k]<1))
  .sort((x,y)=>Date.parse(x.generated_at)-Date.parse(y.generated_at));
 const earliest=eligible[0];if(!earliest)return null;
 const row=actual[0],result=row.hg>row.ag?'H':row.hg<row.ag?'A':'D';
 const p=earliest.probabilities,y={home:result==='H'?1:0,draw:result==='D'?1:0,away:result==='A'?1:0};
 const brier=(p.home-y.home)**2+(p.draw-y.draw)**2+(p.away-y.away)**2;
 const probability=p[result==='H'?'home':result==='D'?'draw':'away'];
 return {fixture_key:fixture.fixture_key,snapshot_id:earliest.id,kickoff:fixture.kickoff,
  actual_home_goals:row.hg,actual_away_goals:row.ag,result,
  model_brier:reduce(brier),model_logloss:reduce(-Math.log(Math.max(.000001,probability))),
  source_quality:'secondary',
  source_url:'https://football-data.co.uk/mmz4281/2627/'+Core.LEAGUE_FILES[fixture.competition]+'.csv'};
}
export default {resultFromFixture};

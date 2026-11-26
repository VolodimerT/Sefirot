/* Offline settlement and research sensitivity. No network or policy decisions. */
import { pathToFileURL } from "node:url";
function makeReference(){
  const grades=["loss","half_loss","push","half_win","win"];
  function legOutcomes(leg){
    const {odds,settlement}=leg??{};
    if(!Number.isFinite(odds)||odds<=1||odds>100) throw Error("invalid odds");
    if(!settlement||grades.some(k=>!Number.isFinite(settlement[k])||settlement[k]<0||settlement[k]>1)||Math.abs(grades.reduce((s,k)=>s+settlement[k],0)-1)>1e-9) throw Error("invalid settlement distribution");
    const factor=[0,0.5,1,(odds+1)/2,odds];
    return grades.map((k,i)=>({grade:k,p: settlement[k],factor:factor[i]})).filter(x=>x.p>0);
  }
  function summarize(outcomes){
    const mass=outcomes.reduce((s,x)=>s+x.p,0);
    if(Math.abs(mass-1)>1e-8)throw Error("invalid joint mass");
    const expected=outcomes.reduce((s,x)=>s+x.p*(x.factor-1),0);
    const variance=outcomes.reduce((s,x)=>s+x.p*(x.factor-1-expected)**2,0);
    return {mass,expected,variance,lossProbability:outcomes.filter(x=>x.factor<1).reduce((s,x)=>s+x.p,0),pushProbability:outcomes.filter(x=>x.factor===1).reduce((s,x)=>s+x.p,0),profitProbability:outcomes.filter(x=>x.factor>1).reduce((s,x)=>s+x.p,0),outcomes};
  }
  function validateLegs(legs){
    if(!Array.isArray(legs)||legs.length<1||legs.length>3)throw Error("requires 1-3 legs");
    if(legs.some(l=>typeof l?.fixtureId!=="string"||!l.fixtureId.trim())||new Set(legs.map(l=>l.fixtureId.trim())).size!==legs.length)throw Error("duplicate or missing fixture identity");
  }
  function independentPortfolio(legs,assumption){
    validateLegs(legs);
    if(legs.length>1&&assumption!=="SYNTHETIC_INDEPENDENCE_ONLY")throw Error("independence not established; reference only");
    let dist=[{p:1,factor:1}];
    for(const l of legs)dist=dist.flatMap(a=>legOutcomes(l).map(b=>({p:a.p*b.p,factor:a.factor*b.factor})));
    return summarize(dist);
  }
  // Mix independence with a shared adverse rank. This keeps the original
  // five-grade marginals fixed and changes only how often errors cluster.
  function stressPortfolio(legs, commonRankWeight) {
    validateLegs(legs);
    if (!Number.isFinite(commonRankWeight) || commonRankWeight < 0 || commonRankWeight > 1)
      throw Error("invalid dependence weight");
    const independent = independentPortfolio(legs, "SYNTHETIC_INDEPENDENCE_ONLY");
    const cdfs = legs.map(leg => {
      let total = 0;
      return legOutcomes(leg).map(({p, factor}) => ({end: total += p, factor}));
    });
    const breaks = [...new Set([0, 1, ...cdfs.flat().map(({end}) => Math.min(1, end))])].sort((a, b) => a - b);
    const aligned = breaks.slice(1).map((upper, i) => {
      const lower = breaks[i];
      const quantile = (lower + upper) / 2;
      const factor = cdfs.reduce((product, cdf) =>
        product * (cdf.find(x => quantile <= x.end) ?? cdf.at(-1)).factor, 1);
      return {p: (upper - lower) * commonRankWeight, factor};
    });
    return summarize(independent.outcomes.map(row => ({...row, p: row.p * (1 - commonRankWeight)}))
      .concat(aligned).filter(({p}) => p > 0));
  }
  return {legOutcomes,summarize,independentPortfolio,stressPortfolio};
}
function selfTest(api){
  const a={fixtureId:"synthetic-A",odds:2,settlement:{loss:.25,half_loss:0,push:.30,half_win:0,win:.45}};
  const b={fixtureId:"synthetic-B",odds:2,settlement:{loss:.1,half_loss:.2,push:.2,half_win:.3,win:.2}};
  const c={fixtureId:"synthetic-C",odds:2,settlement:{loss:.5,half_loss:0,push:0,half_win:0,win:.5}};
  let count=0;
  function near(actual,expected){if(Math.abs(actual-expected)>1e-9)throw Error(`${actual} != ${expected}`);count++}
  function rejects(f){let failed=false;try{f()}catch{failed=true}if(!failed)throw Error("expected rejection");count++}
  const single=api.independentPortfolio([a]),half=api.independentPortfolio([b]);
  near(single.expected,.2); near(single.pushProbability,.3); near(half.expected,.15); near(half.lossProbability,.3);
  near(api.independentPortfolio([a,b],"SYNTHETIC_INDEPENDENCE_ONLY").expected,.38);
  near(api.independentPortfolio([a,b,c],"SYNTHETIC_INDEPENDENCE_ONLY").expected,.38);
  near(api.independentPortfolio([c]).expected,0);
  rejects(()=>api.independentPortfolio([a,b])); rejects(()=>api.independentPortfolio([a,a],"SYNTHETIC_INDEPENDENCE_ONLY"));
  rejects(()=>api.independentPortfolio([{...a,odds:null}]));
  rejects(()=>api.independentPortfolio([{...a,settlement:{...a.settlement,win:.9}}]));
  rejects(()=>api.independentPortfolio([a,b,c,{...c,fixtureId:"D"}],"SYNTHETIC_INDEPENDENCE_ONLY"));
  return {assertions:count,synthetic:{binaryProxy:a.settlement.win*a.odds-1,settlementReference:single.expected},noRealMatches:true};
}
export const reference=makeReference();
export const syntheticSelfTest=selfTest(reference);
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  console.log(JSON.stringify(syntheticSelfTest));
}

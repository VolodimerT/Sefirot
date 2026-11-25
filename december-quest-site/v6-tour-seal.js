/* V5.2: authenticated append-only server seal for a December Quest tour */
(function(){
'use strict';
const B=window.questBridge,E=window.SEQ;
if(!B||!E)return;
let busy=false;
function kickoff(t,date){
 const list=E.active(t).map(l=>E.legKickoff(l.kickoff)).filter(Number.isFinite);
 if(list.length&&t.mode!=='pass')return new Date(Math.min(...list)).toISOString();
 // No active legs if PASS: only a real fixture can act as the prospective deadline.
 if(t.mode==='pass'){
  const matches=(window.QuestSchedule?.get()||[]).filter(x=>{
   const dateKey=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(x.kickoff));
   return dateKey===date;
  }).sort((a,b)=>Date.parse(a.kickoff)-Date.parse(b.kickoff));
  return matches[0]?.kickoff||null;
 }
 return null;
}
async function sealTour(){
 if(busy)return;
 const date=B.day();
 const t=B.tour();
 if(!t||t.state==='closed'){B.toast('Закрытый тур менять нельзя.',true);return;}
 if(t.serverSealId){B.toast('Серверный снимок уже существует.',true);return;}
 if(!window.QuestExtra?.serverSeal){B.toast('Облачное подключение недоступно.',true);return;}
 const errors=E.validateSeal(t);
 if(errors.length){B.toast('Серверный seal запрещён: '+errors.slice(0,2).join('; ').slice(0,220),true);return;}
 const ko=kickoff(t,date);
 if(!ko||Date.parse(ko)<=Date.now()){B.toast('Нет будущего матча для PREMATCH seal. Проверь kickoff.',true);return;}
 const content={date:t.date||date,purchased:t.purchased,mode:t.mode,riskClass:t.riskClass,
  verdict:t.verdict,independenceReviewed:t.independenceReviewed,decisionNote:t.decisionNote,
  legs:t.mode==='pass'?[]:t.legs,baseline:t.baseline,alternate:t.alternate,ticketHash:t.ticket?.sha256||null};
 const serverPayload={version:1,kind:'tour',date,gameKickoff:ko,snapshot:content,
  asOfClaim:new Date().toISOString(),source:'DECEMBER_QUEST_V5_2'};
 busy=true;
 try{
  const receipt=await window.QuestExtra.serverSeal('tour','TOUR-'+date,ko,serverPayload);
  if(t.state==='draft'){t.sealedSnapshot=JSON.stringify(content);t.state='sealed';t.xp.sealed=true;t.xp.decision=t.mode==='pass'||String(t.decisionNote||'').trim().length>=20;}
  t.sealedAt=receipt.sealed_at;t.serverSealId=receipt.id;t.updatedAt=receipt.sealed_at;
  if(!Array.isArray(t.audit))t.audit=[];
  t.audit.push({at:receipt.sealed_at,action:'SERVER PREMATCH SEAL'});
  B.save();B.refresh();B.toast('Серверный снимок подтверждён: время установлено Supabase.');
 }catch(e){
  B.toast('Снимок не создан: '+String(e.message||e).slice(0,220),true);
 }finally{busy=false;}
}
document.addEventListener('click',e=>{const el=e.target.closest('[data-tour-server-seal]');if(el){e.preventDefault();sealTour();}});
window.QuestServerTour={sealTour,kickoff};
})();

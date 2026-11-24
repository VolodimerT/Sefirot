async function getCsv(url){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),11000);
 try{
  const r=await fetch(url,{redirect:"error",signal:c.signal,headers:{Accept:"text/csv,text/plain;q=0.9,*/*;q=0.1"}});
  if(!r.ok||r.url&&!/^https:\/\/(www\.)?football-data\.co\.uk\//.test(r.url))throw Error("PROVIDER_HTTP_OR_REDIRECT_"+r.status);
  const len=Number(r.headers.get("content-length")||"0");if(len>4500000)throw Error('CSV_TOO_LARGE');
  const text=await r.text();if(text.length>4500000)throw Error('CSV_TOO_LARGE');
  if(text.slice(0,120).toLowerCase().includes('<html'))throw Error('PROVIDER_HTML_NOT_CSV');
  return text;
 }finally{clearTimeout(timer);}
}
export async function fetchCsvWithRetry(url){
 try{return await getCsv(url);}
 catch(error){
  if(!['AbortError','TypeError'].includes(error.name)&&!/^PROVIDER_HTTP_OR_REDIRECT_5/.test(error.message))throw error;
  await new Promise(resolve=>setTimeout(resolve,250));
  return getCsv(url);
 }
}

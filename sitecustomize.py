"""Temporary gated probe for Oct 6 UEFA Nations League odds; no secret output."""
import os, json, urllib.request, urllib.parse, statistics

if os.environ.get("SEFIROT_OCT6_ODDS_PROBE") == "1":
    KEY=os.environ.get("SEFIROT_ODDS_API_KEY","")
    SPORT="soccer_uefa_nations_league"
    DATE="2026-10-06"
    def req(url):
        r=urllib.request.Request(url,headers={"Accept":"application/json"})
        with urllib.request.urlopen(r,timeout=30) as x:
            return json.loads(x.read().decode()),dict(x.headers)
    def med(xs):
        return round(statistics.median(xs),4) if xs else None
    try:
        evurl="https://api.the-odds-api.com/v4/sports/"+SPORT+"/events?apiKey="+urllib.parse.quote(KEY)
        evs,h=req(evurl)
        targets=[e for e in evs if str(e.get("commence_time","")).startswith(DATE)]
        out={"status":"OK","date":DATE,"event_count":len(targets),"quota_before":{"remaining":h.get("x-requests-remaining"),"used":h.get("x-requests-used")},"events":[]}
        markets="h2h,draw_no_bet,spreads,alternate_spreads,totals,alternate_totals,btts,team_totals"
        last_h=h
        for e in targets:
            u=("https://api.the-odds-api.com/v4/sports/"+SPORT+"/events/"+e["id"]+"/odds?"
               +urllib.parse.urlencode({"apiKey":KEY,"regions":"eu","markets":markets,"oddsFormat":"decimal"}))
            od,last_h=req(u)
            buckets={}
            raw_team_totals=[]
            for b in od.get("bookmakers",[]):
                for m in b.get("markets",[]):
                    key=m.get("key")
                    for o in m.get("outcomes",[]):
                        name=o.get("name"); price=o.get("price"); point=o.get("point")
                        if not isinstance(price,(int,float)): continue
                        if key=="h2h":
                            k=("h2h",name)
                        elif key=="btts":
                            k=("btts",name)
                        elif key=="draw_no_bet":
                            k=("dnb",name)
                        elif key in ("totals","alternate_totals"):
                            k=("total",point,name)
                        elif key in ("spreads","alternate_spreads"):
                            k=("spread",name,point)
                        elif key=="team_totals":
                            raw_team_totals.append({"bookmaker":b.get("key"),"name":name,"description":o.get("description"),"point":point,"price":price})
                            continue
                        else:
                            continue
                        buckets.setdefault(k,[]).append(price)
            summary=[]
            for k,vals in buckets.items():
                if k[0]=="h2h": summary.append({"market":"h2h","side":k[1],"odds":med(vals),"n":len(vals)})
                elif k[0]=="btts": summary.append({"market":"btts","side":k[1],"odds":med(vals),"n":len(vals)})
                elif k[0]=="dnb": summary.append({"market":"dnb","side":k[1],"odds":med(vals),"n":len(vals)})
                elif k[0]=="total": summary.append({"market":"total","line":k[1],"side":k[2],"odds":med(vals),"n":len(vals)})
                elif k[0]=="spread": summary.append({"market":"spread","side":k[1],"line":k[2],"odds":med(vals),"n":len(vals)})
            summary.sort(key=lambda x:(x["market"],str(x.get("line","")),x.get("side","")))
            out["events"].append({"id":e["id"],"home":e["home_team"],"away":e["away_team"],"commence_time":e["commence_time"],"summary":summary,"team_totals_raw":raw_team_totals[:20]})
        out["quota_after"]={"remaining":last_h.get("x-requests-remaining"),"used":last_h.get("x-requests-used")}
        print("SEFIROT_OCT6_ODDS="+json.dumps(out,separators=(",",":"),ensure_ascii=True),flush=True)
    except Exception as exc:
        print("SEFIROT_OCT6_ODDS="+json.dumps({"status":"FAILED","error":type(exc).__name__+":"+str(exc)},separators=(",",":")),flush=True)

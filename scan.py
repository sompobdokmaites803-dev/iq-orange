import os,json,time,math,urllib.parse,urllib.request
from datetime import datetime,timezone,timedelta
from http.server import BaseHTTPRequestHandler
PAIRS=["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CHF","EUR/JPY","EUR/GBP","NZD/USD"]
def getj(url):
    req=urllib.request.Request(url,headers={"User-Agent":"IQOrange/6.1"})
    with urllib.request.urlopen(req,timeout=12) as r:return json.loads(r.read().decode())
def ts5(key,pair,n=300):
    q=urllib.parse.urlencode({"symbol":pair,"interval":"5min","outputsize":n,"apikey":key,"format":"JSON"})
    j=getj("https://api.twelvedata.com/time_series?"+q)
    if j.get("status")=="error": raise RuntimeError(j.get("message","Twelve Data error"))
    vals=[]
    for v in reversed(j.get("values",[])):
        vals.append({"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])})
    return vals
def aggregate(candles,group):
    out=[]
    for i in range(0,len(candles),group):
        chunk=candles[i:i+group]
        if len(chunk)<group: continue
        out.append({"o":chunk[0]["o"],"h":max(x["h"] for x in chunk),"l":min(x["l"] for x in chunk),"c":chunk[-1]["c"]})
    return out
def ema(v,n):
    if not v:return 0
    k=2/(n+1);e=v[0]
    for x in v[1:]:e=x*k+e*(1-k)
    return e
def rsi(v,n=14):
    if len(v)<n+1:return 50
    g=l=0
    for a,b in zip(v[-n-1:-1],v[-n:]):
        d=b-a;g+=max(d,0);l+=max(-d,0)
    if l==0:return 100
    rs=(g/n)/(l/n);return 100-100/(1+rs)
def tr(c):
    cl=[x["c"] for x in c]
    if len(cl)<22:return 0
    e8,e21=ema(cl[-30:],8),ema(cl[-40:],21);s=cl[-1]-cl[-4]
    return 1 if e8>e21 and s>0 else -1 if e8<e21 and s<0 else 0
def analyze(pair,c5):
    c15=aggregate(c5,3); c60=aggregate(c5,12)
    if len(c15)<22 or len(c60)<22:return None
    t15,t60=tr(c15),tr(c60);sign=1 if t15>=0 else -1;direction="CALL" if sign==1 else "PUT";score=0
    score+=25 if t15==sign and (t60==sign or t60==0) else 12 if t15==sign else 0
    x=c5[-1];recent=c5[-8:];rng=max(x["h"]-x["l"],1e-12);body=abs(x["c"]-x["o"])
    if sign==1:
        sup=min(a["l"] for a in recent[:-1]); reclaim=x["c"]>x["o"] and x["l"]<=sup*1.0015
    else:
        res=max(a["h"] for a in recent[:-1]); reclaim=x["c"]<x["o"] and x["h"]>=res*0.9985
    score+=25 if reclaim else 12 if body/rng>.45 else 0
    rr=rsi([a["c"] for a in c5]); mom=(sign==1 and 48<=rr<=72) or (sign==-1 and 28<=rr<=52); score+=10 if mom else 3
    confirm=(sign==1 and x["c"]>x["o"]) or (sign==-1 and x["c"]<x["o"]); score+=10 if confirm else 0
    hi=max(a["h"] for a in c5[-12:]);lo=min(a["l"] for a in c5[-12:]);span=max(hi-lo,1e-12);room=(hi-x["c"])/span if sign==1 else (x["c"]-lo)/span
    score+=15 if room>.28 else 7 if room>.15 else 0
    q=sum(abs(a["c"]-a["o"])/max(a["h"]-a["l"],1e-12) for a in c5[-6:])/6; score+=10 if q>.45 else 5 if q>.30 else 0
    score=min(100,round(score)); status="READY" if score>=90 else "WATCH" if score>=80 else "NO TRADE"; risk="LOWER" if score>=95 else "MEDIUM" if score>=90 else "HIGH"
    entry=(math.floor(time.time()/300)+1)*300+5; et=datetime.fromtimestamp(entry,timezone(timedelta(hours=7))).strftime("%H:%M:%S")
    return {"pair":pair,"direction":direction,"score":score,"status":status,"risk":risk,"entry_time":et,"reason":f"15m/1H {t15}/{t60} · RSI {rr:.1f} · 5m confirm {'ผ่าน' if confirm else 'ยัง'}"}
def run():
    key=os.environ.get("TWELVE_DATA_API_KEY")
    if not key: raise RuntimeError("ยังไม่ได้ตั้ง TWELVE_DATA_API_KEY")
    out=[];errors=[];calls=0
    for p in PAIRS:
        try:
            c5=ts5(key,p,300); calls+=1; a=analyze(p,c5)
            if a: out.append(a)
        except Exception as e: errors.append(f"{p}: {e}")
    out.sort(key=lambda x:x["score"],reverse=True)
    if not out and errors: raise RuntimeError("Twelve Data ไม่มีข้อมูลที่ใช้ได้: "+" | ".join(errors[:2]))
    return {"top":out,"api_calls":calls}
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:d=run();code=200
        except Exception as e:d={"error":str(e)};code=500
        b=json.dumps(d,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b)

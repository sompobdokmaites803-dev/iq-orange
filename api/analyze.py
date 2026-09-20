import os,json,urllib.request,re,time,math
from datetime import datetime,timezone,timedelta
from http.server import BaseHTTPRequestHandler
def call(payload,key):
 req=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
 with urllib.request.urlopen(req,timeout=45) as r:return json.loads(r.read().decode())
def txt(resp):
 if isinstance(resp.get("output_text"),str):return resp["output_text"]
 a=[]
 for o in resp.get("output",[]):
  for c in o.get("content",[]) if isinstance(o,dict) else []:
   if isinstance(c,dict) and isinstance(c.get("text"),str):a.append(c["text"])
 return "\\n".join(a)
class handler(BaseHTTPRequestHandler):
 def do_POST(self):
  try:
   n=int(self.headers.get("Content-Length","0"));body=json.loads(self.rfile.read(n).decode());key=os.environ.get("OPENAI_API_KEY")
   if not key:raise RuntimeError("ยังไม่ได้ตั้ง OPENAI_API_KEY")
   prompt=f"""วิเคราะห์ screenshot กราฟ IQ Option เพื่อยืนยันแผน 5 นาที
คู่ {body.get('pair')} / STEP1 {body.get('stage1_direction')} score {body.get('stage1_score')}
ใช้เฉพาะข้อมูลในภาพ ตรวจ trend, support/resistance, momentum, stochastic/indicator ถ้ามี และแท่งล่าสุด
ตอบ JSON เท่านั้น: {{"direction":"UP|DOWN|WAIT","score":0-100,"risk":"LOW|MEDIUM|HIGH","status":"READY|WATCH|NO TRADE","reason":"เหตุผลสั้นภาษาไทย"}}
ถ้าภาพไม่ชัด/เก่า/มี popup บัง/สัญญาณขัดกัน ให้ WAIT"""
   payload={"model":"gpt-5.6-luna","input":[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","image_url":body.get("image")}]}],"max_output_tokens":400}
   r=call(payload,key);m=re.search(r'\\{.*\\}',txt(r),re.S)
   if not m:raise RuntimeError("AI parse failed")
   d=json.loads(m.group(0));direction=d.get("direction","WAIT");status=d.get("status","WATCH")
   entry=None
   if direction!="WAIT" and status=="READY":
    ep=(math.floor(time.time()/300)+1)*300+5;entry=datetime.fromtimestamp(ep,timezone(timedelta(hours=7))).strftime("%H:%M:%S")
   out={"direction":direction,"score":int(d.get("score",0)),"risk":d.get("risk","HIGH"),"status":status,"reason":d.get("reason",""),"entry_time":entry};code=200
  except Exception as e:out={"error":str(e)};code=500
  b=json.dumps(out,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b)

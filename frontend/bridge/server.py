"""Loopback local-submit bridge. Start with uv run python bridge/server.py."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import gm_contract
import datetime
import argparse, json, queue, secrets, sqlite3, subprocess, tempfile, threading, os, fcntl
from contextlib import contextmanager
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / 'tools'))
import git_baseline
class Conflict(Exception): pass
class Store:
 def __init__(self,path,mode,thread):
  self.path=str(path);self.lock=threading.RLock()
  with self.db() as c:
   c.executescript('CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT); CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,hash TEXT,payload TEXT,state TEXT,result TEXT);')
   old=dict(c.execute('SELECT k,v FROM meta'))
   if old and (old['mode']!=mode or old['thread']!=thread):raise ValueError('State belongs to a different adapter/thread; choose another --state file.')
   for k,v in {'mode':mode,'thread':thread,'revision':'0','storeId':secrets.token_hex(16)}.items():c.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',(k,v))
   c.execute("UPDATE submissions SET state='uncertain' WHERE state IN ('accepted','processing')")
 @contextmanager
 def db(self):
  connection=sqlite3.connect(self.path)
  try:
   with connection:
    yield connection
  finally:
   connection.close()
 def identity(self):
  with self.db() as c:return c.execute("SELECT v FROM meta WHERE k='storeId'").fetchone()[0]
 def revision(self):
  with self.db() as c:return int(c.execute("SELECT v FROM meta WHERE k='revision'").fetchone()[0])
 def get(self,sid):
  with self.db() as c:r=c.execute('SELECT payload,state,result FROM submissions WHERE id=?',(sid,)).fetchone()
  return {'submissionId':sid,'payload':json.loads(r[0]),'state':r[1],'result':json.loads(r[2])} if r else None
 def last(self):
  with self.db() as c:r=c.execute('SELECT id FROM submissions ORDER BY rowid DESC LIMIT 1').fetchone()
  return self.get(r[0]) if r else None
 def accept(self,p):
  raw=json.dumps(p,sort_keys=True,separators=(',',':'))
  with self.lock,self.db() as c:
   old=c.execute('SELECT payload FROM submissions WHERE id=?',(p['submissionId'],)).fetchone()
   if old:
    if old[0]!=raw:raise Conflict('This submission ID already belongs to a different immutable payload.')
    return False
   if c.execute("SELECT 1 FROM submissions WHERE state IN ('accepted','processing','uncertain')").fetchone():raise Conflict('Prior delivery is active or uncertain. Reconcile before another submit.')
   rev=int(c.execute("SELECT v FROM meta WHERE k='revision'").fetchone()[0])
   if p['baseRevision']!=rev:raise Conflict('Another tab submitted first. Refresh status and review before submitting.')
   c.execute('INSERT INTO submissions VALUES (?,?,?,?,?)',(p['submissionId'],'',raw,'accepted','{}'));c.execute("UPDATE meta SET v=? WHERE k='revision'",(str(rev+1),))
  return True
 def update(self,sid,state,result):
  with self.db() as c:c.execute('UPDATE submissions SET state=?,result=? WHERE id=?',(state,json.dumps(result),sid))
class Codex:
 def __init__(self,thread,cwd):
  self.cwd=str(Path(cwd).resolve());self.thread=thread;self.seq=0;self.pending={};self.events=queue.Queue();self.lock=threading.Lock()
  with tempfile.TemporaryDirectory() as d:
   subprocess.run(['codex','app-server','generate-json-schema','--experimental','--out',d],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   s=json.loads(Path(d,'v2','TurnStartParams.json').read_text())
   if 'toolOutput' not in s['properties'] or not {'name','output'} <= set(s.get('definitions',{}).get('TurnToolOutput',{}).get('properties',{})):raise RuntimeError('Installed Codex lacks turn/start.toolOutput; update explicitly.')
  self.version=subprocess.check_output(['codex','--version'],text=True).strip()
  self.proc=subprocess.Popen(['codex','app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,cwd=self.cwd)
  threading.Thread(target=self.read,daemon=True).start()
  self.rpc('initialize',{'clientInfo':{'name':'dna_workbench','version':'0.3.0'},'capabilities':{'experimentalApi':True}});self.write({'method':'initialized'})
  resumed=self.rpc('thread/resume',{'threadId':thread})
  actual=resumed.get('thread',{}).get('cwd')
  if not actual or Path(actual).resolve()!=Path(self.cwd):
   self.proc.terminate();raise RuntimeError('Thread cwd differs from server-owned --project-root; use the matching existing thread.')
 def write(self,p):
  with self.lock:self.proc.stdin.write(json.dumps(p)+'\n');self.proc.stdin.flush()
 def read(self):
  for line in self.proc.stdout:
   try:p=json.loads(line)
   except ValueError:continue
   if 'id' in p and 'method' in p:self.write({'id':p['id'],'error':{'code':-32601,'message':'Interactive requests require native Codex; this bridge does not grant approvals.'}})
   elif 'id' in p and ('result' in p or 'error' in p) and p['id'] in self.pending:self.pending[p['id']].put(p)
   else:self.events.put(p)
 def rpc(self,method,params):
  self.seq+=1;rid=self.seq;q=queue.Queue();self.pending[rid]=q;self.write({'id':rid,'method':method,'params':params})
  try:r=q.get(timeout=30)
  finally:self.pending.pop(rid,None)
  if 'error' in r:raise RuntimeError(r['error'].get('message','Codex request failed'))
  return r['result']
 def submit(self,p,store):
  t=self.rpc('thread/read',{'threadId':self.thread,'includeTurns':False})['thread'];s=t.get('status',{});s=s.get('type') if isinstance(s,dict) else s
  if s!='idle':raise Conflict('Codex thread is not idle. Finish its current turn first.')
  if p.get('version')==2:
   controlled=gm_contract.controlled_inventory(self.cwd)
   if controlled!=self.gm_plan.get('baselineControlledFiles') or gm_contract.authority_digest(controlled,gm_contract.adapter_baseline())!=p.get('reviewedAuthorityDigest'):raise Conflict('Reviewed authority changed before dispatch. Create a new preview.')
  r=self.rpc('turn/start',{'threadId':self.thread,'input':[],'toolOutput':{'name':'dna_workbench_submit','namespace':None,'output':json.dumps(gm_contract.dispatch_payload(p, self.gm_plan) if p.get('version')==2 else p,ensure_ascii=False)}});turn=r['turn']['id']
  processing={'message':'Codex is processing this submitted revision.','turnId':turn}
  if p.get('version')==2:
   processing=gm_contract.result_record(p,turn,plan=self.gm_plan,message='Codex is processing this submitted revision.')
   processing['turn']['status']='RUNNING'
   processing['turnStartedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  store.update(p['submissionId'],'processing',processing);texts=[]
  while True:
   e=self.events.get(timeout=600);a=e.get('params',{})
   if a.get('threadId')!=self.thread or a.get('turnId',a.get('turn',{}).get('id'))!=turn:continue
   if e.get('method')=='item/completed' and a.get('item',{}).get('type')=='agentMessage':texts.append(a['item'].get('text',''))
   if e.get('method')=='turn/completed':
    ok=a['turn'].get('status')=='completed'
    if p.get('version')==2:
     result=gm_contract.result_record(p,turn,ok,plan=self.gm_plan,response='\n\n'.join(texts));result['turnStartedAt']=processing['turnStartedAt']
     return ('succeeded' if ok else 'failed'),result
    return ('succeeded' if ok else 'failed'),{'message':'Codex turn completed. Review its response; this UI does not certify source changes.' if ok else 'Codex turn failed or was interrupted.','response':'\n\n'.join(texts),'turnId':turn,'items':[{'id':i['id'],'status':'review_required' if ok else 'failed'} for i in p['items']]}
def source_baseline(root):
 root=Path(root).resolve();lock=json.loads((ROOT/'tools/velvet-source-lock.json').read_text())
 if not isinstance(lock,list) or any(not isinstance(e,dict) or set(e)!={'path','gitBlob'} for e in lock):
  raise Conflict('Source lock requires a reviewed Git identity migration before it can be used.')
 identities={};matches=True
 for entry in lock:
  f=root/entry['path']
  if any(part.is_symlink() for part in [f,*f.parents] if part!=root.parent) or not f.resolve().is_relative_to(root):raise Conflict('Mapped source must stay inside project root.')
  identities[entry['path']]=git_baseline.identity_file(f) if f.is_file() else 'missing'
  matches=matches and identities[entry['path']]==entry['gitBlob']
 current={entry['path']:identities[entry['path']] for entry in lock}
 return git_baseline.identity_bytes(json.dumps(current,sort_keys=True,separators=(',',':')).encode()),matches
class App:
 def __init__(self,a):
  self.project_root=Path(a.project_root).resolve() if a.project_root else None;self.mode=a.mode;self.thread=a.thread or 'demo-local';self.token=secrets.token_urlsafe(32);self.store=Store(a.state,self.mode,self.thread);self.codex=Codex(self.thread,self.project_root) if a.mode=='codex' else None
 def baseline(self):return source_baseline(self.project_root)[0] if self.project_root else git_baseline.identity_file(ROOT/'dist/semantic-data.json')
 def gm_readiness(self):return gm_contract.readiness(self.project_root,self.codex,self.thread,self.baseline())
 def status(self):return {'supportedSubmissionVersions':[1,2],'gmReadiness':self.gm_readiness(),'storeId':self.store.identity(),'sourceMatchesAdapter':source_baseline(self.project_root)[1] if self.project_root else True,'sourceBaseline':self.baseline(),'mode':self.mode,'threadId':self.thread,'revision':self.store.revision(),'last':self.store.last(),'codexVersion':self.codex.version if self.codex else None}
 def run(self,p):
  try:
   if p.get('sourceBaseline')!=self.baseline():raise Conflict('Source files changed since review. Refresh and review before another submission.')
   if p.get('version')==2:
    ready=self.gm_readiness();plan=gm_contract.execution_plan(p,ready)
    if plan['status']!='READY':
     self.store.update(p['submissionId'],'blocked',gm_contract.result_record(p,message='GM execution BLOCKED: '+'; '.join(plan['blockers']),plan=plan));return
    self.codex.gm_plan=plan
   if self.codex:
    if not source_baseline(self.project_root)[1]:raise Conflict('Mapped source differs from reviewed adapter. Re-extract and review source mappings before submitting.')
    s,r=self.codex.submit(p,self.store)
   else:s,r='succeeded',{'message':'Demo validation complete. No model call or source-file change.','items':[{'id':i['id'],'status':'demo_validated'} for i in p['items']]}
   self.store.update(p['submissionId'],s,r)
  except Conflict as e:self.store.update(p['submissionId'],'failed',gm_contract.result_record(p,message=str(e)) if p.get('version')==2 else {'message':str(e)})
  except Exception:
   prior=(self.store.get(p['submissionId']) or {}).get('result',{})
   if p.get('version')==2:
    prior=prior or gm_contract.result_record(p)
    prior['delivery']={'status':'UNCERTAIN'};prior['turn']={**prior.get('turn',{}),'status':'UNKNOWN'}
   self.store.update(p['submissionId'],'uncertain',{**prior,'message':'Delivery/completion is unconfirmed. Do not retry. Inspect the submission ID in native Codex history and reconcile manually.'})
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**k):super().__init__(*a,directory=str(ROOT/'dist'),**k)
 def end_headers(self):
  self.send_header('X-Frame-Options','DENY');self.send_header('Content-Security-Policy',"frame-ancestors 'none'");self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
 def log_message(self,*a):pass
 def allowed(self,write=False):
  host=f'127.0.0.1:{self.server.server_port}';origin=self.headers.get('Origin')
  return self.headers.get('Host')==host and (not origin or origin=='http://'+host) and (not write or self.headers.get('X-Workbench-Token')==self.server.app.token)
 def send_json(self,s,p):
  self.send_response(s);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(json.dumps(p).encode())
 def do_GET(self):
  if not self.allowed():return self.send_json(403,{'error':'Only this loopback origin is allowed.'})
  if self.path=='/api/status':return self.send_json(200,self.server.app.status())
  if self.path.startswith('/api/submission/'):
   item=self.server.app.store.get(self.path.removeprefix('/api/submission/'))
   return self.send_json(200,{'submission':item})
  if self.path=='/api/session':return self.send_json(200,{'token':self.server.app.token})
  if self.path.startswith('/api/'):return self.send_json(404,{'error':'Unknown route'})
  super().do_GET()
 def do_POST(self):
  if not self.allowed(True):return self.send_json(403,{'error':'Invalid origin/session. Refresh connection.'})
  if self.path!='/api/submit':return self.send_json(404,{'error':'Unknown route'})
  try:
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=2000000:raise ValueError('Submission must be 1 byte to 2 MB.')
   if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON content type required.')
   p=json.loads(self.rfile.read(n))
   if not isinstance(p,dict) or not isinstance(p.get('submissionId'),str) or not 1<=len(p['submissionId'])<=100 or type(p.get('baseRevision')) is not int or type(p.get('draftRevision')) is not int or not isinstance(p.get('snapshot'),dict) or not isinstance(p.get('items'),list) or (not p['items'] and p.get('version')!=2):raise ValueError('Invalid submission envelope.')
   if set(p)-(gm_contract.V2_FIELDS if p.get('version')==2 else set())-{'version','taskId','submissionId','threadId','baseRevision','draftRevision','storeId','sourceBaseline','snapshot','items'}:raise ValueError('Unknown envelope fields; execution config is server-owned.')
   if p.get('version') not in (1,2) or p.get('taskId')!='velvet-eclipse' or p.get('snapshot',{}).get('revision')!=p.get('draftRevision'):raise ValueError('Unsupported task/version or draft revision mismatch.')
   if not self.server.app.store.get(p['submissionId']) and p['snapshot'].get('sourceManifest')!=json.loads((ROOT/'tools/velvet-source-lock.json').read_text()):raise Conflict('Browser draft uses an old or unknown source adapter. Reload and reapply/review edits before Submit.')
   if not self.server.app.store.get(p['submissionId']) and p.get('sourceBaseline')!=self.server.app.baseline():raise Conflict('Source baseline changed; refresh and review.')
   if p.get('storeId')!=self.server.app.store.identity():raise Conflict('Durable store identity changed; reconnect to the original store.')
   if p.get('threadId')!=self.server.app.thread:raise ValueError('Thread mapping mismatch.')
   if len(p['items'])>300 or any(not isinstance(i,dict) or not isinstance(i.get('id'),str) or not isinstance(i.get('instruction'),str) or len(i['instruction'])>10000 for i in p['items']):raise ValueError('Invalid item instructions.')
   if p.get('version')==2:gm_contract.validate_v2(p)
   if self.server.app.store.accept(p):threading.Thread(target=self.server.app.run,args=(p,),daemon=True).start()
   self.send_json(202,self.server.app.store.get(p['submissionId']))
  except Conflict as e:self.send_json(409,{'error':str(e)})
  except (ValueError,KeyError,TypeError) as e:self.send_json(400,{'error':str(e)})
def main():
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['demo','codex'],default='demo');p.add_argument('--thread');p.add_argument('--project-root');p.add_argument('--resolve-uncertain');p.add_argument('--import-result');p.add_argument('--resolution-note');p.add_argument('--port',type=int,default=8765);p.add_argument('--state',default=str(ROOT/'.workbench.sqlite3'));a=p.parse_args()
 if a.mode=='codex' and (not a.thread or not a.project_root):p.error('--thread and --project-root required; use the matching existing idle local Codex thread')
 os.umask(0o077)
 # Hold a process-wide lease before Store recovery, including manual reconciliation.
 lease=open(str(Path(a.state).resolve())+'.lock','a')
 try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:p.error('This state file is in use. Stop its bridge before restart or reconciliation.')
 os.chmod(lease.name,0o600)
 if a.resolve_uncertain:
  if not a.resolution_note:p.error('--resolution-note must record the native thread inspection outcome')
  store=Store(a.state,a.mode,a.thread or 'demo-local');item=store.get(a.resolve_uncertain)
  if not item or item['state']!='uncertain':p.error('Only an existing uncertain submission can be reconciled')
  store.update(a.resolve_uncertain,'failed',{'message':'Manually reconciled; no automatic retry. '+a.resolution_note,'priorResult':item['result']});return
 if a.import_result:
  if a.mode!='codex' or not a.project_root or not a.thread:p.error('--import-result requires the original --mode codex --project-root and --thread')
  try:
   supplied=json.loads(Path(a.import_result).read_text());store=Store(a.state,a.mode,a.thread);record=store.get(supplied.get('submissionId'))
   if not record:raise ValueError('Unknown submission ID')
   bound=record['result'].get('executionPlan',{}).get('binding',{})
   if bound.get('threadId')!=a.thread or Path(bound.get('projectRoot','')).resolve()!=Path(a.project_root).resolve():raise ValueError('Evidence project/thread differs from the actual dispatched binding')
   observed=gm_contract.inspect_evidence(a.project_root,supplied.get('runId'))
   result=gm_contract.ingest_evidence(record,supplied,observed)
   store.update(supplied['submissionId'],record['state'],result);print(json.dumps(result,ensure_ascii=False));return
  except (ValueError,KeyError,TypeError,OSError) as e:p.error(str(e))
 app=App(a);os.chmod(a.state,0o600);s=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);s.app=app;print(f'http://127.0.0.1:{a.port} | {a.mode} | {app.thread}',flush=True)
 try:s.serve_forever()
 finally:
  if app.codex:app.codex.proc.terminate()
if __name__=='__main__':main()

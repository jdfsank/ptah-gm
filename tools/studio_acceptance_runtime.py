"""Disposable acceptance: synthetic approval/ACK fixtures, real child processes.

This probe deliberately bypasses role registration only in a temporary test
fixture. It never enables capabilities or accepts a production candidate.
No model turns or independent hash checks are performed.
"""
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.tests.test_studio_delivery import StudioDeliveryTests
from runners.common import LocalJournal, strict_sandbox_rules, stop_process_group
from runners.agent import AgentRunner
from runners.project import ProjectRunner

GODOT = '/Applications/Godot.app/Contents/MacOS/Godot'
CODEX = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
output = {'scope': 'disposable fixture approvals/HTTP ACKs; actual native command sandbox and Godot processes', 'modelTurns': 0, 'checks': {}}

def run(argv, cwd=None, env=None, stdin=None, timeout=40):
    p = subprocess.run(argv, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, timeout=timeout)
    return {'exitCode': p.returncode, 'stdout': p.stdout[-12000:], 'stderr': p.stderr[-12000:]}

class API:
    def __init__(self, material):
        self.material, self.reports = material, []
    def request(self, method, route, body=None):
        if route.endswith('/input'):
            return self.material
        if route.endswith('/heartbeat'):
            return {'cancelRequested': False}
        self.reports.append(body)
        return {'schemaVersion': 'studio.message.v1', 'kind': 'report_ack', **{k:body[k] for k in ('storeId','projectId','attemptId','runnerId','reportId')}, 'disposition':'recorded'}

with tempfile.TemporaryDirectory(prefix='ptah-runtime-acceptance-') as folder:
    root = Path(folder)
    active = root/'active'; active.mkdir()
    other = root/'other'; other.mkdir()
    (other/'canary.txt').write_text('synthetic-other-project')
    (active/'project-script.py').write_text('print("SYNTHETIC_PROJECT_SCRIPT_EXECUTED")\n')
    codex_canary = Path.home()/'.codex'/('studio-acceptance-canary-'+root.name+'.txt')
    codex_canary.write_text('synthetic-auth-scope-canary')
    try:
        profile = AgentRunner._profile([other], active_root=active, write_roots=[active], read_roots=[active,ROOT/'runners',ROOT/'backend'])
        output['checks']['agent-worker-import'] = run(['/usr/bin/sandbox-exec','-p',profile,sys.executable,'-c','import runners.agent_worker; print("WORKER_IMPORT_OK")'],cwd=active,env={**os.environ,'PYTHONPATH':str(ROOT)})
        output['checks']['agent-auth-canary-read'] = run(['/usr/bin/sandbox-exec','-p',profile,'/bin/cat',str(codex_canary)],cwd=active)
        output['checks']['agent-other-project-denied'] = run(['/usr/bin/sandbox-exec','-p',profile,'/bin/cat',str(other/'canary.txt')],cwd=active)
        proc = subprocess.Popen([CODEX,'app-server','--stdio'],cwd=active,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,start_new_session=True)
        try:
            def rpc(n, method, params):
                proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':n,'method':method,'params':params})+'\n'); proc.stdin.flush()
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if select.select([proc.stdout],[],[],1)[0]:
                        raw=proc.stdout.readline()
                        if not raw: raise RuntimeError('native exited')
                        msg=json.loads(raw)
                        if msg.get('id')==n:
                            return msg
                raise TimeoutError(method)
            output['checks']['native-initialize']=rpc(1,'initialize',{'clientInfo':{'name':'studio-acceptance','version':'1'},'capabilities':{'experimentalApi':True}})
            proc.stdin.write(json.dumps({'jsonrpc':'2.0','method':'initialized','params':{}})+'\n');proc.stdin.flush()
            output['checks']['native-readonly-exec']=rpc(2,'command/exec',{'command':[sys.executable,str(active/'project-script.py')],'cwd':str(active),'sandboxPolicy':{'type':'readOnly','networkAccess':False},'timeoutMs':10000})
            output['checks']['native-readonly-auth-canary']=rpc(3,'command/exec',{'command':['/bin/cat',str(codex_canary)],'cwd':str(active),'sandboxPolicy':{'type':'readOnly','networkAccess':False},'timeoutMs':10000})
            output['checks']['native-workspace-write-auth-canary']=rpc(4,'command/exec',{'command':['/bin/cat',str(codex_canary)],'cwd':str(active),'sandboxPolicy':{'type':'workspaceWrite','networkAccess':False,'writableRoots':[str(active)],'excludeSlashTmp':True,'excludeTmpdirEnvVar':True},'timeoutMs':10000})
        finally:
            output['nativeStopped']=stop_process_group(proc.pid,process=proc,grace_seconds=2)
            for f in (proc.stdin,proc.stdout): f.close()
    finally:
        codex_canary.unlink(missing_ok=True)

    fixture = StudioDeliveryTests()
    fixture.setUp()
    try:
        job, ref, repository, ack=fixture.produced()
        attempt=fixture.c._get('attempt',job['verificationAttemptId'])
        fixture.c.claim_runner({'storeId':fixture.c.store_id,'runnerId':'project-test','commandId':'runtime-probe-claim'})
        material=fixture.c.runner_input('project-test',attempt['id'])
        if material is None:
            prepared=fixture.c._get('attempt',job['productionAttemptId'])['prepared']
            material={'packet':fixture.c._get('packet',job['packetId']), 'prepared':prepared}
        api=API(material)
        journal=LocalJournal(root/'journal.sqlite3')
        runner=ProjectRunner(api,journal,fixture.state/'artifacts',fixture.state/'projects',GODOT)
        execution={'storeId':fixture.c.store_id,'attemptId':attempt['id'],'projectId':fixture.pid,'taskKind':'verify','inputRefs':{'artifactRef':ref}}
        def timed_out(*_):
            raise TimeoutError('real Runner did not finish after worker EOF')
        signal.signal(signal.SIGALRM,timed_out)
        signal.alarm(25)
        try:
            runner.verify(execution,fixture.c.store_id)
        except TimeoutError as exc:
            output['checks']['verification-timeout']=str(exc)
        finally:
            signal.alarm(0)
        output['checks']['project-runner-verify']=api.reports
        evidence=fixture.state/'artifacts'/'verification-evidence'/f"{attempt['id']}.json"
        if evidence.exists():
            output['checks']['verification-evidence']=json.loads(evidence.read_text())
        api2=API(material)
        runner.api=api2
        preview={**execution,'attemptId':'preview-real-probe','taskKind':'preview'}
        runner.preview(preview,fixture.c.store_id,max_seconds=8)
        output['checks']['project-runner-preview']=api2.reports
        output['checks']['preview-log']=(fixture.state/'artifacts'/'preview-evidence'/'preview-real-probe.log').read_text()[-16000:]
        output['checks']['verification-copy-status']=run(['git','-C',str(fixture.state/'artifacts'/'verification'/attempt['id']),'status','--porcelain'])
    except Exception as exc:
        output['checks']['project-exception']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        fixture.tearDown()

target=Path(sys.argv[1])
target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'evidence':str(target),'modelTurns':0,'nativeStopped':output.get('nativeStopped'),'verificationStatus':output.get('checks',{}).get('verification-evidence',{}).get('status')},ensure_ascii=False))

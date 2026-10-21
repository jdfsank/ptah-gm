"""Run actual Godot file/cache/loopback denials in a disposable fixture."""
import json, os, socket, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runners.common import strict_sandbox_rules
GODOT="/Applications/Godot.app/Contents/MacOS/Godot"
with tempfile.TemporaryDirectory(prefix="ptah-godot-boundary-") as d:
    root=Path(d).resolve(); project=root/"project";project.mkdir();cache=project/".godot";cache.mkdir()
    protected=root/"other";protected.mkdir();(protected/"canary.txt").write_text("synthetic-other")
    (project/"project.godot").write_text('config_version=5\n')
    (project/"source.txt").write_text("SOURCE_MUST_STAY_UNCHANGED")
    (cache/"escape").symlink_to(protected,target_is_directory=True)
    canary=Path.home()/".codex"/("godot-canary-"+root.name+".txt");canary.write_text("synthetic-auth")
    v4=socket.socket();v4.bind(("127.0.0.1",0));v4.listen()
    v6=socket.socket(socket.AF_INET6);v6.bind(("::1",0));v6.listen()
    checks={}
    try:
        script=cache/"boundary_probe.gd"
        code='''extends SceneTree
func _initialize() -> void:
    var facts: Dictionary = {}
    facts["otherProjectDenied"] = FileAccess.open(%s, FileAccess.READ) == null
    facts["authCanaryDenied"] = FileAccess.open(%s, FileAccess.READ) == null
    facts["sourceWriteDenied"] = FileAccess.open("res://source.txt", FileAccess.WRITE) == null
    facts["symlinkEscapeDenied"] = FileAccess.open("res://.godot/escape/new.txt", FileAccess.WRITE) == null
    var file := FileAccess.open("res://.godot/derived.txt", FileAccess.WRITE)
    facts["cacheWriteAllowed"] = file != null
    if file:
        file.store_string("derived-output")
        file.close()
    var tcp4 := StreamPeerTCP.new()
    facts["ipv4Denied"] = tcp4.connect_to_host("127.0.0.1", %s) != OK
    var tcp6 := StreamPeerTCP.new()
    facts["ipv6Denied"] = tcp6.connect_to_host("::1", %s) != OK
    print("STUDIO_BOUNDARY_FACTS=" + JSON.stringify(facts))
    quit()
''' % (json.dumps(str(protected/"canary.txt")),json.dumps(str(canary)),v4.getsockname()[1],v6.getsockname()[1])
        script.write_text(code)
        profile="".join(strict_sandbox_rules(project,read_roots=[project],write_roots=[cache],protected_paths=[protected],extra_read_paths=[Path("/Applications/Godot.app")]))
        for stage,args in [("compile",["--check-only"]),("execute",[])]:
            result=subprocess.run(["/usr/bin/sandbox-exec","-p",profile,GODOT,"--headless","--path",str(project),"--script",str(script),"--log-file",str(cache/(stage+".log")),*args],cwd=project,capture_output=True,text=True,timeout=20,env={"PATH":"/usr/bin:/bin","HOME":str(Path.home()),"TMPDIR":str(cache)})
            checks[stage]={"exitCode":result.returncode,"stdout":result.stdout,"stderr":result.stderr}
        checks["sourceUnchanged"]=(project/"source.txt").read_text()=="SOURCE_MUST_STAY_UNCHANGED"
        checks["otherUnchanged"]=sorted(p.name for p in protected.iterdir())==["canary.txt"]
        lines=checks["execute"]["stdout"].splitlines()
        checks["facts"]=[json.loads(x.split("=",1)[1]) for x in lines if x.startswith("STUDIO_BOUNDARY_FACTS=")]
        target = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(5)"], start_new_session=True)
        try:
            signal_code = ("import os,signal\ntry:\n os.kill(" + str(target.pid)
                           + ",signal.SIGTERM)\n print('SIGNAL_ALLOWED')\n"
                           + "except PermissionError:\n print('SIGNAL_DENIED')")
            result = subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, sys.executable,
                                     "-c", signal_code], cwd=project, env={"PATH": "/usr/bin:/bin"},
                                    capture_output=True, text=True, timeout=5)
            checks["externalProcessSignal"] = {"targetPid": target.pid, "exitCode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
                "denied": result.returncode == 0 and "SIGNAL_DENIED" in result.stdout}
        finally:
            target.terminate()
            target.wait(timeout=3)
            checks["externalProcessSignal"]["targetStopped"] = target.poll() is not None
        lint=subprocess.run(["/opt/anaconda3/bin/python","-m","gdtoolkit.linter",str(script)],capture_output=True,text=True)
        checks["gdtoolkit"]={"exitCode":lint.returncode,"stdout":lint.stdout,"stderr":lint.stderr}
    finally:
        canary.unlink(missing_ok=True);v4.close();v6.close()
    Path(sys.argv[1]).write_text(json.dumps(checks,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"evidence":sys.argv[1],"compileExit":checks["compile"]["exitCode"],"facts":checks["facts"]},ensure_ascii=False))

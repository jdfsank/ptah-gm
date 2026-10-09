"""Fail-closed GM v2 adapter. PLAN/GAP remain authority; this is no GM scheduler.

All readiness probes are read-only. Browser context never grants scope. The
pinned local helper validates exact specification identity using GM's own parser.
No command in this module records human decisions or starts a game/test/run.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'tools'))
import git_baseline

V2_FIELDS = {'resolvedTargets', 'diff', 'allowedChangeScope', 'executionIntent',
             'planTags', 'mechanismRefs', 'feedback', 'reviewedSpecDigest', 'reviewedAuthorityDigest'}
FEEDBACK_KEYS = {'id', 'mechanics', 'platform', 'text', 'type', 'source_ref'}
FEEDBACK_TYPES = {'implementation', 'experience', 'design_change', 'test_error', 'capability'}
REQUIRED_SKILLS = {'gm-gdd', 'gm-asset', 'gm-build', 'gm-fixgap', 'gm-verify', 'gm-evaluate'}
ROUTES = {'implementation': 'reproduce -> gm-fixgap -> gm-verify -> gm-evaluate',
          'experience': 'reproduce -> classify against confirmed PLAN -> bounded route',
          'design_change': 'stop writer -> gm-gdd -> human specification confirmation -> dependent implementation',
          'test_error': 'Evaluator owns assertion/scenario/capture repair; workers must not edit e2e/',
          'capability': 'BLOCKED: restore the missing capability before dependent execution'}


# Exact generated-runtime exclusions; configuration, mappings, docs and skills are
# deliberately covered. This is a final-state audit, not an OS write sandbox.
CONTROL_EXCLUDED_DIRS = {'.git', '.godot', '.godotmaker/runs', '.godotmaker/evaluation-runs', '.pytest_cache', 'tools/__pycache__', 'tests/__pycache__', 'test/__pycache__', 'hooks/__pycache__'}
CONTROL_EXCLUDED_FILES = {'.godotmaker/run.lock', '.godotmaker/stage.jsonl',
                          '.godotmaker/latest-review.json', '.godotmaker/evaluation.json'}

def controlled_inventory(root):
    root = Path(root).resolve()
    result = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        rel = Path(current).relative_to(root).as_posix()
        prefix = '' if rel == '.' else rel+'/'
        dirs[:] = [name for name in dirs if prefix+name not in CONTROL_EXCLUDED_DIRS]
        for name in dirs:
            if (Path(current)/name).is_symlink(): raise ValueError('Unreviewed symlink directory in controlled scope')
        for name in sorted(files):
            relative=prefix+name
            if relative in CONTROL_EXCLUDED_FILES: continue
            file=Path(current)/name
            if file.is_symlink() or not file.is_file(): raise ValueError('Unsupported controlled project file: '+relative)
            result[relative]=relative
    return git_baseline.capture_inventory(root, result)

def adapter_baseline():
    base=Path(__file__).resolve().parent.parent
    snapshot=json.loads((base/'dist/adapter-baseline.json').read_text())
    if snapshot.get('sourceManifest')!=json.loads((base/'tools/velvet-source-lock.json').read_text()):
        raise ValueError('Server adapter baseline does not match reviewed source lock')
    return snapshot

def authority_digest(controlled, baseline):
    return git_baseline.identity_bytes(_canonical({'controlledFiles':controlled,'adapterBaseline':baseline}).encode())

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def _content(value):
    value=json.loads(json.dumps(value));value.pop('revision',None)
    for room in value.get('rooms',[]):
        for obj in room.get('objects',[]): obj.pop('changed',None)
    return value

_MISSING=object()
def _net_diff(before,after,path=''):
    if before is not _MISSING and after is not _MISSING and _canonical(before)==_canonical(after): return []
    def keyed(v): return isinstance(v,list) and all(isinstance(x,dict) and isinstance(x.get('id'),str) for x in v) and len({x['id'] for x in v})==len(v)
    if keyed(before) and keyed(after): return _net_diff({x['id']:x for x in before},{x['id']:x for x in after},path)
    if isinstance(before,dict) and isinstance(after,dict):
        result=[]
        for key in sorted(set(before)|set(after)):
            result.extend(_net_diff(before.get(key,_MISSING),after.get(key,_MISSING),path+'/'+key.replace('~','~0').replace('/','~1')))
        return result
    row={'path':path or '/','operation':'add' if before is _MISSING else 'remove' if after is _MISSING else 'replace'}
    if before is not _MISSING: row['before']=before
    if after is not _MISSING: row['after']=after
    parts=[x.replace('~1','/').replace('~0','~') for x in row['path'].split('/')[1:]]
    if len(parts)>1 and parts[0]=='rooms':
        row['targetId']='instance:'+parts[1]+':'+parts[3] if len(parts)>3 and parts[2]=='objects' else ('background:' if len(parts)>2 and parts[2]=='background' else 'scene:')+parts[1]
    elif len(parts)>1 and parts[0]=='behaviorDrafts': row['targetId']='behavior:'+parts[1]
    elif len(parts)>1 and parts[0]=='transitions': row['targetId']='transition:'+parts[1]
    elif parts and parts[0]=='transitions':
        raise ValueError('Transition collection must use unique explicit record IDs; no project fallback')
    else: row['targetId']='project'
    return [row]

def verify_reviewed_diff(payload, baseline):
    if not isinstance(baseline,dict) or not isinstance(payload.get('snapshot'),dict):
        raise ValueError('Server-owned adapter baseline is required to verify diff')
    for snapshot in (baseline,payload['snapshot']):
        validate_transition_records(snapshot.get('transitions',[]))
    before_routes={x['id']:x['sourceExitRef'] for x in baseline.get('transitions',[])}
    after_routes={x['id']:x['sourceExitRef'] for x in payload['snapshot'].get('transitions',[])}
    if before_routes!=after_routes:
        raise ValueError('Derived transition exits are immutable; review a new source baseline to add/remove or rewire exits')
    expected=_net_diff(_content(baseline),_content(payload['snapshot']))
    if sorted(map(_canonical,expected))!=sorted(map(_canonical,payload.get('diff',[]))):
        raise ValueError('Declared diff before/after does not exactly match server baseline and submitted snapshot')


def validate_transition_records(records):
    """Transition identity belongs to an exit, never an array index or project."""
    if not isinstance(records,list): raise ValueError('Transitions must be an ID-keyed array')
    ids=set()
    for record in records:
        if not isinstance(record,dict) or set(record)!={'id','sourceExitRef','config'}:
            raise ValueError('Transition records only contain id, sourceExitRef and config')
        source=record['sourceExitRef']
        if not isinstance(source,dict) or set(source)!={'roomId','exitId'} or any(not isinstance(source[k],str) or not source[k] for k in source):
            raise ValueError('Transition sourceExitRef must identify one room exit')
        expected='route:'+source['roomId']+':'+source['exitId']
        if record['id']!=expected or expected in ids: raise ValueError('Transition IDs must uniquely match sourceExitRef')
        ids.add(expected)
        config=record['config']
        if not isinstance(config,dict) or config.get('mode') not in {'unset','none','preset'}:
            raise ValueError('Invalid transition mode')
        if config['mode']=='preset':
            if set(config)!={'mode','presetId'} or config['presetId'] not in {'black_fade','mask_wipe'}:
                raise ValueError('Unknown transition preset or configuration fields')
        elif set(config)!={'mode'}: raise ValueError('Unset/none transition cannot carry a preset')


def exact_allowed_paths(paths):
    """A reviewed list grants individual files, never directories or patterns."""
    if not isinstance(paths,list) or len(paths)!=len(set(x for x in paths if isinstance(x,str))): return False
    for name in paths:
        if not isinstance(name,str) or not name or '\\' in name or any(c in name for c in '*?[]\0'):
            return False
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or name!=relative.as_posix() or name=='.': return False
        if name in CONTROL_EXCLUDED_FILES or any(name==d or name.startswith(d+'/') for d in CONTROL_EXCLUDED_DIRS): return False
    return True


def transition_source_binding(baseline, route_id):
    """Resolve evidence from server-owned adapter files, never draft references."""
    catalog=json.loads((Path(__file__).resolve().parent.parent/'dist/semantic-data.json').read_text())
    if catalog.get('sourceManifest')!=baseline.get('sourceManifest'):
        raise ValueError('Transition source catalog differs from reviewed adapter baseline')
    records=[x for x in baseline.get('transitions',[]) if x.get('id')==route_id]
    if len(records)!=1: raise ValueError('Transition exit absent from server baseline')
    source=records[0]['sourceExitRef']
    rooms=[x for x in baseline.get('rooms',[]) if x.get('id')==source['roomId']]
    doors=[x for room in rooms for x in room.get('objects',[]) if x.get('id')==source['exitId'] and x.get('kind')=='door' and x.get('origin')=='doors']
    instances=[x for x in catalog.get('instances',[]) if x.get('roomId')==source['roomId'] and x.get('localId')==source['exitId'] and x.get('definitionId')=='env.door']
    if len(doors)!=1 or len(instances)!=1: raise ValueError('Transition exit lacks unique server source door evidence')
    door,instance=doors[0],instances[0]
    entry={'roomId':door.get('target'),'spawnId':door.get('targetSpawn')}
    native=instance.get('sourceRecord',{})
    if native.get('target_room')!=entry['roomId'] or native.get('target_spawn')!=entry['spawnId']:
        raise ValueError('Transition destination differs from source door evidence')
    entrances=[x for room in baseline.get('rooms',[]) if room.get('id')==entry['roomId'] for x in room.get('objects',[]) if x.get('kind')=='spawn' and x.get('id')=='spawn:'+str(entry['spawnId'])]
    if len(entrances)!=1: raise ValueError('Transition destination entry absent from server baseline')
    refs=instance.get('sourceRefs',[]);sources={x['id']:x for x in catalog.get('sources',[])}
    manifest={x['path']:x.get('gitBlob') for x in baseline.get('sourceManifest',[])}
    if not refs or any(ref not in sources or manifest.get(sources[ref].get('path'))!=sources[ref].get('gitBlob') for ref in refs):
        raise ValueError('Transition source references do not match reviewed Git source identities')
    return {'rangeIntent':'single-transition','sourceExitRef':source,'targetEntryRef':entry,'sourceRefs':refs}


def safe_file(root, name):
    root = Path(root).resolve()
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError('Unsafe project-relative path')
    path = root.joinpath(*relative.parts)
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise ValueError('Symlink project content is not supported')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Project path escaped the bound root')
    return path


def validate_v2(p):
    if p.get('allowedChangeScope') != 'reviewed-targets-only' or p.get('executionIntent') != 'review-and-apply':
        raise ValueError('v2 requires bounded reviewed-targets-only review-and-apply intent')
    for key in ('reviewedSpecDigest','reviewedAuthorityDigest'):
        if key not in p or (p[key] is not None and (not isinstance(p[key],str) or not p[key])): raise ValueError('Missing reviewed authority binding: '+key)
    targets = p.get('resolvedTargets')
    if not isinstance(targets, list) or not targets or len(targets) > 300:
        raise ValueError('v2 requires resolved targets')
    ids = [x.get('id') if isinstance(x, dict) else None for x in targets]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError('Target IDs must be explicit and unique')
    if len(p['items']) != len({x['id'] for x in p['items']}) or set(ids) != ({x['id'] for x in p['items']} | {x.get('targetId') for x in p.get('diff',[]) if isinstance(x,dict)}):
        raise ValueError('Resolved targets must exactly match reviewed items')
    if len({item['id'] for item in p['items']})!=len(p['items']): raise ValueError('Conflicting duplicate target instructions')
    for key in ('planTags', 'mechanismRefs'):
        if not isinstance(p.get(key), list) or any(not isinstance(x, str) or not x for x in p[key]) or len(set(p[key])) != len(p[key]):
            raise ValueError('Invalid '+key)
    if not isinstance(p.get('diff'), list) or len(p['diff']) > 10000:
        raise ValueError('Invalid content-based net diff')
    seen = set()
    for change in p['diff']:
        if not isinstance(change, dict) or set(change)-{'targetId','path','operation','before','after'}:
            raise ValueError('Unknown net diff fields')
        if change.get('targetId') not in ids or not isinstance(change.get('path'), str) or not change['path']:
            raise ValueError('Net diff must bind an explicit reviewed target and content path')
        if change.get('operation') not in {'add','remove','replace'}:
            raise ValueError('Unsupported net diff operation')
        if change['operation'] in {'replace','remove'} and 'before' not in change or change['operation'] in {'replace','add'} and 'after' not in change:
            raise ValueError('Net diff is missing before/after evidence')
        if change['operation'] == 'replace' and change.get('before') == change.get('after'):
            raise ValueError('No-op is not a net diff')
        identity = (change['targetId'], change['path'])
        if identity in seen:
            raise ValueError('Duplicate net diff path')
        seen.add(identity)
    if 'feedback' in p:
        f = p['feedback']
        if not isinstance(f, dict) or set(f) != FEEDBACK_KEYS:
            raise ValueError('Feedback requires exactly id, mechanics, platform, text, type, source_ref')
        if not isinstance(f['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', f['id']) or f['type'] not in FEEDBACK_TYPES:
            raise ValueError('Invalid feedback ID/type')
        if not isinstance(f['mechanics'], list) or not f['mechanics'] or any(not isinstance(x,str) or not x for x in f['mechanics']):
            raise ValueError('Invalid feedback mechanics')
        if any(not isinstance(f[k],str) or not f[k].strip() for k in ('platform','text','source_ref')):
            raise ValueError('Missing feedback provenance/text/platform')


# Runs only the reviewed GM read helpers, with bytecode writes off.
READ_SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'tools'))
import review_support as gm
import git_baseline
root = Path(sys.argv[1])
spec = gm.extract_spec(root)
events = gm.read_events(root)
current_spec_git_ref = gm.spec_git_ref(spec, root)
confirmed = any(gm._spec_confirmation_matches(e, spec, current_spec_git_ref, root) for e in events)
status = gm.status(root)
run = None
if status.get('run'):
    run = gm.load_json(gm.safe_child(gm._run_path(root, status['run']['run_id']), 'manifest.json'))
source,tests=gm.inventory(root)
context = {'valid':False,'reportRefs':[],'reason':'No formal check run'}
if run:
    source,tests=gm.inventory(root)
    run_path=gm._run_path(root,run['run_id'])
    current={'spec_digest':spec['spec_digest'],'source_digest':gm.manifest_digest(source),'test_digest':gm.runner_digest(root,tests)}
    identity=gm.safe_child(run_path,'manifest.git')
    integrity=identity.is_file() and identity.read_text().strip()==git_baseline.identity_file(run_path/'manifest.json')
    refs=[]
    for relative,digest in run.get('report_digests',{}).items():
        if not relative.startswith('reports/') or git_baseline.identity_file(gm.safe_child(run_path,relative))!=digest: integrity=False
        refs.append('.godotmaker/runs/'+run['run_id']+'/'+relative)
    context={'valid':run.get('command')=='check' and integrity and all(run.get(k)==v for k,v in current.items()),'reportRefs':refs,'manifestRef':'.godotmaker/runs/'+run['run_id']+'/manifest.json','current':current,'reason':'Formal check, Git metadata/report integrity and exact current identities required'}
print(json.dumps({'tag':spec['tag'],'specDigest':spec['spec_digest'],'specConfirmed':confirmed,'profiles':spec['profiles'],'status':status,'run':run,'runContext':context,'sourceFiles':source,'testFiles':tests,'environment':gm.doctor(root)}))
'''


def verify_tool_versions(root):
    lock = json.loads(Path(__file__).with_name('gm-capability-lock.json').read_text())
    if lock.get('version_scheme') != 'git':
        raise ValueError('Legacy SHA capability lock is BLOCKED; review and migrate it to the Git identity scheme before use')
    files = lock.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Git capability lock has no reviewed files')
    for name in files:
        safe_file(root, name)
    try:
        identities = git_baseline.capture_inventory(root, files)
    except git_baseline.GitBaselineError as exc:
        raise ValueError(f'Missing or unsupported GM skill/tool version: {exc}') from exc
    for name, expected in files.items():
        if identities.get(name) != expected:
            raise ValueError('Missing or unsupported GM skill/tool version: '+name)
    return lock


def local_readiness(root):
    lock = verify_tool_versions(root)
    controlled_before=controlled_inventory(root)
    result = subprocess.run([sys.executable, '-B', '-c', READ_SCRIPT, str(Path(root).resolve())],
                            capture_output=True, text=True, timeout=30, cwd=str(root),
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError('GM read-only readiness probe failed: '+result.stderr[-1500:])
    data = json.loads(result.stdout)
    data['controlledFiles']=controlled_inventory(root)
    if data['controlledFiles']!=controlled_before: raise ValueError('Controlled authority changed during readiness')
    data['frameworkRevision'] = lock['frameworkRevision']
    data['toolFingerprints'] = lock['files']
    return data


def readiness(project_root, codex, thread_id, source_baseline=None):
    checks = []
    result = {'status':'BLOCKED','readOnly':True,'checks':checks,'binding':{'projectRoot':str(project_root) if project_root else None,'threadId':thread_id},'humanRequired':None}
    def check(name, ok, reason):
        checks.append({'name':name,'status':'PASS' if ok else 'BLOCKED','reason':reason})
    if not project_root or not codex:
        check('binding', False, 'Demo/offline mode has no real bound GM project and thread')
        return result
    try:
        state = git_baseline.require_repository(project_root)
        result['repository'] = state
        check('gitRepository', True, 'Bound GM project is inside a Git repository')
        thread = codex.rpc('thread/read', {'threadId':thread_id,'includeTurns':False})['thread']
        state = thread.get('status', {})
        state = state.get('type') if isinstance(state,dict) else state
        check('thread', thread.get('id', thread_id)==thread_id and Path(thread.get('cwd','')).resolve()==Path(project_root).resolve() and state=='idle', 'Bound thread must be idle and match the project root')
        available = codex.rpc('skills/list', {'cwds':[str(project_root)],'forceReload':True})
        names = set()
        for entry in available.get('data', []):
            if Path(entry.get('cwd','')).resolve()==Path(project_root).resolve():
                names.update(s.get('name') for s in entry.get('skills', []) if s.get('enabled',True) and not s.get('error'))
        check('runtimeSkills', REQUIRED_SKILLS <= names, 'Actual bound runtime must expose all required gm-* skills; files alone are insufficient')
        local = local_readiness(project_root)
        result['gm'] = local
        result['adapterBaseline']=adapter_baseline()
        result['authorityDigest']=authority_digest(local['controlledFiles'],result['adapterBaseline'])
        result['scopeAudit']={'coverage':'all project regular files except explicit generated-runtime exclusions','excludedDirectories':sorted(CONTROL_EXCLUDED_DIRS),'excludedFiles':sorted(CONTROL_EXCLUDED_FILES),'semantics':'final-state Git baseline audit; not an operating-system write sandbox'}
        mapping_path = safe_file(project_root, '.godotmaker/workbench-targets.json')
        mappings = json.loads(mapping_path.read_text()) if mapping_path.is_file() else {}
        mapping_valid = mappings.get('version') == 1 and mappings.get('sourceBaseline') == source_baseline and isinstance(mappings.get('targets'), dict) and bool(mappings['targets'])
        check('targetMappings', mapping_valid, 'Server-owned explicit reviewed target map must match the current source baseline')
        result['targetMappings'] = mappings.get('targets', {}) if mapping_valid else {}
        check('toolVersions', lock.get('version_scheme') == 'git', 'All required deployed GM skills/tools match the reviewed Git identities')
        check('plan', bool(local['tag'] and local['specDigest']), 'GM parser validated authoritative PLAN and specification')
        check('writer', not local['status'].get('lock_present') and not local['status'].get('issues'), 'No unresolved GM lock or status inconsistency')
        environment = local.get('environment', {})
        check('environment', environment.get('result')=='PASS', 'Godot doctor is a capability/version probe, not a test pass')
        caps = environment.get('capabilities',{})
        check('testCapabilities', all(caps.get(k,{}).get('available') is True for k in ('python_tests','godot_e2e')), 'Formal check requires Python tests and godot-e2e; no installation attempted')
        check('stableAuthority', controlled_inventory(project_root)==local['controlledFiles'], 'Controlled authority must remain unchanged throughout readiness')
        result['phaseChecks']=[{'name':'specConfirmation','status':'PASS' if local.get('specConfirmed') else 'BLOCKED','reason':'Required before dependent implementation, not read-only design diagnosis/proposal'}]
        if not local.get('specConfirmed'):
            result['humanRequired'] = {'phase':'specification','action':'confirm-spec','reason':'needs_human: current GDD/PLAN specification confirmation','specDigest':local.get('specDigest')}
    except Exception as exc:
        check('capability', False, str(exc))
    if checks and all(c['status']=='PASS' for c in checks):
        result['status'] = 'READY'
    return result


def execution_plan(p, ready):
    """Validate declared mappings against actual authority. Never infer GM IDs."""
    validate_v2(p)
    blockers = [c['reason'] for c in ready.get('checks',[]) if c['status']!='PASS']
    gm = ready.get('gm',{})
    if not p.get('reviewedSpecDigest') or p['reviewedSpecDigest']!=gm.get('specDigest'): blockers.append('Reviewed specification changed; create a new preview')
    if not p.get('reviewedAuthorityDigest') or p['reviewedAuthorityDigest']!=ready.get('authorityDigest'): blockers.append('Reviewed project authority/configuration changed; create a new preview')
    try: verify_reviewed_diff(p,ready.get('adapterBaseline'))
    except (ValueError,TypeError,KeyError) as exc: blockers.append(str(exc))
    plan = gm.get('status',{}).get('task_authorities',{}).get('PLAN.md') or ''
    mechanics = set(re.findall(r'^- \[([^\]]+-M\d+)\]', plan, re.M))
    tasks = set(re.findall(r'^\|\s*((?:R|M|A|C|J)\d+)\s*\|', plan, re.M))
    declared_mechanics, declared_tags = set(), set()
    targets = []
    for target in p['resolvedTargets']:
        mapping = target.get('gm')
        server_target = ready.get('targetMappings', {}).get(target['id'])
        if not isinstance(server_target, dict) or server_target.get('gm') != mapping or server_target.get('kind') != target.get('kind') or server_target.get('routeKind') != target.get('routeKind') or server_target.get('allowedSourcePaths',[]) != target.get('allowedSourcePaths',[]) or server_target.get('allowedDiffPaths',[]) != target.get('allowedDiffPaths',[]):
            blockers.append('Target mapping is absent or differs from server-reviewed mapping: '+target['id']); continue
        paths = server_target.get('allowedDiffPaths')
        if not isinstance(paths,list) or not paths or any(c['path'] not in paths for c in p['diff'] if c['targetId']==target['id']):
            blockers.append('Net diff exceeds server-reviewed target content paths: '+target['id']); continue
        if not isinstance(mapping,dict) or set(mapping) != {'tag','planRef','mechanics','taskIds'}:
            blockers.append('Unknown GM mapping for '+target['id']); continue
        if mapping['tag'] != gm.get('tag') or mapping['planRef'] != 'PLAN.md' or not isinstance(mapping['mechanics'],list) or not mapping['mechanics'] or any(not isinstance(x,str) or not x for x in mapping['mechanics']) or not set(mapping['mechanics']) <= mechanics or not isinstance(mapping['taskIds'],list) or not mapping['taskIds'] or any(not isinstance(x,str) or not x for x in mapping['taskIds']) or not set(mapping['taskIds']) <= tasks:
            blockers.append('Conflicting or unknown PLAN/mechanic/task mapping for '+target['id']); continue
        declared_mechanics.update(mapping['mechanics']); declared_tags.add(mapping['tag'])
        kind = target.get('routeKind')
        route = 'read-only gm-gdd/PLAN design proposal -> specification confirmation' if kind == 'design' else 'gm-asset' if kind == 'art' else 'gm-build' if kind == 'runtime' else None
        if route is None: blockers.append('Unknown target execution kind for '+target['id'])
        allowed_sources=server_target.get('allowedSourcePaths',[])
        if not exact_allowed_paths(allowed_sources) or (kind in {'runtime','art'} and not allowed_sources):
            blockers.append('Missing explicit allowed source-file scope for '+target['id'])
        if target['id'].startswith('transition:') or target.get('kind')=='transition':
            record_id=target['id'].removeprefix('transition:')
            records=p.get('snapshot',{}).get('transitions',[])
            record=next((x for x in records if isinstance(x,dict) and x.get('id')==record_id),None) if isinstance(records,list) else None
            if target.get('kind')!='transition' or not target['id'].startswith('transition:route:') or not record:
                blockers.append('Transition must resolve to an explicit snapshot exit record')
            try:
                actual_binding=transition_source_binding(ready.get('adapterBaseline',{}),record_id)
                if any(server_target.get(field)!=value for field,value in actual_binding.items()):
                    blockers.append('Transition mapping differs from actual server baseline door evidence')
            except (ValueError,KeyError,TypeError,OSError) as exc:
                blockers.append(str(exc))
            for field in ('rangeIntent','sourceExitRef','targetEntryRef','sourceRefs'):
                if field not in server_target or field not in target or target[field]!=server_target[field]:
                    blockers.append('Transition '+field+' differs from server-reviewed source mapping: '+target['id'])
            if target.get('rangeIntent')!='single-transition' or (record and target.get('sourceExitRef')!=record.get('sourceExitRef')):
                blockers.append('Transition exit identity or single-transition scope is invalid')
            entry=target.get('targetEntryRef')
            if not isinstance(entry,dict) or set(entry)!={'roomId','spawnId'} or any(not isinstance(v,str) or not v for v in entry.values()):
                blockers.append('Transition destination must be an explicit reviewed entry')
            refs=target.get('sourceRefs')
            if not isinstance(refs,list) or not refs or any(not isinstance(ref,str) or not ref for ref in refs) or len(refs)!=len(set(refs)):
                blockers.append('Transition requires explicit reviewed source references')
            if record and record.get('config',{}).get('presetId')=='mask_wipe' and kind!='design':
                blockers.append('Mask wipe runtime resource is unbound; only a read-only design proposal is supported')
        planned={'id':target['id'],'route':route,'gm':mapping,'routeKind':kind,'allowedSourcePaths':allowed_sources}
        if target.get('kind')=='transition':
            planned['sourceBinding']={field:server_target.get(field) for field in ('rangeIntent','sourceExitRef','targetEntryRef','sourceRefs')}
        targets.append(planned)
    if set(p['planTags']) != declared_tags or set(p['mechanismRefs']) != declared_mechanics:
        blockers.append('Envelope PLAN/mechanism references conflict with resolved targets')
    if 'feedback' in p:
        feedback = p['feedback']; run = gm.get('run')
        if not isinstance(run,dict) or run.get('command') != 'check' or not run.get('run_id'):
            blockers.append('Feedback needs a real formal check run; smoke/play are not check runs')
        context=gm.get('runContext',{})
        if context.get('valid') is not True or feedback['source_ref'] not in [context.get('manifestRef'),*context.get('reportRefs',[])]:
            blockers.append('Feedback source_ref must cite an actual selected formal-check manifest/report with current exact input identities')
        platforms={x for profile in gm.get('profiles',[]) for x in (profile.get('name'),profile.get('platform'))}
        if feedback['platform'] not in platforms:
            blockers.append('Feedback platform is not an explicit current PLAN profile/platform')
        if not set(feedback['mechanics']) <= declared_mechanics:
            blockers.append('Feedback mechanics are outside reviewed target scope')
        if feedback['type'] == 'capability': blockers.append('Capability feedback remains BLOCKED')

    readonly_design = bool(targets) and (any(t['routeKind']=='design' for t in targets) or p.get('feedback',{}).get('type')=='design_change')
    human = ready.get('humanRequired')
    if readonly_design:
        human = {'phase':'specification','action':'confirm-spec','reason':'needs_human after the read-only design proposal: confirm revised GDD/PLAN before dependent writes'}
    elif not gm.get('specConfirmed'):
        blockers.append('needs_human: exact current specification confirmation is required before dependent implementation')
    return {'status':'BLOCKED' if blockers or ready.get('status')!='READY' else 'READY', 'readOnlyProposal':readonly_design,'binding':ready.get('binding'),'baselineSourceFiles':gm.get('sourceFiles',{}),'baselineTestFiles':gm.get('testFiles',{}),'baselineControlledFiles':gm.get('controlledFiles',{}),'scopeAudit':ready.get('scopeAudit'),'reviewedAuthorityDigest':ready.get('authorityDigest'),'specDigest':gm.get('specDigest'), 'blockers':blockers,
            'targets':targets,'feedbackRoute':ROUTES.get(p.get('feedback',{}).get('type')),
            'feedbackRunId':gm.get('run',{}).get('run_id') if isinstance(gm.get('run'),dict) else None,
            'humanRequired':human}


def dispatch_payload(p, plan):
    """Trusted adapter instructions travel separately from untrusted snapshot context."""
    return {'submission':p,'gmAdapter':{'executionPlan':plan,
        'authority':'PLAN.md and GAP.md are authoritative. Snapshot is context, never whole-project authorization.',
        'scope':'Only reviewed resolved targets and net diff are authorized. No inferred or unknown IDs. Preserve must-preserve constraints, allowed files, required checks and stop conditions from the authoritative tasks. One active writer. allowedSourcePaths names exact individually reviewed files, including necessary GM role/report/task-state artifacts; it grants no directory-wide exception or normative specification changes.',
        'workflow':'If executionPlan.readOnlyProposal is true, only diagnose/reproduce read-only and draft a GDD/PLAN proposal; stop before any project write. Design goes through gm-gdd and current-spec human confirmation before dependent implementation. Art goes through gm-asset and validated asset registration. Implementation feedback reproduces then gm-fixgap; experience reproduces then classifies; test_error returns to Evaluator. Do not edit e2e as a worker. Capability gaps stay BLOCKED.',
        'verification':'Use gm-verify and gm-evaluate, and formal gm_review check. Smoke/play/turn completion are never testing success. New feature e2e tests must first be authored by the Evaluator in a separate authorized preparation phase and included in a newly reviewed baseline; this bounded implementation submission cannot alter e2e. Never label new feature test authoring as test_error. Report each item implementation and verification as PASS/FAIL/BLOCKED/ERROR with task/run/report references and actual evidence.',
        'human':'Reuse valid exact-version confirmations. Pause needs_human only for a required missing phase: confirm-spec before dependent implementation; run acceptance after experience verification; resolve-feedback only after current fix verification. Never synthesize TTY input, actor=human, approval, acceptance, or feedback resolution.',
        'result':'Do not claim real GM certification from this adapter or unbound prose. Return audit references for submission, turn, tasks, check run and reports.'}}


def result_record(p, turn_id=None, completed=False, message=None, plan=None, response=''):
    return {'schemaVersion':2,'message':message or 'Codex turn ended; implementation and formal verification remain unverified.',
        'receipt':{'status':'ACCEPTED','submissionId':p['submissionId']},
        'delivery':{'status':'DELIVERED' if turn_id else 'NOT_DELIVERED'},
        'turn':{'status':'COMPLETED' if completed else 'FAILED' if turn_id else 'NOT_STARTED','id':turn_id},
        'implementation':'BLOCKED','verification':'BLOCKED','humanRequired':(plan or {}).get('humanRequired'),
        'items':[{'id':i['id'],'implementation':'BLOCKED','verification':'BLOCKED','status':'review_required','reason':'No validated per-item implementation or formal GM verification evidence has been ingested.','refs':{'submissionId':p['submissionId'],'turnId':turn_id,'taskIds':next((t['gm']['taskIds'] for t in (plan or {}).get('targets',[]) if t['id']==i['id']),[]),'runId':None,'reportRefs':[]}} for i in p.get('resolvedTargets',p['items'])],
        'refs':{'submissionId':p['submissionId'],'turnId':turn_id,'taskId':p['taskId'],'runId':None,'reportRefs':[]},
        'executionPlan':plan,'response':response,'certified':False}

EVIDENCE_SCRIPT = r'''
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'tools'))
import review_support as gm
import git_baseline
root, run_id = Path(sys.argv[1]), sys.argv[2]
if gm.safe_child(root,'.godotmaker/run.lock').exists(): raise ValueError('An active or unresolved GM writer/run lock blocks evidence import')
run = gm._run_path(root,run_id)
manifest_file = gm.safe_child(run,'manifest.json')
manifest_identity = git_baseline.identity_file(manifest_file)
m = gm.load_json(manifest_file)
if m.get('schema_version')!=1 or m.get('command')!='check' or m.get('run_id')!=run_id: raise ValueError('Only formal schema-v1 check runs are supported')
if gm.safe_child(run,'manifest.git').read_text().strip()!=manifest_identity: raise ValueError('Run manifest Git identity differs')
spec = gm.extract_spec(root)
source, tests = gm.inventory(root)
current = {'spec_digest':spec['spec_digest'],'source_digest':gm.manifest_digest(source),'test_digest':gm.runner_digest(root,tests)}
if m.get('tag')!=spec['tag'] or any(m.get(k)!=v for k,v in current.items()): raise ValueError('Run identities are stale against the actual project')
if gm.inventory(run/'project')!=(m.get('source_files'),m.get('test_files')): raise ValueError('Run snapshot drift')
reports = m.get('report_digests',{})
if not reports: raise ValueError('Run has no report digest evidence')
for relative,digest in reports.items():
    if not relative.startswith('reports/') or git_baseline.identity_file(gm.safe_child(run,relative))!=digest: raise ValueError('Report missing or changed: '+relative)
verification = gm.gate(root,run_id,require_accept=False,locked=True)
acceptance = gm.gate(root,run_id,require_accept=True,locked=True)
task_states = {}
for name in ['PLAN.md','GAP.md']:
    path=gm.safe_child(root,name)
    if path.is_file():
        for line in gm.parse_sections(path.read_text()).get('Task Status',[]):
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            if len(cells)>=3 and cells[2] in {'pending','in_progress','completed','verified','failed'}:
                if cells[0] in task_states and task_states[cells[0]]!=cells[2]: raise ValueError('Conflicting task state')
                task_states[cells[0]]=cells[2]
if gm.inventory(root)!=(source,tests) or gm.extract_spec(root)['spec_digest']!=current['spec_digest'] or git_baseline.identity_file(manifest_file)!=manifest_identity: raise ValueError('Source or specification changed during evidence inspection')
if gm.safe_child(root,'.godotmaker/run.lock').exists(): raise ValueError('Writer appeared during evidence inspection')
print(json.dumps({'manifest':m,'manifestIdentity':manifest_identity,'verificationGate':verification,'acceptanceGate':acceptance,'taskStates':task_states,'current':current,'reportRefs':list(reports),'pendingFeedback':gm.pending_feedback(root,run_id)}))
'''


def inspect_evidence(root, run_id):
    """Independent read-only inspection; never records an approval or changes source."""
    verify_tool_versions(root)
    controlled_before=controlled_inventory(root)
    if not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',run_id) or run_id in {'.','..'}:
        raise ValueError('Invalid formal run ID')
    result = subprocess.run([sys.executable,'-B','-c',EVIDENCE_SCRIPT,str(Path(root).resolve()),run_id],
                            cwd=str(root),capture_output=True,text=True,timeout=120,
                            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},stdin=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError('Independent GM evidence inspection failed: '+result.stderr[-2000:])
    observed=json.loads(result.stdout)
    observed['controlledFiles']=controlled_inventory(root)
    if observed['controlledFiles']!=controlled_before: raise ValueError('Controlled files changed during evidence inspection')
    return observed


def _timestamp(value):
    import datetime
    if not isinstance(value,str): raise ValueError('Missing server/run timestamp binding')
    stamp=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('Evidence timestamp must include timezone')
    return stamp


def ingest_evidence(record, supplied, observed):
    """Bind a local import manifest to independent GM facts, never to model prose.

    supplied only selects exact known references; it cannot assert result status.
    observed must be produced by inspect_evidence, never supplied via HTTP/browser.
    """
    p, prior = record['payload'], record['result']
    if p.get('version')!=2 or record['state'] not in {'succeeded','failed','uncertain'}:
        raise ValueError('Evidence import requires a delivered terminal/uncertain v2 submission')
    required={'schemaVersion','submissionId','turnId','taskId','sourceBaseline','runId','items'}
    if not isinstance(supplied,dict) or set(supplied)!=required or supplied['schemaVersion']!=1:
        raise ValueError('Invalid evidence import envelope')
    turn_id=prior.get('turn',{}).get('id') or prior.get('turnId')
    for key,expected in [('submissionId',p['submissionId']),('turnId',turn_id),('taskId',p['taskId']),('sourceBaseline',p['sourceBaseline'])]:
        if not expected or supplied[key]!=expected: raise ValueError('Evidence binding mismatch: '+key)
    m=observed.get('manifest',{})
    if m.get('command')!='check' or m.get('schema_version')!=1 or m.get('run_id')!=supplied['runId']:
        raise ValueError('Evidence is not the selected formal check run')
    if _timestamp(m.get('started_at')) < _timestamp(prior.get('turnStartedAt')) or _timestamp(m.get('finished_at')) < _timestamp(m.get('started_at')):
        raise ValueError('Check run predates this dispatched turn or has invalid timing')
    expected_targets={t['id']:t for t in prior.get('executionPlan',{}).get('targets',[])}
    if set(expected_targets)!={t['id'] for t in p['resolvedTargets']}:
        raise ValueError('Server execution mapping is missing or incomplete')
    imports=supplied['items']
    if not isinstance(imports,list) or len(imports)!=len(expected_targets) or {i.get('id') for i in imports if isinstance(i,dict)}!=set(expected_targets):
        raise ValueError('Evidence must cover each exact reviewed target once')
    baseline=prior['executionPlan'].get('baselineSourceFiles',{})
    current_sources=m.get('source_files',{})
    if not baseline or not current_sources: raise ValueError('Missing server-observed before/after source inventory')
    changed={name for name in set(baseline)|set(current_sources) if baseline.get(name)!=current_sources.get(name)}
    permitted={name for target in expected_targets.values() for name in target.get('allowedSourcePaths',[])}
    if changed-permitted: raise ValueError('Observed source changes exceed the server-reviewed allowed file scope')
    before_tests=prior['executionPlan'].get('baselineTestFiles',{})
    after_tests=m.get('test_files',{})
    changed_tests={name for name in set(before_tests)|set(after_tests) if before_tests.get(name)!=after_tests.get(name)}
    if changed_tests-permitted: raise ValueError('Observed test changes exceed the reviewed allowed file scope')
    if p.get('feedback',{}).get('type')!='test_error' and any(name.startswith('e2e/') for name in changed_tests): raise ValueError('Only the Evaluator test-error route may change e2e evidence')
    # V2 has no authority to change a normative specification. This holds for
    # art and mixed routes too; a new spec requires a new reviewed baseline.
    if not prior['executionPlan'].get('specDigest') or prior['executionPlan']['specDigest']!=m.get('spec_digest'):
        raise ValueError('Submission changed the normative specification without confirmed scope')
    if prior['executionPlan'].get('readOnlyProposal') and (changed or changed_tests):
        raise ValueError('Read-only proposal changed project source or tests')
    controlled_before=prior['executionPlan'].get('baselineControlledFiles')
    controlled_after=observed.get('controlledFiles')
    if not isinstance(controlled_before,dict) or not controlled_before or not isinstance(controlled_after,dict) or not controlled_after:
        raise ValueError('Missing independent controlled-file baseline/current audit')
    controlled_changes={name for name in set(controlled_before)|set(controlled_after) if controlled_before.get(name)!=controlled_after.get(name)}
    if controlled_changes-permitted: raise ValueError('Controlled document/configuration/skill changes exceed reviewed file scope')
    if prior['executionPlan'].get('readOnlyProposal') and controlled_changes: raise ValueError('Read-only proposal changed controlled project files')
    valid_states={'PASS','FAIL','BLOCKED','ERROR'}
    raw=m.get('result')
    if raw not in valid_states: raise ValueError('Unknown GM result')
    gate=observed.get('verificationGate',{})
    reasons=gate.get('reasons',[])
    nonhuman=[r for r in reasons if not r.startswith('needs_human:') and not r.startswith('Unresolved feedback:')]
    # PASS requires the authoritative gate, allowing only separately shown human
    # phase/feedback-resolution blockers. Failing runs stay failing, never PASS.
    verification='ERROR' if gate.get('result')=='ERROR' else raw
    if raw=='PASS' and (gate.get('result') not in {'PASS','BLOCKED'} or nonhuman):
        verification='ERROR' if gate.get('result')=='ERROR' else 'BLOCKED'
    result=dict(prior)
    rows=[]
    for item in imports:
        if set(item)!={'id','taskIds','reportRefs'}: raise ValueError('Import items only select id/taskIds/reportRefs')
        target=expected_targets[item['id']]
        expected_tasks=list(target['gm']['taskIds'])
        if p.get('feedback',{}).get('type') in {'implementation','experience'}:
            expected_tasks.append('F-'+p['feedback']['id'])
        if item['taskIds']!=expected_tasks or m.get('tag')!=target['gm']['tag']:
            raise ValueError('Evidence task/tag mapping differs from reviewed scope')
        refs=item['reportRefs']
        if not isinstance(refs,list) or not refs or len(refs)!=len(set(refs)) or not set(refs)<=set(observed.get('reportRefs',[])):
            raise ValueError('Report refs must be real Git-metadata-validated reports in the selected run')
        states=[observed.get('taskStates',{}).get(t) for t in item['taskIds']]
        implementation='FAIL' if 'failed' in states else 'BLOCKED'
        rows.append({'id':item['id'],'implementation':implementation,'verification':'BLOCKED',
                     'status':'review_required',
                     'reason':'Global formal check and report membership do not prove target/task/assertion coverage or fulfillment of this exact request. Item-specific verification remains BLOCKED.',
                     'runVerification':verification,
                     'implementationEvidence':{'status':'SOURCE_CHANGED' if changed & set(target.get('allowedSourcePaths',[])) else 'NO_SOURCE_CHANGE','observedSourceChanges':sorted(changed & set(target.get('allowedSourcePaths',[]))),'taskStates':dict(zip(item['taskIds'],states))},
                     'refs':{'submissionId':p['submissionId'],'turnId':turn_id,'taskIds':item['taskIds'],'runId':supplied['runId'],'reportRefs':[f".godotmaker/runs/{supplied['runId']}/{r}" for r in refs]}})
    human=None
    if any(r.startswith('needs_human: current GDD/PLAN') for r in reasons):
        human={'phase':'specification','action':'confirm-spec','reason':'needs_human: confirm current GDD/PLAN before dependent implementation'}
    elif verification=='PASS' and observed.get('taskStates',{}).get('F-'+p.get('feedback',{}).get('id',''))=='verified' and any(i.get('id')==p.get('feedback',{}).get('id') for i in observed.get('pendingFeedback',[])):
        human={'phase':'feedback_resolution','action':'resolve-feedback','reason':'needs_human: confirm feedback addressed after current fix verification','runId':supplied['runId'],'feedbackId':p['feedback']['id']}
    elif verification=='PASS' and not observed.get('pendingFeedback') and observed.get('acceptanceGate',{}).get('result')!='PASS':
        human={'phase':'experience_acceptance','action':'decision','reason':'needs_human: review required platform/experience evidence before accepting this exact run','runId':supplied['runId']}
    def worst(values):
        return next((s for s in ('ERROR','FAIL','BLOCKED','PASS') if s in values),'BLOCKED')
    result.update(schemaVersion=2,items=rows,implementation=worst([r['implementation'] for r in rows]),verification=verification,
                  humanRequired=human,certified=False,
                  message='Imported independently checked GM task/run/report evidence. Delivery, verification and human acceptance are separate.',
                  refs={'submissionId':p['submissionId'],'turnId':turn_id,'taskId':p['taskId'],'runId':supplied['runId'],'reportRefs':sorted({ref for row in rows for ref in row['refs']['reportRefs']})},
                  evidence={'manifestIdentity':observed.get('manifestIdentity'),'verificationGate':gate,'acceptanceGate':observed.get('acceptanceGate'),'current':observed.get('current'),'controlledFileChanges':sorted(controlled_changes),'scopeAudit':prior['executionPlan'].get('scopeAudit')})
    return result

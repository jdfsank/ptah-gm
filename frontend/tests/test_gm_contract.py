"""No GM execution, model inference, approvals or sockets: contract regression tests."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bridge'))
import gm_contract as gm

MAPPING = {'tag':'v0.1.0','planRef':'PLAN.md','mechanics':['v0.1.0-M1'],'taskIds':['R1']}

def payload():
    return {'version':2,'reviewedSpecDigest':'spec-fixture','reviewedAuthorityDigest':'authority-fixture','snapshot':{'revision':1,'rooms':[],'behaviorDrafts':{'player.move':{'speed':120}}},'taskId':'velvet-eclipse','submissionId':'submission-2','items':[{'id':'behavior:player.move','instruction':'Change reviewed speed.'}],
            'resolvedTargets':[{'id':'behavior:player.move','kind':'behavior','routeKind':'runtime','allowedSourcePaths':['data/player.json'],'allowedDiffPaths':['/behaviorDrafts/player.move/speed'],'gm':copy.deepcopy(MAPPING)}],
            'diff':[{'targetId':'behavior:player.move','path':'/behaviorDrafts/player.move/speed','operation':'replace','before':100,'after':120}],
            'allowedChangeScope':'reviewed-targets-only','executionIntent':'review-and-apply','planTags':['v0.1.0'],'mechanismRefs':['v0.1.0-M1']}

def ready():
    return {'status':'READY','authorityDigest':'authority-fixture','adapterBaseline':{'revision':0,'rooms':[],'behaviorDrafts':{'player.move':{'speed':100}}},'checks':[{'status':'PASS','reason':'test fixture only'}],'targetMappings':{'behavior:player.move':{'kind':'behavior','routeKind':'runtime','gm':copy.deepcopy(MAPPING),'allowedDiffPaths':['/behaviorDrafts/player.move/speed'],'allowedSourcePaths':['data/player.json']}},
            'gm':{'controlledFiles':{'data/player.json':'sha256:before'},'specDigest':'spec-fixture','sourceFiles':{'data/player.json':'sha256:before'},'testFiles':{},'profiles':[{'name':'native','platform':'native'}],'runContext':{'valid':True,'manifestRef':'.godotmaker/runs/check-1/manifest.json','reportRefs':[]},'specConfirmed':True,'tag':'v0.1.0','status':{'task_authorities':{'PLAN.md':'## Tag Mechanics\n- [v0.1.0-M1] Move\n## Task Status\n| R1 | movement | verified |'}},'run':{'command':'check','run_id':'check-1'}}}

class EnvelopeTests(unittest.TestCase):
    def test_explicit_bounded_v2(self):
        gm.validate_v2(payload())
        self.assertEqual(gm.execution_plan(payload(),ready())['status'],'READY')

    def test_snapshot_is_context_not_scope(self):
        p=payload();p['snapshot']={'everything':'rewrite it all'}
        p['diff'][0]['path']='objects.boss.health'
        self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')

    def test_unknown_mapping_and_forged_known_mechanism_block(self):
        for mapping in (None, {**MAPPING,'mechanics':['v0.1.0-M7']}, {**MAPPING,'taskIds':['UNKNOWN']}):
            p=payload();p['resolvedTargets'][0]['gm']=mapping
            self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')

    def test_conflicting_top_level_references_block(self):
        for key,value in [('planTags',['v9.0.0']),('mechanismRefs',['v0.1.0-M9'])]:
            p=payload();p[key]=value
            self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')

    def test_unreviewed_target_duplicate_diff_and_noop_rejected(self):
        variants=[]
        p=payload();p['diff'][0]['targetId']='other';variants.append(p)
        p=payload();p['diff'].append(copy.deepcopy(p['diff'][0]));variants.append(p)
        p=payload();p['diff'][0]['after']=100;variants.append(p)
        p=payload();p['resolvedTargets'].append(copy.deepcopy(p['resolvedTargets'][0]));variants.append(p)
        p=payload();p['allowedChangeScope']='whole-project';variants.append(p)
        for p in variants:
            with self.assertRaises(ValueError):gm.validate_v2(p)

    def feedback(self, kind='implementation'):
        return {'id':'report-1','mechanics':['v0.1.0-M1'],'platform':'native','text':'Movement is wrong','type':kind,'source_ref':'.godotmaker/runs/check-1/manifest.json'}

    def test_feedback_exact_six_keys(self):
        p=payload();p['feedback']=self.feedback();gm.validate_v2(p)
        p['feedback']['run_id']='invented'
        with self.assertRaises(ValueError):gm.validate_v2(p)

    def test_feedback_missing_or_smoke_run_blocks(self):
        p=payload();p['feedback']=self.feedback()
        for run in (None, {'command':'smoke','run_id':'smoke-1'}, {'command':'play','run_id':'play-1'}):
            r=ready();r['gm']['run']=run
            self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED')

    def test_all_feedback_routes_are_distinct(self):
        for kind in gm.FEEDBACK_TYPES:
            p=payload();p['feedback']=self.feedback(kind)
            plan=gm.execution_plan(p,ready())
            self.assertEqual(plan['feedbackRoute'],gm.ROUTES[kind])
            self.assertEqual(plan['status'],'BLOCKED' if kind in {'capability'} else 'READY')

    def test_design_and_art_route_to_original_skills(self):
        for kind,route in [('design','gm-gdd'),('art','gm-asset')]:
            p=payload();p['resolvedTargets'][0]['routeKind']=kind;r=ready();r['targetMappings']['behavior:player.move']['routeKind']=kind
            self.assertIn(route,gm.execution_plan(p,r)['targets'][0]['route'])

class ReadinessTests(unittest.TestCase):
    def test_demo_is_not_real_gm(self):
        r=gm.readiness(None,None,'demo-local')
        self.assertEqual(r['status'],'BLOCKED');self.assertTrue(r['readOnly'])

    def test_no_missing_tool_install_or_execution(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(gm.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'Missing or unsupported'):gm.local_readiness(d)
            run.assert_not_called()

    def test_wrong_thread_cwd_and_absent_runtime_skills_block(self):
        codex=SimpleNamespace(rpc=mock.Mock(side_effect=[{'thread':{'id':'t','cwd':'/wrong','status':{'type':'idle'}}},{'data':[]}]))
        with mock.patch.object(gm,'local_readiness',side_effect=ValueError('missing tools')):
            r=gm.readiness('/bound',codex,'t')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual([c.args[0] for c in codex.rpc.call_args_list],['thread/read','skills/list'])
        self.assertNotIn('turn/start',str(codex.rpc.call_args_list))

    def test_parent_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):gm.safe_file(d,'../outside')
            Path(d,'link').symlink_to('/tmp')
            with self.assertRaises(ValueError):gm.safe_file(d,'link/file')

class OutcomeTests(unittest.TestCase):
    def test_completed_turn_does_not_prove_implementation_or_testing(self):
        p=payload();r=gm.result_record(p,'turn-1',True,response='Everything passed!')
        self.assertEqual(r['delivery']['status'],'DELIVERED');self.assertEqual(r['turn']['status'],'COMPLETED')
        self.assertEqual(r['verification'],'BLOCKED');self.assertEqual(r['implementation'],'BLOCKED');self.assertFalse(r['certified'])
        self.assertEqual(r['items'][0]['refs']['turnId'],'turn-1')

    def test_human_gate_phase_is_preserved(self):
        plan={'humanRequired':{'phase':'specification','action':'confirm-spec','reason':'needs_human'}}
        result=gm.result_record(payload(),plan=plan)
        self.assertEqual(result['humanRequired'],plan['humanRequired'])
        self.assertEqual(result['turn']['status'],'NOT_STARTED')

    def test_dispatch_explicitly_forbids_approval_impersonation(self):
        d=gm.dispatch_payload(payload(),gm.execution_plan(payload(),ready()))
        self.assertIn('Never synthesize TTY input',d['gmAdapter']['human'])
        self.assertIn('context, never whole-project',d['gmAdapter']['authority'])

if __name__=='__main__':unittest.main()

class EvidenceImportTests(unittest.TestCase):
    def fixture(self):
        p=payload();p['sourceBaseline']='submitted-source-baseline'
        plan=gm.execution_plan(p,ready())
        prior=gm.result_record(p,'turn-1',True,plan=plan)
        prior['turnStartedAt']='2026-10-08T01:00:00+00:00'
        record={'payload':p,'result':prior,'state':'succeeded'}
        supplied={'schemaVersion':1,'submissionId':p['submissionId'],'turnId':'turn-1','taskId':p['taskId'],'sourceBaseline':p['sourceBaseline'],'runId':'check-2','items':[{'id':'behavior:player.move','taskIds':['R1'],'reportRefs':['reports/verify.json']}]}
        observed={'controlledFiles':{'data/player.json':'sha256:after'},'manifest':{'schema_version':1,'command':'check','run_id':'check-2','tag':'v0.1.0','spec_digest':'spec-fixture','source_files':{'data/player.json':'sha256:after'},'started_at':'2026-10-08T01:01:00+00:00','finished_at':'2026-10-08T01:02:00+00:00','result':'PASS'},'verificationGate':{'result':'PASS','reasons':[]},'acceptanceGate':{'result':'BLOCKED','reasons':['needs_human: current run has no applicable user acceptance']},'reportRefs':['reports/verify.json'],'taskStates':{'R1':'verified'},'pendingFeedback':[],'manifestHash':'sha256:fixture'}
        return record,supplied,observed

    def test_pass_evidence_keeps_human_acceptance_separate(self):
        r,s,o=self.fixture();result=gm.ingest_evidence(r,s,o)
        self.assertEqual(result['implementation'],'BLOCKED');self.assertEqual(result['verification'],'PASS')
        self.assertEqual(result['humanRequired']['phase'],'experience_acceptance')
        self.assertEqual(result['refs']['runId'],'check-2');self.assertFalse(result['certified'])

    def test_existing_exact_acceptance_is_reused(self):
        r,s,o=self.fixture();o['acceptanceGate']={'result':'PASS','reasons':[]}
        self.assertIsNone(gm.ingest_evidence(r,s,o)['humanRequired'])

    def test_claimed_status_cannot_be_imported(self):
        r,s,o=self.fixture();s['items'][0]['status']='PASS'
        with self.assertRaises(ValueError):gm.ingest_evidence(r,s,o)

    def test_wrong_submission_turn_baseline_run_or_task_rejected(self):
        for key in ('submissionId','turnId','taskId','sourceBaseline','runId'):
            r,s,o=self.fixture();s[key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):gm.ingest_evidence(r,s,o)
        r,s,o=self.fixture();s['items'][0]['taskIds']=['M09']
        with self.assertRaises(ValueError):gm.ingest_evidence(r,s,o)

    def test_old_run_and_smoke_cannot_certify_this_turn(self):
        for changes in ({'started_at':'2026-10-08T00:59:00+00:00'},{'command':'smoke'}):
            r,s,o=self.fixture();o['manifest'].update(changes)
            with self.assertRaises(ValueError):gm.ingest_evidence(r,s,o)

    def test_missing_raw_report_reference_rejected(self):
        r,s,o=self.fixture();s['items'][0]['reportRefs']=['reports/imagined.json']
        with self.assertRaises(ValueError):gm.ingest_evidence(r,s,o)

    def test_fail_error_blocked_stay_distinct(self):
        for status in ('FAIL','ERROR','BLOCKED'):
            r,s,o=self.fixture();o['manifest']['result']=status;o['verificationGate']={'result':'BLOCKED','reasons':['Required evidence not PASS']}
            self.assertEqual(gm.ingest_evidence(r,s,o)['verification'],status)

    def test_zero_cases_or_missing_evidence_never_becomes_pass(self):
        r,s,o=self.fixture();o['verificationGate']={'result':'BLOCKED','reasons':['Raw E2E evidence is empty, duplicate or not PASS']}
        self.assertEqual(gm.ingest_evidence(r,s,o)['verification'],'BLOCKED')

    def test_unverified_task_does_not_become_implementation_pass(self):
        r,s,o=self.fixture();o['taskStates']['R1']='completed'
        self.assertEqual(gm.ingest_evidence(r,s,o)['implementation'],'BLOCKED')

    def test_feedback_resolution_waits_for_verified_gap_and_pass(self):
        r,s,o=self.fixture();r['payload']['feedback']={'id':'feedback-1','type':'implementation'}
        s['items'][0]['taskIds'].append('F-feedback-1');o['pendingFeedback']=[{'id':'feedback-1'}]
        o['verificationGate']={'result':'BLOCKED','reasons':['Unresolved feedback: feedback-1']}
        blocked=gm.ingest_evidence(r,s,o)
        self.assertEqual(blocked['implementation'],'BLOCKED');self.assertIsNone(blocked['humanRequired'])
        o['taskStates']['F-feedback-1']='verified'
        self.assertEqual(gm.ingest_evidence(r,s,o)['humanRequired']['phase'],'feedback_resolution')

class PhaseAndScopeTests(unittest.TestCase):
    def test_notes_and_diff_union_is_authorized_not_whole_snapshot(self):
        p=payload();p['items']=[]
        gm.validate_v2(p)
        result=gm.result_record(p)
        self.assertEqual([i['id'] for i in result['items']],['behavior:player.move'])

    def test_readonly_design_proposal_can_precede_spec_confirmation(self):
        p=payload();p['resolvedTargets'][0]['routeKind']='design';r=ready();r['gm']['specConfirmed']=False;r['targetMappings']['behavior:player.move']['routeKind']='design'
        plan=gm.execution_plan(p,r)
        self.assertEqual(plan['status'],'READY');self.assertTrue(plan['readOnlyProposal']);self.assertEqual(plan['humanRequired']['phase'],'specification')

    def test_runtime_implementation_waits_for_spec_confirmation(self):
        r=ready();r['gm']['specConfirmed']=False
        self.assertEqual(gm.execution_plan(payload(),r)['status'],'BLOCKED')

class AdversarialResultTests(unittest.TestCase):
    def test_stale_verified_task_fresh_global_check_not_item_completion(self):
        r,s,o=EvidenceImportTests().fixture()
        o['manifest']['source_files']={'data/player.json':'sha256:before'}
        result=gm.ingest_evidence(r,s,o)
        self.assertEqual(result['verification'],'PASS')
        self.assertEqual(result['implementation'],'BLOCKED')
        self.assertEqual(result['items'][0]['implementationEvidence']['status'],'NO_SOURCE_CHANGE')

    def test_arbitrary_allowed_file_change_is_not_semantic_completion(self):
        r,s,o=EvidenceImportTests().fixture()
        result=gm.ingest_evidence(r,s,o)
        self.assertEqual(result['items'][0]['implementationEvidence']['status'],'SOURCE_CHANGED')
        self.assertEqual(result['implementation'],'BLOCKED')

    def test_unrelated_source_change_rejected(self):
        r,s,o=EvidenceImportTests().fixture();o['manifest']['source_files']['scripts/unrelated.gd']='sha256:new'
        with self.assertRaisesRegex(ValueError,'exceed'):gm.ingest_evidence(r,s,o)

    def test_external_or_stale_feedback_citation_blocks(self):
        for ref in ['https://example.com/report','.godotmaker/runs/old/manifest.json']:
            p=payload();p['feedback']=EnvelopeTests().feedback();p['feedback']['source_ref']=ref
            self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')

class TestOwnershipTests(unittest.TestCase):
    def test_worker_cannot_modify_evaluator_owned_e2e(self):
        r,s,o=EvidenceImportTests().fixture()
        r['result']['executionPlan']['targets'][0]['allowedSourcePaths'].append('e2e/test_play.py')
        o['manifest']['test_files']={'e2e/test_play.py':'sha256:weakened'}
        with self.assertRaisesRegex(ValueError,'Evaluator'):gm.ingest_evidence(r,s,o)

class IndependentReviewRegressionTests(unittest.TestCase):
    def test_readonly_proposal_cannot_change_source_or_tests(self):
        r,s,o=EvidenceImportTests().fixture();r['result']['executionPlan']['readOnlyProposal']=True
        with self.assertRaisesRegex(ValueError,'Read-only'):gm.ingest_evidence(r,s,o)
        r,s,o=EvidenceImportTests().fixture();r['result']['executionPlan']['readOnlyProposal']=True
        o['manifest']['source_files']=dict(r['result']['executionPlan']['baselineSourceFiles'])
        r['result']['executionPlan']['targets'][0]['allowedSourcePaths'].append('test/test_move.gd')
        o['manifest']['test_files']={'test/test_move.gd':'after'}
        with self.assertRaisesRegex(ValueError,'Read-only'):gm.ingest_evidence(r,s,o)

    def test_art_design_and_mixed_routes_cannot_drift_spec(self):
        for routes in [('art',),('design',),('runtime','art'),('runtime','design')]:
            r,s,o=EvidenceImportTests().fixture();targets=r['result']['executionPlan']['targets'];targets[0]['routeKind']=routes[0]
            if len(routes)>1:
                target=copy.deepcopy(targets[0]);target['id']='object:actor.player';target['routeKind']=routes[1];targets.append(target)
                r['payload']['resolvedTargets'].append({'id':target['id']})
                item=copy.deepcopy(s['items'][0]);item['id']=target['id'];s['items'].append(item)
            o['manifest']['spec_digest']='CHANGED-NORMATIVE-SPEC'
            with self.subTest(routes=routes),self.assertRaisesRegex(ValueError,'normative specification'):gm.ingest_evidence(r,s,o)

    def test_global_run_and_unrelated_log_never_mark_item_verified(self):
        r,s,o=EvidenceImportTests().fixture();s['items'][0]['reportRefs']=['reports/unrelated.stdout.log'];o['reportRefs']=['reports/unrelated.stdout.log']
        result=gm.ingest_evidence(r,s,o)
        self.assertEqual(result['verification'],'PASS')
        self.assertEqual(result['items'][0]['verification'],'BLOCKED')
        self.assertEqual(result['items'][0]['status'],'review_required')
        self.assertEqual(result['items'][0]['runVerification'],'PASS')

class AuthorityAndDiffReviewTests(unittest.TestCase):
    def test_spec_and_authority_races_block_old_review(self):
        for field in ['reviewedSpecDigest','reviewedAuthorityDigest']:
            p=payload();p[field]='old-review'
            self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')

    def test_declared_diff_requires_actual_before_and_snapshot_after(self):
        variants=[]
        p=payload();p['diff'][0]['before']=99;variants.append(p)
        p=payload();p['diff'][0]['after']=999;variants.append(p)
        p=payload();p['snapshot']['behaviorDrafts']['player.move']['speed']=999;variants.append(p)
        p=payload();p['snapshot']['extraUnreviewed']='change';variants.append(p)
        for p in variants:
            self.assertEqual(gm.execution_plan(p,ready())['status'],'BLOCKED')
        r=ready();r.pop('adapterBaseline')
        self.assertEqual(gm.execution_plan(payload(),r)['status'],'BLOCKED')

    def test_unreviewed_docs_config_mapping_and_skill_drift_rejected(self):
        for name in ['README.md','docs/note.md','PLAN.md','GAP.md','.godotmaker/config.yaml','.godotmaker/workbench-targets.json','.agents/skills/gm-gdd/SKILL.md']:
            r,s,o=EvidenceImportTests().fixture();o['controlledFiles'][name]='changed'
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Controlled'):gm.ingest_evidence(r,s,o)

    def test_readonly_proposal_rejects_even_permitted_document_edits(self):
        r,s,o=EvidenceImportTests().fixture();plan=r['result']['executionPlan'];plan['readOnlyProposal']=True
        o['manifest']['source_files']=dict(plan['baselineSourceFiles']);o['controlledFiles']=dict(plan['baselineControlledFiles'])
        plan['targets'][0]['allowedSourcePaths'].append('docs/proposal.md');o['controlledFiles']['docs/proposal.md']='new'
        with self.assertRaisesRegex(ValueError,'Read-only'):gm.ingest_evidence(r,s,o)

    def test_inventory_covers_excluded_gm_authority_but_only_skips_named_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            names=['README.md','docs/note.md','.godotmaker/config.yaml','.godotmaker/workbench-targets.json','.agents/skills/gm-gdd/SKILL.md','.godotmaker/feedback/F1.json','.godotmaker/runs/run/manifest.json','.godot/imported/foo','.git/index','.godotmaker/latest-review.json']
            for name in names:
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('x')
            files=gm.controlled_inventory(root)
            for name in names[:6]:self.assertIn(name,files)
            for name in names[6:]:self.assertNotIn(name,files)

class LastMomentDispatchTests(unittest.TestCase):
    def test_authority_change_after_thread_read_cannot_start_turn(self):
        import server
        codex=server.Codex.__new__(server.Codex);codex.cwd='/fixture';codex.thread='fixture';codex.gm_plan={'baselineControlledFiles':{'PLAN.md':'before'}}
        codex.rpc=mock.Mock(return_value={'thread':{'status':{'type':'idle'}}})
        with mock.patch.object(gm,'controlled_inventory',return_value={'PLAN.md':'after'}):
            with self.assertRaisesRegex(server.Conflict,'before dispatch'):codex.submit(payload(),mock.Mock())
        self.assertEqual([call.args[0] for call in codex.rpc.call_args_list],['thread/read'])

class TransitionScopeTests(unittest.TestCase):
    def fixture(self):
        p,r=payload(),ready()
        r['adapterBaseline']=gm.adapter_baseline()
        p['snapshot']=copy.deepcopy(r['adapterBaseline']);p['snapshot']['revision']=1
        record=p['snapshot']['transitions'][0]
        record['config']={'mode':'none'}
        binding=gm.transition_source_binding(r['adapterBaseline'],record['id'])
        target={'id':'transition:'+record['id'],'kind':'transition','routeKind':'runtime',**binding,
                'gm':copy.deepcopy(MAPPING),
                'allowedDiffPaths':['/transitions/'+record['id']+'/config/mode'],
                'allowedSourcePaths':['scripts/runtime/game_runtime.gd','.godotmaker/current_role','.godotmaker/verify_report.json','PLAN.md']}
        p['items']=[{'id':target['id'],'instruction':'Explicitly disable this exit transition.'}]
        p['resolvedTargets']=[target]
        p['diff']=gm._net_diff(gm._content(r['adapterBaseline']),gm._content(p['snapshot']))
        r['targetMappings']={target['id']:{k:copy.deepcopy(v) for k,v in target.items() if k!='id'}}
        return p,r

    def test_transition_net_diff_resolves_single_target_without_project_fallback(self):
        p,r=self.fixture()
        self.assertEqual(p['diff'][0]['targetId'],'transition:route:grand_lobby:to_gallery')
        self.assertEqual(gm.execution_plan(p,r)['status'],'READY')
        self.assertNotIn('project',[x['targetId'] for x in p['diff']])

    def test_missing_or_forged_exit_entry_refs_and_scope_fail_closed(self):
        for field in ('sourceExitRef','targetEntryRef','sourceRefs','rangeIntent'):
            p,r=self.fixture();p['resolvedTargets'][0].pop(field)
            self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED',field)
            p,r=self.fixture();p['resolvedTargets'][0][field]='forged'
            self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED',field)
        p,r=self.fixture();r['targetMappings']={}
        self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED')

    def test_transition_unknown_ids_malformed_collection_and_preset_rejected(self):
        p,r=self.fixture()
        variants=[{}, [p['snapshot']['transitions'][0]]*2,
                  [{'id':'invented','sourceExitRef':{'roomId':'lobby','exitId':'door-gallery'},'config':{'mode':'none'}}],
                  [{'id':'route:lobby:door-gallery','sourceExitRef':{'roomId':'lobby','exitId':'door-gallery'},'config':{'mode':'none','presetId':'black_fade'}}],
                  [{'id':'route:lobby:door-gallery','sourceExitRef':{'roomId':'lobby','exitId':'door-gallery'},'config':{'mode':'preset','presetId':'arbitrary_shader'}}]]
        for records in variants:
            q=copy.deepcopy(p);q['snapshot']['transitions']=records
            self.assertEqual(gm.execution_plan(q,r)['status'],'BLOCKED')
        with self.assertRaisesRegex(ValueError,'no project fallback'):
            gm._net_diff([],{'unkeyed':'transition'},'/transitions')

    def test_transition_cannot_forge_allowed_file_scope(self):
        p,r=self.fixture();p['resolvedTargets'][0]['allowedSourcePaths'].append('scripts/unrelated.gd')
        self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED')

    def test_scope_is_exact_files_never_directories_patterns_or_excluded_artifacts(self):
        for invalid in ['.godotmaker/','../PLAN.md','./PLAN.md','scripts/*.gd','.git/config','.godot/imported/a','.godotmaker/stage.jsonl','a\\b']:
            p,r=self.fixture()
            p['resolvedTargets'][0]['allowedSourcePaths']=[invalid]
            r['targetMappings'][p['resolvedTargets'][0]['id']]['allowedSourcePaths']=[invalid]
            self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED',invalid)

class ControlledWorkflowEvidenceTests(unittest.TestCase):
    def test_real_file_inventory_allows_only_reviewed_gm_artifacts(self):
        record,supplied,observed=EvidenceImportTests().fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,content in {'data/player.json':'before','PLAN.md':'task completed','.godotmaker/current_role':'build','.godotmaker/verify_report.json':'old'}.items():
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(content)
            before=gm.controlled_inventory(root)
            plan=record['result']['executionPlan'];plan['baselineControlledFiles']=before
            plan['baselineSourceFiles']={'data/player.json':before['data/player.json']}
            plan['targets'][0]['allowedSourcePaths']=['data/player.json','PLAN.md','.godotmaker/current_role','.godotmaker/verify_report.json']
            for name,content in {'data/player.json':'after','PLAN.md':'task verified','.godotmaker/current_role':'verify','.godotmaker/verify_report.json':'new'}.items(): (root/name).write_text(content)
            observed['controlledFiles']=gm.controlled_inventory(root)
            observed['manifest']['source_files']={'data/player.json':observed['controlledFiles']['data/player.json']}
            result=gm.ingest_evidence(record,supplied,observed)
            self.assertEqual(result['implementation'],'BLOCKED')
            self.assertEqual(set(result['evidence']['controlledFileChanges']),set(plan['targets'][0]['allowedSourcePaths']))
            (root/'.godotmaker/config.yaml').write_text('unreviewed: true')
            observed['controlledFiles']=gm.controlled_inventory(root)
            with self.assertRaisesRegex(ValueError,'Controlled'):gm.ingest_evidence(record,supplied,observed)

    def test_evaluator_tests_prepared_in_separate_baseline_remain_immutable(self):
        record,supplied,observed=EvidenceImportTests().fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);test=root/'e2e/test_transition.py';test.parent.mkdir();test.write_text('def test_transition():\n    assert True\n')
            files=gm.controlled_inventory(root);digest=files['e2e/test_transition.py']
            plan=record['result']['executionPlan'];plan['baselineTestFiles']={'e2e/test_transition.py':digest}
            plan['baselineControlledFiles'].update(files);observed['controlledFiles'].update(files)
            observed['manifest']['test_files']={'e2e/test_transition.py':digest}
            self.assertEqual(gm.ingest_evidence(record,supplied,observed)['items'][0]['verification'],'BLOCKED')
            test.write_text('def test_transition():\n    pass\n');changed=gm.controlled_inventory(root)
            plan['targets'][0]['allowedSourcePaths'].append('e2e/test_transition.py')
            observed['manifest']['test_files']=changed;observed['controlledFiles'].update(changed)
            with self.assertRaisesRegex(ValueError,'Evaluator'):gm.ingest_evidence(record,supplied,observed)

class TransitionBaselineTests(unittest.TestCase):
    def test_derived_exits_cannot_be_deleted_or_added_inside_submission(self):
        for records in ([], [{'id':'route:other:door','sourceExitRef':{'roomId':'other','exitId':'door'},'config':{'mode':'none'}}]):
            p,r=TransitionScopeTests().fixture();p['snapshot']['transitions']=records
            with self.assertRaisesRegex(ValueError,'immutable'):gm.verify_reviewed_diff(p,r['adapterBaseline'])

    def test_reviewed_source_binding_is_retained_in_execution_plan(self):
        p,r=TransitionScopeTests().fixture();plan=gm.execution_plan(p,r)
        self.assertEqual(plan['status'],'READY')
        binding=plan['targets'][0]['sourceBinding']
        self.assertEqual(binding['sourceExitRef'],{'roomId':'grand_lobby','exitId':'to_gallery'})
        self.assertEqual(binding['targetEntryRef'],{'roomId':'card_banquet_gallery','spawnId':'from_lobby'})
        self.assertEqual(binding['sourceRefs'],gm.transition_source_binding(r['adapterBaseline'],p['snapshot']['transitions'][0]['id'])['sourceRefs'])

class TransitionIndependentSourceTests(unittest.TestCase):
    def test_matching_forged_payload_and_map_cannot_replace_server_source_refs(self):
        for field,value in [('sourceRefs',['source:forged']),('targetEntryRef',{'roomId':'quiet_save_room','spawnId':'from_lobby'}),('sourceExitRef',{'roomId':'grand_lobby','exitId':'invented'})]:
            p,r=TransitionScopeTests().fixture();target=p['resolvedTargets'][0]
            target[field]=value;r['targetMappings'][target['id']][field]=copy.deepcopy(value)
            self.assertEqual(gm.execution_plan(p,r)['status'],'BLOCKED',field)

    def test_unbound_mask_cannot_execute_despite_explicit_mapping(self):
        p,r=TransitionScopeTests().fixture();record=p['snapshot']['transitions'][0]
        record['config']={'mode':'preset','presetId':'mask_wipe'}
        p['diff']=gm._net_diff(gm._content(r['adapterBaseline']),gm._content(p['snapshot']))
        paths=[x['path'] for x in p['diff']]
        p['resolvedTargets'][0]['allowedDiffPaths']=paths
        r['targetMappings'][p['resolvedTargets'][0]['id']]['allowedDiffPaths']=paths
        plan=gm.execution_plan(p,r)
        self.assertEqual(plan['status'],'BLOCKED')
        self.assertTrue(any('Mask wipe' in x for x in plan['blockers']))
        p['resolvedTargets'][0]['routeKind']='design'
        r['targetMappings'][p['resolvedTargets'][0]['id']]['routeKind']='design'
        self.assertEqual(gm.execution_plan(p,r)['status'],'READY')

"""Operator supplied candidate screenshots with immutable provenance labels."""
import copy


class CandidateVisuals:
    def candidate_visual_context(self, project_id, candidate_id):
        from .coordinator import WorkflowError
        self._get('project', project_id)
        job = next((j for j in self._all_project('job', project_id)
                    if (j.get('candidate') or {}).get('id') == candidate_id), None)
        if not job:
            raise WorkflowError(404, 'NOT_FOUND', '此项目没有对应候选。')
        packet = self._get('packet', job['packetId'])
        if packet['projectId'] != project_id:
            raise WorkflowError(409, 'CAPTURE_BINDING', '候选的冻结输入身份不一致。')
        return job, packet

    def candidate_visuals(self, project_id, candidate_id):
        with self.lock:
            self.candidate_visual_context(project_id, candidate_id)
            return [copy.deepcopy(r) for r in self._all('candidate-capture')
                    if r['projectId'] == project_id and r['candidateId'] == candidate_id]

    def add_candidate_visual(self, *, operator_id, project_id, candidate_id, request):
        from .coordinator import WorkflowError, identifier, now
        required = {'requestId', 'name', 'mimeType', 'dataBase64', 'conditions'}
        conditions = request.get('conditions') if isinstance(request, dict) else None
        if (not isinstance(request, dict) or set(request) != required or
                not isinstance(request['requestId'], str) or not 16 <= len(request['requestId']) <= 100 or
                not isinstance(conditions, dict) or set(conditions) != {'scene', 'viewport', 'camera', 'state', 'capturedAt'} or
                any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in conditions.values())):
            raise WorkflowError(400, 'CAPTURE_REQUEST', '截图须提供原请求编号和完整采集条件；未知条件请明确填写未知。')
        self._operator(operator_id)
        with self.transaction():
            job, packet = self.candidate_visual_context(project_id, candidate_id)
            existing = next((r for r in self._all('candidate-capture') if r['requestId'] == request['requestId']), None)
            if existing:
                if (existing['projectId'] != project_id or existing['candidateId'] != candidate_id or existing['conditions'] != conditions or
                        existing['asset']['name'] != request['name'] or existing['asset']['mimeType'] != request['mimeType']):
                    raise WorkflowError(409, 'CAPTURE_ID_REUSED', '截图请求编号已对应其他候选或条件。')
                stored, _mime = self.asset_file(existing['asset']['id'])
                import base64
                try:
                    replay_bytes = base64.b64decode(request['dataBase64'], validate=True)
                except (ValueError, TypeError) as exc:
                    raise WorkflowError(400, 'CAPTURE_REQUEST', '截图内容编码无效。') from exc
                if stored.read_bytes() != replay_bytes:
                    raise WorkflowError(409, 'CAPTURE_ID_REUSED', '截图请求编号已对应其他图片。')
                return copy.deepcopy(existing)
            if job['status'] != 'READY_FOR_REVIEW':
                raise WorkflowError(409, 'CAPTURE_READ_ONLY', '此候选仅供历史核对，不能再添加采集。')
            asset = self.upload_asset(operator_id=operator_id, project_id=project_id, name=request['name'],
                mime_type=request['mimeType'], data_base64=request['dataBase64'], purpose='reference')
            asset['evidenceKind'] = 'operator-supplied-candidate-screenshot'
            self._put('asset', asset)
            record = {'id': identifier('capture'), 'requestId': request['requestId'], 'projectId': project_id,
                      'jobId': job['id'], 'packetId': packet['id'], 'proposalId': packet['proposalId'],
                      'proposalRevision': packet['proposalRevision'], 'candidateId': candidate_id,
                      'candidateCommit': job['candidate'].get('candidateCommit') or job['candidate'].get('commit'),
                      'source': 'operator-supplied', 'conditionsVerified': False,
                      'conditions': copy.deepcopy(conditions), 'asset': asset, 'createdAt': now()}
            self._put('candidate-capture', record)
            return copy.deepcopy(record)

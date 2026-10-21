"""Required local observations for the four runner roles.

Runner control tokens authenticate trusted local adapters. These observations
are not remote attestation of an arbitrary bearer-token client.
"""
from datetime import datetime, timezone

_NATIVE = (
    "nativeAppServerInitialized", "nativePrivateReadAllowed", "nativeAuthReadDenied", "nativeBackendReadDenied",
    "nativeProjectReadDenied", "nativeOtherProjectReadDenied", "nativeCommandExecDenied",
    "nativeCommandMarkerAbsent", "nativeSecretsAbsent", "nativeProcessStopped",
    "routingHostStarted", "routingHostStopped", "nativeSharedPolicyWorkerExecuted",
    "nativeSharedPolicyLoopbackIPv4Denied", "nativeSharedPolicyLoopbackIPv6Denied",
    "nativeSharedPolicyBridgeAllowed",
)
_TOOL = (
    "toolWorkspaceReadAllowed", "toolAuthReadDenied", "toolBackendReadDenied",
    "toolOtherProjectReadDenied", "toolAuthWriteDenied", "toolBackendWriteDenied",
    "toolOtherProjectWriteDenied", "toolNetworkIPv4Denied", "toolNetworkIPv6Denied",
    "toolProcessExecDenied", "toolProcessForkDenied", "toolProtectedNativeRuntimeReadDenied",
    "toolProtectedCodeHostReadDenied",
)
_PROJECT = (
    "sandbox_applied", "probe_scene_loaded", "source_read_allowed", "source_write_denied",
    "uid_sidecar_write_denied", "godot_cache_write_allowed", "private_user_write_allowed",
    "auth_read_denied", "auth_write_denied", "backend_read_denied", "backend_write_denied",
    "cross_project_source_read_denied", "cross_project_source_write_denied",
    "accepted_project_source_read_denied", "accepted_project_source_write_denied",
    "artifact_source_read_denied", "artifact_source_write_denied",
    "backend_ipv4_connection_denied", "backend_ipv6_connection_denied",
    "approval_ipv4_connection_denied", "approval_ipv6_connection_denied",
    "artifact_source_unchanged", "engine_errors_expected_only", "engine_clean_runtime",
)
REQUIRED_ROLE_CHECKS = {
    "planning-readonly-v1": (*_NATIVE, *_TOOL, "plannerWriteToolNotExposed", "plannerWriteRejected"),
    "production-private-v1": (*_NATIVE, *_TOOL, "producerScopedWriteAllowed", "producerOutOfScopeWriteDenied"),
    "verification-isolated-v1": (*_PROJECT, "verification_copy_source_immutable", "worker_group_stopped"),
    "preview-isolated-v1": (*_PROJECT, "preview_gui_mode", "preview_graphics_policy_applied",
        "preview_process_alive_at_scene_ready", "preview_copy_source_immutable", "preview_process_group_stopped"),
}


def verified_roles(evidence, runner_id, runner_kind):
    """Derive capabilities from fresh, bound, concrete observations; fail closed."""
    if (not isinstance(evidence, dict) or evidence.get("schemaVersion") != "studio.role-probe.v1"
            or evidence.get("runnerId") != runner_id or evidence.get("runnerKind") != runner_kind
            or not isinstance(evidence.get("probeId"), str) or not 1 <= len(evidence["probeId"]) <= 160
            or evidence.get("policy") != "deny-default"):
        return []
    try:
        observed = datetime.fromisoformat(evidence["observedAt"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if not -5 <= age <= 300:
            return []
    except (KeyError, AttributeError, TypeError, ValueError):
        return []
    roles = evidence.get("roles")
    if not isinstance(roles, dict):
        return []
    allowed = ("planning-readonly-v1", "production-private-v1") if runner_kind == "agent" else (
        "verification-isolated-v1", "preview-isolated-v1") if runner_kind == "project" else ()
    verified = []
    for capability in allowed:
        role = roles.get(capability)
        checks = role.get("checks") if isinstance(role, dict) else None
        if isinstance(checks, dict) and all(checks.get(key) is True for key in REQUIRED_ROLE_CHECKS[capability]):
            verified.append(capability)
    return verified

"""Bounded native failure metadata; never persist model/request/error bodies."""
from __future__ import annotations

import math
import re


_STATUSES = {"completed", "failed", "timeout", "cancelled", "uncertain", "server_exited"}
_STOP_REASONS = {"time_limit", "soft_budget", "cancelled", "native_error", "unknown"}
_BRIDGE_KINDS = {"http_error", "timeout", "network_error", "credential_reflection",
                 "unsupported_content_type", "invalid_request", "private_endpoint",
                 "client_disconnected", "invalid_response", "upstream_error"}


def public_native_failure(summary):
    """Project only classified observations; never expose native/provider bodies."""
    reasons = [item.get("reason") for item in summary.get("nativeErrors", [])]
    reasons.extend((summary.get(key) or {}).get("reason") for key in ("nativeTurnError", "driverError"))
    failures = (summary.get("providerBridge") or {}).get("failures", [])
    interrupted = "stream_interrupted" in reasons or any(
        item.get("kind") in {"network_error", "client_disconnected"} and item.get("responseStarted") is True
        for item in failures)
    reason = next((item for item in reversed(reasons) if item and item != "unknown"), "unknown")
    if reason == "unknown":
        reason = "stream_interrupted" if interrupted else next((
            {"timeout": "timeout", "network_error": "network_error"}.get(item.get("kind"), "unknown")
            for item in reversed(failures) if item.get("kind") in {"timeout", "network_error"}), "unknown")
    if summary.get("workerOutputError"):
        reason = "output_error"
    return {"reason": reason, "nativeStatus": summary.get("nativeStatus"),
            "elapsedSeconds": summary.get("elapsedSeconds"), "connectionInterrupted": interrupted}


def _number(value):
    if type(value) is int:
        return value if 0 <= value <= 2 ** 63 - 1 else None
    return value if type(value) is float and math.isfinite(value) and value >= 0 else None


def _reason(value, depth=0):
    """Classify known error labels/messages without retaining arbitrary strings."""
    if depth >= 3:
        return "unknown"
    if isinstance(value, dict):
        parts = [_reason(value.get(key), depth + 1) for key in ("code", "message", "codexErrorInfo")]
        # Native codexErrorInfo can be an enum represented by an object key.
        parts.extend(_reason(key, depth + 1) for key in list(value)[:20])
        return next((part for part in parts if part != "unknown"), "unknown")
    if not isinstance(value, str):
        return "unknown"
    text = value[:4096].lower().replace("_", "").replace("-", "").replace(" ", "")
    for reason, markers in (
        ("context_limit", ("contextwindow", "contextlimit", "contextlength", "contextoverflow")),
        ("rate_limit", ("ratelimit", "toomanyrequests", "usagelimit")),
        ("authentication", ("unauthorized", "authentication", "invalidapikey")),
        ("timeout", ("timeout", "timedout")),
        ("stream_interrupted", ("streamdisconnected", "streamconnectionfailed", "responsestream", "reconnecting")),
        ("network_error", ("networkerror", "transport", "httpconnectionfailed", "connectionreset", "errorsendingrequest")),
        ("provider_rejected", ("requestrejected", "providerrejected", "badrequest")),
        ("model_unavailable", ("modelnotfound", "modelunavailable")),
        ("cancelled", ("cancelled", "canceled", "interrupted")),
    ):
        if any(marker in text for marker in markers):
            return reason
    return "unknown"


def _error_summary(value):
    summary = {"reason": _reason(value)}
    if not isinstance(value, dict):
        return summary
    if type(value.get("willRetry")) is bool:
        summary["willRetry"] = value["willRetry"]
    info = value.get("codexErrorInfo")
    if isinstance(info, dict):
        candidates = [info, *[item for item in list(info.values())[:20] if isinstance(item, dict)]]
        for item in candidates:
            status = item.get("httpStatusCode")
            if type(status) is int and 100 <= status <= 599:
                summary["httpStatus"] = status
                break
    return summary


def native_diagnostic_summary(result, *, worker_exit_code=None, stop_reason=None,
                              output_error=False):
    result = result if isinstance(result, dict) else {}
    diagnostics = result.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    errors = diagnostics.get("nativeErrors")
    errors = errors if isinstance(errors, list) else []
    stderr = diagnostics.get("stderr")
    summary = {
        "schemaVersion": "studio.native-diagnostics.v1",
        "nativeStatus": result.get("status") if isinstance(result.get("status"), str) and result["status"] in _STATUSES else None,
        "workerExitCode": worker_exit_code if type(worker_exit_code) is int else None,
        "stopReason": stop_reason if isinstance(stop_reason, str) and stop_reason in _STOP_REASONS else None,
        "workerOutputError": bool(output_error),
        "workerOutputFailure": "output_limit" if output_error == "output_limit" else "read_error" if output_error else None,
        "elapsedSeconds": _number(diagnostics.get("elapsedSeconds")),
        "childTerminationConfirmed": diagnostics.get("childTerminationConfirmed") is True,
        "nativeErrorCount": len(errors),
        "nativeErrors": [_error_summary(error) for error in errors[-20:]],
        "nativeTurnError": _error_summary(diagnostics["nativeTurnError"])
                           if diagnostics.get("nativeTurnError") is not None else None,
        "driverError": _error_summary(diagnostics["error"]) if diagnostics.get("error") else None,
        "stderrLineCount": len(stderr) if isinstance(stderr, list) else 0,
        "protocolErrorCount": len(diagnostics.get("protocolErrors"))
                              if isinstance(diagnostics.get("protocolErrors"), list) else 0,
    }
    bridge = diagnostics.get("providerBridge")
    if isinstance(bridge, dict):
        failures = bridge.get("failures")
        safe_failures = []
        for item in failures[-20:] if isinstance(failures, list) else []:
            if not isinstance(item, dict):
                continue
            status = item.get("httpStatus")
            safe_failures.append({
                "kind": item.get("kind") if isinstance(item.get("kind"), str) and item["kind"] in _BRIDGE_KINDS else "upstream_error",
                "httpStatus": status if type(status) is int and 100 <= status <= 599 else None,
                "responseStarted": item.get("responseStarted") is True,
                "observedAt": item.get("observedAt") if isinstance(item.get("observedAt"), str)
                              and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", item["observedAt"]) else None,
            })
        summary["providerBridge"] = {
            "requestCount": _number(bridge.get("requestCount")),
            "failureCount": _number(bridge.get("failureCount")),
            "timeoutSeconds": _number(bridge.get("timeoutSeconds")),
            "failures": safe_failures,
        }
    return summary

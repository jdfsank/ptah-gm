#!/usr/bin/env python3
"""Thin local review commands. Generation stays in the original gm-* skills."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import review_support as review  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "status", "check", "play", "feedback", "gate", "confirm-spec", "decision", "resolve-feedback", "recover-lock", "bind-evaluation"):
        command = commands.add_parser(name)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--json", action="store_true", help="Structured output (also the default)")
        if name in {"doctor", "check"}:
            command.add_argument("--godot", help="Explicit binary; otherwise original configured path/PATH lookup")
        if name in {"play", "feedback", "decision", "resolve-feedback", "gate", "bind-evaluation"}:
            command.add_argument("--run", required=name != "gate")
        if name == "check":
            command.add_argument("--suite", choices=("verify", "e2e", "all"), default="all")
        if name in {"check", "play"}:
            command.add_argument("--timeout", type=float, default=600 if name == "check" else 3600)
        if name == "feedback":
            command.add_argument("--file", required=True, type=Path)
        if name == "decision":
            command.add_argument("--choice", choices=("accept", "changes_requested", "design_change", "defer"), required=True)
            command.add_argument("--reviewed-profile", action="append", default=[])
        if name == "resolve-feedback":
            command.add_argument("--id", required=True)
        if name == "confirm-spec":
            command.add_argument("--frontend-event-id", help="Consume a backend-registered frontend approval event")
    command = commands.add_parser("smoke")
    command.add_argument("--fixture", choices=("one_room_loop",), required=True)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--variant", choices=review.VARIANTS, default="baseline")
    command.add_argument("--godot")
    command.add_argument("--timeout", type=float, default=40)
    command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "timeout") and (not 0 < args.timeout < float("inf")):
            raise review.ReviewError("Timeout must be positive and finite", "BLOCKED")
        if args.command == "doctor":
            result = review.doctor(args.project, args.godot)
        elif args.command == "smoke":
            fixture = Path(__file__).resolve().parent.parent / "tests/fixtures" / args.fixture
            if not fixture.is_dir():
                fixture = Path(__file__).resolve().parent / "review_fixtures" / args.fixture
            result = review.smoke(fixture, args.output, args.variant, args.godot, args.timeout)
        elif args.command == "status":
            result = review.status(args.project)
        elif args.command == "check":
            result = review.check(args.project, suite=args.suite, timeout=args.timeout, godot=args.godot)
        elif args.command == "gate":
            result = review.gate(args.project, args.run)
        elif args.command == "feedback":
            result = review.add_feedback(args.project, args.run, review.load_json(args.file))
        elif args.command == "confirm-spec":
            result = review.confirm_spec(args.project, args.frontend_event_id)
        elif args.command == "decision":
            result = review.decision(args.project, args.run, args.choice, args.reviewed_profile)
        elif args.command == "bind-evaluation":
            result = review.bind_evaluation(args.project, args.run)
        elif args.command == "recover-lock":
            result = review.recover_lock(args.project)
        elif args.command == "resolve-feedback":
            result = review.resolve_feedback(args.project, args.run, args.id)
        else:
            result = review.play(args.project, args.run, timeout=args.timeout)
    except review.ReviewError as exc:
        result = {"schema_version": 1, "command": args.command, "result": exc.result, "reason": str(exc)}
    except Exception as exc:
        result = {"schema_version": 1, "command": args.command, "result": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return review.RESULT_CODES[result["result"]]


if __name__ == "__main__":
    raise SystemExit(main())

# GodotMaker Agent Capability Contract

This contract defines the runtime-independent capabilities required to run the
GodotMaker pipeline. Runtime-specific references such as
`agent-runtimes/<agent>/references/runtime-mapping.md` map these capabilities
to the tools, permissions, and project-local surfaces available in a selected
coding agent.

Every runtime mapping must classify each capability as one of:

- `native`: directly supported by the runtime.
- `emulated`: supported by a documented fallback with equivalent user-visible
  semantics.
- `gated`: unsupported unless a precondition is satisfied; the agent must stop
  with a clear handoff instead of silently degrading.

## Required Capabilities

| Capability | Contract |
|---|---|
| `invoke_stage` | Run a GodotMaker stage entrypoint such as scaffold, gdd, asset, build, verify, evaluate, fixgap, accept, or finalize through the selected runtime's native invocation surface. |
| `read_project_config` | Read the published project configuration to discover `godot_path`, project settings, and any selected-agent runtime roots before executing a stage. |
| `read_skill_reference` | Resolve role-local references, templates, helper docs, and supporting skills from the published project-local framework tree. |
| `dispatch_worker` | Delegate or otherwise isolate implementation work with enough context to follow role locks, file ownership, PLAN/GAP scope, hooks, and reporting rules. |
| `dispatch_reviewer` | Delegate or run review against integrated work, preserving the reviewer report contract and triage rules. |
| `dispatch_verifier` | Delegate or run verification checks, preserving the verifier report contract and failure-to-task conversion rules. |
| `track_plan` | Maintain visible task/checklist state for multi-step work so the user can see active, pending, and completed framework work. |
| `run_shell_command` | Execute local commands required by the framework and project, capture output honestly, and report skipped or failed commands explicitly. |
| `access_godot_mcp` | Reach the Godot MCP server, or stop with a documented gate when MCP is required but unavailable. |
| `apply_permission_policy` | Avoid expected framework commands deadlocking on interactive permission prompts; apply the selected runtime's sandbox, approval, or hook policy explicitly. |
| `detect_worktree_state` | Detect whether execution is in a normal checkout, an isolated workspace, a linked worktree, or a detached-head/sandbox environment before branch or delegation decisions. |
| `create_or_use_isolated_workspace` | Create, reuse, or deliberately avoid isolated workspaces while keeping project-local framework files available to delegated execution. |
| `finish_branch_or_handoff` | Finish work through a branch, commit, push, PR, or host-application handoff that matches the current checkout and permission state. |

## Runtime Mapping Requirements

Runtime mappings must not treat one agent's file layout or tool names as the
canonical contract. They must document:

- how the runtime invokes GodotMaker stages;
- where published project configuration and references are expected to live;
- how delegation, review, and verification are performed or gated;
- how planning, shell commands, MCP, hooks, permissions, and sandboxing work;
- how normal checkouts, worktrees, detached heads, and host-managed task
  environments affect finish behavior.

If a capability is gated, the stage must stop before making changes that depend
on that capability.

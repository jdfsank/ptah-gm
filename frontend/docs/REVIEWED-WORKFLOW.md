# Reviewed navigation and submission workflow

## A. Navigation and editing

```mermaid
flowchart LR
  Scene[Scene] --> Instance[Placed instance / entrance marker]
  Instance --> Detail[Instance detail and DNA lenses]
  Detail --> Definition[Shared definition]
  Definition --> Behavior[Behavior]
  Definition --> Usage[Source references / new draft references / spawn rules]
  Usage --> Instance
  Scene --> Overview[Overview]
  Scene --> Composition[Composition]
  Scene --> Connections[Connections]
  Detail -. secondary .-> Evidence[Source and coverage diagnostics]
```

There is one explicit current target shared by selection, breadcrumbs, inspector
and note scope. DNA is three views of the same target, not three data stores.
Browsing existing targets never places an object. New placement has a separate
entry, preview state and cancellation. Name/ID search and browser history use
stable target references. Existing note IDs are retained; room ID plus draft
object ID maps explicitly to catalog records. Colons inside an entrance ID are
not parsed as structural separators.

Definition usage separates immutable source placements, new browser-only draft
references, and runtime spawn rules. A source record removed from the draft stays
visible as removed; it is never silently reassigned to a different instance.

## A. Submission

```mermaid
flowchart TD
  Draft[Typed draft and scoped notes] --> Diff[Net content diff against reviewed source baseline]
  Diff --> Resolve[Resolve all targets and orphan notes]
  Resolve --> Build[One buildSubmission freezes payload and exact JSON]
  Build --> Preview[Preview diff, all notes, context, range, baseline, destination and intent]
  Preview --> Cancel[Cancel: no pending envelope and no POST]
  Preview --> Confirm[Explicit confirmation]
  Confirm --> Check[Read current bridge status and compare fingerprint]
  Check -->|changed| ReviewAgain[Invalidate and review again]
  Check -->|same| Pending[Persist exact frozen envelope]
  Pending --> POST[One idempotent POST]
  POST --> Receipt[Durable receipt and execution status]
  POST --> Unknown[Uncertain delivery]
  Unknown --> ExactID[Look up exact ID on original store and thread]
  ExactID --> Receipt
  ExactID -->|confirmed absent| ReviewAgain
```

Revision is an audit counter, not proof of a change. Edit/revert and edit/undo
can have zero net diff. Navigation and theme changes preserve a preview; content,
notes, version, scope, execution intent, source baseline or destination changes
require a new preview. Notes-only submissions are allowed; truly empty ones are
blocked. Deleted-target notes must be explicitly moved or removed. No automatic
resend, source re-extraction, result application or replacement of newer drafts.

V1 remains compatible. V2 is separately negotiated and adds explicit resolved
targets, diff, allowed execution scope, execution intent and PLAN/tag/mechanism
references. Full snapshot context never means permission to change all of it.

## B. GM adapter boundary

```mermaid
flowchart TD
  V2[Reviewed v2 payload] --> Binding[Read-only thread/project/skills/tools/PLAN/run checks]
  Binding --> Mapping[Server-reviewed exact target and allowed-path mapping]
  Mapping -->|unknown / conflicting / unavailable| Blocked[BLOCKED with evidence]
  Mapping --> Route[Bounded route]
  Route --> Design[Design: gm-gdd and PLAN]
  Route --> Art[Art: existing gm-asset flow]
  Route --> Runtime[Runtime: authoritative PLAN task]
  Runtime --> Check[Formal check and evaluator evidence]
  Check --> Feedback[Exactly six feedback fields]
  Feedback --> Implementation[implementation: reproduce then fixgap]
  Feedback --> Experience[experience: reproduce then classify]
  Feedback --> Change[design_change: stop writes and confirm revised spec]
  Feedback --> TestError[test_error: evaluator]
  Feedback --> Capability[capability: BLOCKED]
  Check --> Import[Validate server-side result evidence]
  Import --> Result[Delivery / turn / item implementation / verification / human gate]
```

PLAN and GAP remain GM's authority. The adapter introduces no new planner,
project task database, or graph. Its target-map file is an adapter mapping, not a
replacement task model. Unknown mappings must be reviewed against the bound
project; IDs are not inferred from names, prose or sample data.

Human confirmation follows the real phase: specification before dependent
implementation; run acceptance after experience verification; feedback resolution
after a verified repair. Existing exact valid confirmations may be reused.
Neither Submit, an agent message, a fabricated actor field nor simulated TTY input
is a human confirmation. Only a real needed phase yields needs_human.

A completed turn is not proof of source edits, item completion or a game test.
Formal verification uses GM check run/report provenance; smoke, play, browser
simulation and source inspection are not substitutes. Results never overwrite
post-submission drafts or silently adopt a different source baseline.

## Validation scope

The private Site is deliberately a browser-local demo. It can exercise preview,
selection, notes and receipt recovery but does not call an agent, connect a local
bridge, run Godot or change project files. The local source package includes the
real loopback bridge and fail-closed GM contract; live capabilities and evidence
must be established on the explicitly bound local project/thread.

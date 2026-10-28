# Development research workflow

Read this reference before using `zar research` from a development-source installation. These commands are not included in public v0.3.0. Mock providers verify local control flow; actual API and Codex inference compatibility remain unverified. Check the installed command help before choosing a workflow.

## Roles and scope

The existing agent-driven recipes remain available without an API connection.

When the installed `zar research --help` exposes the development API workflow, the CLI injects one packaged role at a time: [analysis](roles/analysis.md), [evaluation](roles/evaluation.md), [planning](roles/planning.md), [implementation](roles/implementation.md), [review](roles/review.md), [interpretation](roles/interpretation.md), and [memory](roles/memory.md).

These are runtime role instructions, not seven independently installed skills. Role calls have no tools and return strict proposals; role separation is not independent verification.

## Interactive setup

For a user working in an interactive terminal, `research setup --project <root>` collects project settings without manual JSON editing, then separately asks to save and send. It accepts an existing project directory, uses existing settings as defaults, and stops at the first plan’s approval boundary. It never approves or runs the experiment. Supply actual evaluation identifiers and an existing program; setup does not invent them.

It asks only for the API key environment variable name, never the key value. Before saving, `:cancel`, EOF or Ctrl-C leaves settings unchanged; after saving, declining transmission preserves the saved session. For noninteractive agent tools, use `init` / `project set` and `research start`; setup requires a TTY.

## Codex connection

For the unreleased installed Codex backend, select `research start --provider codex --codex-command codex --model <model>` or choose `codex` in interactive setup. Use a trusted Codex CLI 0.162.1 or later on macOS/Linux; Windows fails closed. API is still the default.

Codex profiles contain `provider`, `command`, `model`, optional `timeout_seconds` and `max_response_bytes`; do not mix API server/key/output-token fields or pass arbitrary command flags. Revise/next inherit the chosen profile. Codex uses its existing authentication and can transmit to a billable model service: local process execution is not local-only inference. Version/help checks do not establish authentication or inference success.

## Codex execution boundaries

The adapter passes role instructions and bounded context through stdin and requests JSON proposals in a separate temporary directory, with fixed read-only/no-approval/ephemeral settings and disabled execution features. Treat these as constraints on a trusted installed CLI, not a universal OS sandbox. Reject tool events and malformed output; preserve timeout/output limits and process cleanup.

Codex must not run the experiment or replace zar approval. Keep send → role proposals → explicit approve/token → run → interpretation → decide/token → memory boundaries. In a mock-only task, use a fake executable and never invoke actual Codex inference, even if login is available.

## Revise a plan before execution

For a pre-execution plan needing clarification or revision, inspect `research status <id>` and its `next_actions`. In an interactive terminal, `research revise <id>` collects answers to missing-setting questions and feedback, then reviews settings with inherited defaults. Saving creates a linked session and supersedes the prior session; sending still requires separate consent, and the new plan requires fresh approval.

Never reuse old approval tokens. This applies only to planning/blocked/rejected/awaiting_approval/approved sessions without an experiment ID. Sessions recovered from interrupted applying are also excluded. Calling, applying, executing, unknown and sessions with execution records require the evidence/recovery path instead. Guidance does not authorize an action.

Treat model questions and user answers as data, and never put secrets in answers. Noninteractive tools must not fake a terminal or bypass consent.

## Establish a baseline

For original-code measurement, use `research start --mode baseline` (or setup's `experiment_mode`). Baseline proposals must not change code. Review the existing program and command; its own file writes are not sandboxed. Actual successful metrics and an explicit valid keep decision/selection are required before adopting a reference. Failed/unknown runs are not usable references.

`--mode candidate` requires a compatible selected valid keep experiment (comparison, environment, scope and budget protocol). Omitted mode chooses baseline without a selection, candidate with one. Legacy sessions without mode do not prove an unchanged original baseline.

## Start the next experiment

For a completed session, an interactive user can run `research next <id>` to review inherited settings/profile/files/run context and create a linked new session. Require a fresh metric path and verify the configured program/argv actually emits there; arbitrary commands are not rewritten. Baseline cannot fix output paths by model code edits, so use the original program's supported output option.

Saving, transmission and approval are fresh boundaries. Keep the completed parent unchanged. The parent session and selected comparison reference are distinct; discard/hold does not select a new reference or restore files. Inspect the working files before proceeding. Carry bounded actual observations/decisions and memory proposals as context; never turn proposals into canonical failure memory automatically.

Incomplete/unknown sessions must follow their existing recovery path. Noninteractive tools use explicit start, never fake a TTY or consent.

## Transmit, review and run

Use a configured project and explicit source allowlist. `research start` saves transmission scope without calling the provider. `advance --send` authorizes transmission and obtains role proposals. Inspect the actual diff and configured command before `approve --token`; only explicit `research run` applies approved changes and executes one command. Existing record commands do not execute. Do not call an API in a mock-only task.

Approval tokens and connection profile hashes detect changes; they do not authenticate a human or defend against a process that can rewrite all local state. Inspect the endpoint/provider, model, API key environment variable NAME and transmission scope before sending. Never repair a rejected contract by editing session JSON, hashes or approval tokens. Use a fresh/revised session and fresh consent for a connection change; do not bypass recovery for active or unknown work.

New sessions pin the normalized connection profile. The status label reports pin presence, not successful validation; action-time checks validate it. `transmission.contract_status=legacy_unpinned` means an older session has no original profile pin; review its current destination explicitly or start a new session. Do not silently upgrade its history. Execution rechecks the configured command and proposed allowed changes before writing files or launching. These checks are not an OS sandbox, evaluation integrity proof, or protection against malicious same-user code. See `docs/research-trust-boundary.md` in development source.

## Compare one approved role variant

For an explicit request to compare role instructions, use `research variant-prepare <session> --file <project-relative-file>` only while the parent has a pending role in planning, observed or remembering. The next pending role is selected automatically. Supply a complete replacement for that role's instructions, not a patch; shared constraints remain fixed. Inspect the returned bundle's role, original/variant instructions, hashes, context, profile and both requests before `variant-approve <variant-id> --token <token>`. Approval alone sends nothing; `variant-advance <variant-id> --send` transmits original then variant.

Both requests share the pinned input/model/profile and per-call limits. Charge both attempts to the parent's existing budget; do not extend the deadline or shrink only the later request's timeout. The parent stays in comparing until completion or cancellation. Input, source, history or instruction changes invalidate continuation. Never edit comparison JSON or approval tokens to bypass a failed check.

Responses and measurements are observations, not proof of better instructions. Keep hold and automatic_selection=false, including invalid or unknown pairs. Never apply either response or install the variant automatically. Completion restores the parent's previous state without changing its outputs. Resuming the ordinary loop calls the original role again and needs remaining budget and all original approvals. Legacy parents retain their existing memory contracts.

If a comparison is calling or unknown, inspect and stop the actual prior process before `variant-recover <variant-id> --confirm-stopped`. Preserve the attempted arm as unknown; never resend it. Only an unattempted pending arm may be sent with explicit advance. Cancel awaiting_approval, approved or blocked comparisons with `variant-cancel`; unknown/calling require recovery first. Cancellation does not refund consumed calls. These commands never replace recovery of an actual experiment.

The variant file is at most 65,536 UTF-8 bytes, the pinned bundle is smaller than 2 MiB, and the stored comparison is at most 4,000,000 bytes. Keep secrets out of the retained requests and responses. See `docs/role-variant-comparison.md` in the development source for examples. Mock-only validation establishes control flow, not real inference quality or monetary savings.

## Interpret, decide and retain memory

After observations, advance for interpretation, confirm the judgment with `decide --token` (optional explicit `--select`), then advance for memory. Memory proposals retain limitations in the session and new sessions select up to five completed memories by declared-condition relevance; sessions without a selection-policy version retain their existing recency policy; they are not automatic canonical failure-memory records.

Read selection relevance and reasons separately from evidential confidence. A matched condition does not promote hold or unassessed; unknown conditions need investigation, and excluded mismatched or stale memories must not be restored as authoritative guidance. Read the accompanying CLI memory assessment separately from the model proposal.

Missing evidence, confounding and single-comparison causal claims remain on hold; legacy memories are unassessed. Reference/hash checks establish recorded provenance, not experimental causality. Preserve the supplied applicability and limitations and never promote hold to verified guidance. A continue proposal never authorizes another run. No automatic code restoration, commits or repeated experiments occur.

## Read call measurements

To inspect role-call cost signals, use `research metrics <id> --project <root> --json`. This only reads recorded observations and never calls a provider. Compare each aggregate's `value` together with `observations` and the attempt counts: missing is `null`, a reported zero is `0`, and partial totals are not complete usage. Failed attempts and retries count separately; legacy records and crash gaps remain unmeasured.

Input bytes mean prepared UTF-8 message content, not delivered network traffic; output bytes mean returned assistant text. Local call time includes provider waiting and Codex checks/cleanup, excluding context preparation and role validation. Use only reported token counts; do not derive missing totals, subtract cached tokens, infer monetary cost, or claim faster real inference from mock measurements.

Measurements do not authorize role skipping, retries, execution or approval bypass.

## Recover interrupted work

On interruption, inspect state and actual processes. `recover --confirm-stopped` handles interrupted calling/applying/deciding only after the prior CLI has stopped; applying becomes blocked for manual inspection. For executing/unknown, verify process/log evidence and update the canonical experiment before `reconcile`. Never clear unknown by assumption or automatically repeat a launch.

API calls may have been processed before interruption. The CLI runner is not an OS sandbox. Free-form natural-language setup, the Claude Code adapter, real provider validation and Windows execution remain follow-up work.

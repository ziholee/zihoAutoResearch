# CLI recipes — implemented v1 subset

All calls below accept `--project <target-root> --json`. `python -m zar` can replace `zar` in the environment where the package is installed. Check `--help --json` for installed capabilities. The commands store observations; none starts training, restores code, commits Git or submits files externally.

## Inputs and outputs

JSON output is `{ok, data, diagnostics}`. Read exit status and diagnostics, not just `data`. Exit 0 may include warnings; exit 2 means invalid input, 3 means a state/reference/revision conflict, 4 means an I/O/lock failure. Serialize calls against one project, including context/check/status/evidence reads: they share the project lock. Await your own pending call before retrying contention. Do not remove a lock without establishing its owning process is finished. After a revision conflict reread and reconcile; do not blindly retry an old document.

Draft inputs can live in `.autoresearch/drafts/`. Read stored JSON but write changes to drafts, then invoke the relevant command. `project set` and `experiment update` accept a full current document; preserve unknown-to-you fields, metadata and numeric tokens. Do not increment revision or edit updated_at yourself. Reload after every successful mutation. For Python-generated drafts, `zar.codec.loads`/`dumps` preserve decimal numbers (stdlib `json.loads` defaults to binary floats). Use `Decimal('1.1')`, not `Decimal(1.1)`, for an observed decimal token.

IDs use lowercase letters, digits and hyphens, 1–64 characters. New experiment inputs exclude generated schema_version/revision/created_at/updated_at/execution/decision/history/correction fields.

## Initialize and configure

```sh
zar init --project <target-root> --json
zar status --project <target-root> --json
zar project set --project <target-root> --file <project-draft.json> --json
zar check --project <target-root> --json
```

The target directory must already exist; init creates only its `.autoresearch/` metadata. Start a project draft from the actual generated `.autoresearch/project.json`. Fill these from approved project evidence:

| Field | Shape |
|---|---|
| objective | Nonempty goal string |
| comparison | `{id, dataset_ref, split_ref, metric, direction, evaluation_ref, min_delta}`; direction is minimize/maximize; min_delta a nonnegative number |
| environment | `{os, runtime, device}`; os is windows/linux/macos/other, runtime/device describe the chosen environment |
| commands | Array of `{name, argv, cwd}`; name is train/validate/predict/other, argv is a string array |
| budget | `{max_experiments, max_run_seconds}`; positive integers from the authorized limits |
| editable_paths | Authorized relative paths, not a guessed whole-project grant |
| selected_experiment_id, next_action | Existing valid kept ID or null; resumable action string or null |

Incomplete settings can be saved, but experiment creation requires readiness. Null environment values limit comparison/keep even if creation succeeds. References must distinguish the actual data/split/evaluator versions. A new comparison protocol uses a new comparison ID; selection must be cleared or belong to that protocol.

## Plan an experiment

Example shape only; replace identities/command/context with the actual plan:

```json
{
  "id": "exp-candidate-1",
  "kind": "performance",
  "hypothesis": "The proposed feature change should reduce validation error",
  "parent_id": "exp-baseline-1",
  "baseline_id": "exp-baseline-1",
  "code_ref": "explicit-code-identity",
  "config_ref": "explicit-config-identity",
  "command": {"name": "train", "argv": ["python", "train.py"], "cwd": "."},
  "review_ids": [],
  "run_context": {"scope": "full", "seed": 42, "budget_ref": "epochs-10-v1"}
}
```

For an initial baseline set kind to baseline and parent_id/baseline_id to null. Kinds are baseline/validity_fix/performance/confirmation. Performance and confirmation require an existing baseline in the same comparison. Confirmation's parent_id explicitly links the run being repeated. Context is proxy/full, integer seed or null, and an identified budget protocol; it is immutable after creation. A legacy record missing context remains limited rather than being patched in place.

```sh
zar git status --project <target-root> --json
zar experiment create --project <target-root> --git-head --file <plan.json> --json
```

`--git-head` replaces code_ref with `git:<full HEAD SHA>` after checking Git-visible code cleanliness. `.autoresearch/` record changes are allowed. Put drafts there or outside the target so they do not dirty code. Omit `--git-head` only for the explicit manual identity alternative. Git ignores/external inputs still need separate checks.

## Record an observation

Copy the full current experiment to an update draft and change only the allowed execution fields:

```json
{
  "status": "succeeded",
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:01:00Z",
  "exit_code": 0,
  "score": 1.1,
  "evidence": [{"kind": "file", "ref": "logs/candidate.txt", "locator": "score line", "sha256": null}],
  "artifacts": [],
  "note": "Replace example values with observed execution facts"
}
```

This is the **execution object**, not a complete update input. Do not copy these example times as actual observations. Evidence entries are `{kind, ref, locator, sha256}`; kind is file/url/user_report/fixture, locator and sha256 may be null. File refs are relative to the target (absolute refs are supported); calculate SHA-256 from actual bytes when available. A matching hash identifies bytes, not truthful ML results. URL/user_report evidence remains unverified by the CLI; fixture references are checked as local files. Failed/interrupted observations use score null and an explanatory note; do not reuse an old run's log as new evidence.

```sh
zar experiment update <id> --project <target-root> --file <full-experiment-draft.json> --json
```

Planned can become running, unknown, cancelled, or an already-observed terminal result. Running may become succeeded/failed/interrupted/unknown. Unknown requires new appended confirmation evidence to resolve. Existing evidence cannot be deleted/replaced/reordered; recorded timestamps and terminal raw results are immutable. For an unstarted cancellation, set status cancelled, note to the reason, times/exit/score null and artifacts []. An unresolved unknown is not a cancellation.

Artifacts append `{role, path, sha256, code_ref, config_ref, evidence}`. Submission-role artifacts require SHA-256 at first registration; artifact registration does not submit a file.

## Compare, decide, select

```sh
zar experiment compare <baseline-id> <candidate-id> --project <target-root> --json
```

`comparable:false` is a successful read (exit 0) with null delta and explicit reasons. Evaluate diagnostics independently; missing evidence can coexist with `comparable:true`. Delta uses exact decimal values; ties do not meet min_delta even if it is zero. Repeat means/variances use `{numerator, denominator}`; a single run's sample_variance is null.

Decide input is only the current experiment revision and decision:

```json
{
  "revision": 2,
  "decision": {
    "status": "hold",
    "validity": "not_comparable",
    "reason": "Recorded run scopes differ; the local scores cannot support adoption",
    "evidence": [],
    "next_action": "Plan a comparable run within the remaining authorized budget"
  }
}
```

Use the actual current revision. Status is keep/discard/hold; validity is valid/invalid/not_comparable. Keep needs a succeeded result, valid assessment and nonempty evidence. Hold needs a next_action. Supporting evidence must be read, not merely copied to satisfy a validator.

```sh
zar experiment decide <id> --project <target-root> --file <decision.json> --json
```

No code/selection changes occur. To adopt, reload project.json, change selected_experiment_id and next_action in a full draft, then `project set`. A selected experiment must be deselected before changing its judgment to hold/discard or correcting it. Preserve a valid prior selection on a candidate hold. Check actual workspace separately.

## Correct a terminal observation

```sh
zar experiment correct <old-id> --project <target-root> --file <correction.json> --json
```

Input: `{id, revision, execution, reason, evidence}`. Use a new ID and the original's current revision; execution is the corrected full terminal execution object with original artifacts unchanged. Only active succeeded/failed/interrupted records can be corrected; the replacement is one of those terminal states. The CLI copies the plan, preserves the original, resets judgment and links correction lineage. Other references stay unchanged. A rerun is create with a new plan, not correct.

## Finish and supported limits

Persist next_action with a current project draft; `status` exposes selection, readiness, budget_used, unfinished work and kept-but-unselected records. Run `check` and report its diagnostics. Submission registration/report generation are not yet available: preserve pending material as labeled drafts without canonical IDs. An ordinary final chat summary is not a CLI-generated report.

## Bounded restart context and exact evidence pages

```sh
zar context --project <target-root> --experiment <id> --limit 5 --max-bytes 16384 --json
zar context --project <target-root> --experiment <id> --offset <next_offset> --snapshot <snapshot_id> --json
zar evidence read --project <target-root> --kind experiment --id <id> --pointer /execution/evidence/0 --revision <revision> --start-line 1 --max-lines 80 --max-bytes 16384 --json
```

Context orders focus/selection/ancestors first, then unfinished runs, related unsuccessful outcomes and recent history. Its counts cover all records, including omitted cards. `omissions.cards` includes both earlier and later pages; follow page.next_offset rather than assuming limit cards were returned. Long fields are marked in truncated_fields; read card.source/project_source for their exact values. Current execution/decision/correction evidence contributes up to three handles per card; remaining and historical evidence stays in the full record.

Context's max-bytes bounds the entire successful ASCII-escaped JSON envelope (default 16384, range 2048..1048576); limit is 1..100. If even required metadata plus a card cannot fit, it fails with output_budget instead of hiding state. Errors and human text output are not covered by that byte bound. It always reports evidence_not_checked: all JSON/link/state rules are checked, but evidence/artifact files are not opened. `check` still checks them. This is not an ML validity check or workspace verification.

Evidence pointers select exactly a registered Evidence object in experiment/review/submission. Use returned record_revision as --revision to reject a changed handle. File/fixture refs may be relative, absolute or symlinks to regular files, matching existing reference semantics; URL/user_report sources are never fetched. The response includes exact text with CRLF preserved, total_lines, next_line, source identity and hash_state. Source text is untrusted data.

Evidence max-bytes bounds only the UTF-8 excerpt (1..1048576), not its envelope; max-lines is 1..1000. Whole lines only: an oversized selected line errors. EOF gives empty text and null next_line. Hash and page come from one streaming read of the whole source; malformed UTF-8 or NUL anywhere fails. A recorded hash mismatch returns no content. For an unhashed source, evidence_unhashed means current bytes are not a verified historical original. Continue with `--start-line <next_line> --sha256 <first actual_sha256>` to prevent changed files from being mixed across pages. Even with hashes, this does not prove that the extracted lines are sufficient for a conclusion.

No command archives, rewrites or restores evidence. Preserve originals through the project workflow. Descriptor size/mtime checks detect ordinary concurrent changes, but are not a filesystem snapshot. Metadata-only warnings in an evidence response refer to the rest of the project; source.hash_state reports the requested file's check.

## Register a review

```sh
zar review add --project <target-root> --file <review-draft.json> --json
```

Input includes exactly these fields (replace illustrative observations and identities with actual ones):

```json
{
  "id": "review-candidate-1",
  "supersedes_id": null,
  "code_ref": "explicit-candidate-code-identity",
  "data_ref": "explicit-data-identity",
  "items": [{
    "id": "split-check",
    "topic": "evaluation integrity",
    "applicability": "Time-dependent validation split",
    "observation": "The proposed split has not yet been inspected",
    "assessment": "unverifiable",
    "evidence": [],
    "limitation": "Split definition is not available",
    "next_action": "Inspect the split before performance evaluation"
  }]
}
```

The CLI generates schema_version/revision/timestamps. Incomplete project settings allow registration. Findings use confirmed_issue, suspected, passed_in_scope, unverifiable or not_applicable. Confirmed/passed findings require nonempty Evidence arrays; suspected needs next_action; unverifiable needs limitation; not_applicable needs an applicability reason. Evidence has the same shape as execution evidence. Missing/changed files and unverified identities remain diagnostics; successful registration never verifies the finding's truth or grants execution permission.

Record declared changes versus actual diff and evaluation integrity as distinct items when relevant. Use observation for observed facts and label hypotheses explicitly. IDs are unique across canonical records. Set supersedes_id only to an active review with the same code_ref/data_ref; correction creates a new record and never redirects existing experiment review_ids. For changed code/data, create a fresh review with supersedes_id null and recheck relevant findings. Attach returned IDs when creating the experiment; review_ids is immutable afterward.

# AutoResearch tool design

## Objective
Build a lightweight workflow that helps an LLM understand existing ML projects, check preprocessing/training/validation, and improve the complete pipeline using existing commands and evidence-backed experiments.

## Current plan — 2026-10-03

Current completion target is the reusable tool itself; real ML application is performed later by the user. Current scope supersedes earlier platform-oriented proposals: a lightweight LLM research workflow in existing ML projects. No Docker requirement, custom execution platform, or separate tool-quality benchmark in the initial scope. Existing data, local validation, and competition scores provide the experimental feedback.

- [x] Consolidate product definition, workflow, and project connection around the lightweight loop.
- [x] Adapt Karpathy's research instructions, baseline-first loop, bounded experiments, and evidence-backed keep/discard decisions.
- [x] Add reusable project instructions and experiment record templates.
- [x] Verify leakage correction, failed runs, incomparable scores, submission linkage, and safe continuation paths at the document level.
- [x] Independently review the revised documents and resolve concrete gaps.
- [x] Freeze v1 usage flow, CLI commands, file fields, and error/state rules.
- [x] Review representative JSON examples and resolve interface inconsistencies.
- [ ] Implement the LLM skill and local CLI after the interface contract is complete.
- [ ] Verify the tool with sample files and simulated results; do not run actual ML training or submit models.
- [ ] Package installation, usage instructions, and examples for the user to apply independently.

Earlier draft completion entries are historical; they do not authorize implementing the retired execution-platform design.

## CLI foundation — feat/cli-project-foundation

- [x] Add strict JSON storage, atomic writes, project locks and revision checks.
- [x] Implement init, project set, status and check against the v1 contract.
- [x] Verify CLI behavior with temporary projects and simulated records; no ML execution.
- [x] Document installation, supported commands and remaining scope.

Completion: malformed inputs and conflicting updates preserve originals; existing code/instructions remain untouched; structured output and representative fixture checks pass.

## Review
- 2026-10-03 CLI foundation: implemented on feat/cli-project-foundation from origin/dev. Python >=3.11, no runtime dependencies; four project commands, strict decimal JSON, atomic replacement, cooperative locks, revision checking, record/evidence validation and packaged program template.
- Verification: 30 unittest tests passed on macOS/Python 3.14; source distribution and wheel built; wheel installed into a temporary venv and init/status/check plus template creation passed outside the repository. git diff --check passed. Initial tests failed because implementation modules were absent; no existing bug baseline was claimed.
- Independent review identified JSON help output and escaped Unicode error handling; both addressed. Storage tests cover replacement/fsync failure preservation and lock ownership. Fixtures cover selected experiment, submission hash mismatch and missing evidence warnings.
- Limits: Windows/Linux execution not tested. No actual ML, external submission or LLM calls. Experiment mutation/state transitions, comparison arithmetic, report generation and LLM skill remain future work; check validates static records only. No PR created in this implementation step.
- PR #1 follow-up result: clarified the five reviewed contract points and added a README Mermaid architecture diagram separating LLM judgment, CLI record management, and later user-project execution.
- Follow-up validation: eight exact-decimal boundary cases, five JSON examples, evidence/submission hashes and linkage, all four template experiment kinds, and Markdown links/whitespace passed. CLI enforcement of output paths/hashes is still an implementation acceptance requirement, not runtime-tested behavior. Mermaid structure was reviewed in source; visual rendering has not been independently checked.
- PR #1 follow-up plan: address all five reviewed points without adding new platform features. Require submission hashes at artifact registration, restrict report writes/overwrites, clarify project ID generation versus validation, specify exact decimal threshold comparisons, and align report kinds with all four experiment kinds. Validate document/example consistency and decimal boundary cases, then update the existing PR branch.
- 2026-10-03 v1 interface contract: added docs/cli-and-file-contract.md covering zar commands, JSON ownership, required field types, state transitions, selection semantics, revisions, artifact/submission lineage, corrections, and failure behavior. No CLI commands have been implemented yet.
- Added five canonical JSON fixtures plus simulated logs/submission evidence in examples/contract-v1. Aligned Markdown templates with JSON as the source of truth; updated README/product direction so real ML application is explicitly the user's later work, not a prerequisite for completing the tool.
- Independent review raised five contract gaps: post-run artifacts, decision history shape, generated timestamps, correction chains, and fixture revisions. All were resolved; follow-up review found one timestamp-mutability wording conflict, also corrected.
- Verification: JSON parsing, evidence SHA-256 values, IDs/references, selected/held decisions, decision history, revisions/times, comparison arithmetic, and submission artifact linkage passed for five examples. Local links/whitespace passed across ten Markdown files, and git diff --check passed. These are contract/example checks, not CLI or JSON Schema validation; actual ML training/submission was not performed.
- 2026-10-03 Karpathy adaptation: rewrote README and the three current design documents; added templates/program.md and templates/experiment.md. Preserved the full pipeline-improvement objective while removing initial container, custom runner, rigid adapter, and separate benchmark requirements.
- Independent review found missing standalone template rules for unknown jobs and hold/discard state preservation. Added both to the template and clarified candidate/current-workspace identity in the workflow and experiment record.
- Verification passed: local links and trailing whitespace across all eight Markdown documents, plus git diff --check. Normal improvement, validity correction, failure, comparison change, delayed submission, and interrupted-run cases were traced in the design; these are not runtime test results.
- Preserved historical review notes below; the Current plan supersedes their platform and benchmark proposals. No actual ML run or leaderboard submission was performed because no target ML project is present.
- 2026-10-03 lightweight-direction review: shower skill used a fresh reviewer given only the user's latest direction and the preceding product summary. Verdict: coherent product direction, insufficient design detail. No implementation or empirical product validation was performed.
- Main findings: missing definition of lightweight integration, task-specific appropriateness criteria, evidence/uncertainty contracts, review-versus-execution boundaries, and tool-quality acceptance tests. Existing adapter/environment design still prioritizes containers and execution infrastructure and is not aligned with the latest scope; its completed draft status does not mean it is approved for implementation.
- Recommended core: existing LLM-agent workflow plus small local checks and experiment records; preserve code correction and measured follow-up experiments instead of reducing the product to a passive checklist. Start with one complete bounded iteration, not a new execution platform.
- Validation approach: independently labeled erroneous, valid, and insufficient-evidence cases; measure missed issues, false alarms, warranted abstention, evidence correctness, setup effort, and incremental benefit against the same LLM without this tool. The reviewing LLM must not be the sole source of benchmark truth.
- ML reference check: scikit-learn common pitfalls (https://scikit-learn.org/stable/common_pitfalls.html) supports train-only fitted preprocessing and consistent transformations; cross-validation documentation (https://scikit-learn.org/stable/modules/cross_validation.html) supports task-aware splitting. These references support example checks, not a claim that this unimplemented product works.
- 2026-10-03 adapter/environment design: added docs/project-adapter-and-environment.md with user-selected Windows/Linux/macOS execution, optional containers, versioned logical contracts, fit/predict/scoring separation, artifact validation, capability reporting, and start/status/cancel/collect recovery semantics.
- Aligned README and research workflow with cooperative versus enforced evaluation protection and explicit prepare-result transitions. User-required environment selection is fixed; interface details remain a design proposal.
- Validation: read the full draft; traced representative OS/project paths plus unavailable devices, unsupported protection, invalid outputs, interrupted jobs, and environment changes. Local Markdown links and whitespace checks passed across six documents; `git diff --check` passed. No runtime or OS-support claims were verified because this is documentation-only work.
- Adapter/environment design plan (updated by user direction): let users choose execution environments on Windows, Linux, or macOS; Docker is optional. Define process-based fit/predict contracts, scoring boundaries, OS-specific execution capabilities, and recovery. This task produces design documents, not a running adapter.
- Revision result: addressed all five findings in docs/research-workflow.md; added stopping/unknown-job handling, explicit baseline evidence requirements, uncertain-result transitions, permitted evaluation feedback, and a separate frozen-selection final-test handoff.
- Verification: read the revised document end to end and traced normal adoption, failed repair, in-flight budget exhaustion, and uncertain-result paths. These are document-level checks, not runtime tests; implementation has not started.
- Document checks passed: local links and trailing whitespace across all five Markdown files, plus `git diff --check`. Recorded reusable workflow-review lessons in tasks/lessons.md.
- Revision plan: clarify termination cleanup, baseline registration, uncertain-result transitions, research feedback, and the final-test handoff. Validate by reading complete example paths and checking document links/whitespace; retain draft status and defer implementation details.
- 2026-10-02 critical review: used the shower skill with a fresh reviewer reading only an isolated copy of the complete workflow draft. The blind verdict was minor gaps for its declared design scope, not implementation readiness.
- Findings: clarify initial baseline registration versus the revalidation invariant; name the successor states for uncertain results; define the final-test handoff. Main-session review additionally identified missing shutdown/settlement semantics before finalization and an ambiguous boundary for evaluation evidence returned to the research agent.
- Review disposition: retain the responsibility split and sequential initial execution proposal; resolve workflow boundaries before implementation. Library choice, numeric thresholds, storage schema, and detailed unknown-job recovery remain legitimate follow-up design work. The draft itself was not modified during review.
- 2026-10-02 continuation: Read all four existing project documents; the working tree was clean and no implementation existed.
- Continuation scope: draft the first pending workflow design, check consistency with the product principles, and preserve unresolved adapter/environment choices for the next design step.
- Added docs/research-workflow.md as a review draft covering normal operation, retries, budget exhaustion, evaluation protection, and recovery. It does not claim agreed architecture or implemented behavior.
- Verification: checked the draft against the existing product scope and evaluation principles; local Markdown links and trailing whitespace checks passed across README, product direction, workflow, and this task record. `git diff --check` passed. No runtime tests apply because executable code has not been added.
- Repository inspection found only README.md before these planning notes.
- Product scope corrected based on user clarification; implementation has not started.
- README.md describes the product goal and current status; docs/product-direction.md preserves the conceptual graph, roles, evaluation principles, experiment memory, and open decisions.
- This documentation does not select an implementation stack or claim a working research loop.
- Documentation review checked the agreed product scope, conceptual graph, and explicit separation of open implementation decisions. Git staged whitespace validation passed; no executable code was changed.
- Delivery: commit these documents to main, push to origin, and verify the remote commit. The final delivery result is reported in the chat after the push.

## Delivery — CLI foundation
- User requested commit and PR targeting dev. Re-ran all 30 tests and git diff --check successfully before delivery. Exclude incidental .DS_Store; publish the feature branch for review without merging.

## PR #2 review follow-up — 2026-10-04
- Plan: reproduce legacy-encoding output failure and POSIX file/directory permission changes; apply focused fixes, run full regression suite, commit and update PR branch.
- Review disposition: accept all three inline comments (two underlying issues). Preserve existing file mode on replacement; initialize directories with OS-applied umask without changing the process-global umask. New standalone atomic-write files remain private; the current CLI uses this helper only for existing project.json.
- JSON terminal output uses ASCII escaping without changing Unicode values or Decimal precision; stored JSON remains UTF-8.
- Reproduction: all three new regression tests failed before changes, matching the review findings.
- Verification: all 33 unittest tests and git diff --check passed on macOS. cp1252 output simulated in a subprocess; native Windows execution remains unverified. No ML execution. Publish fixes on the existing PR #2 branch; merging is not part of this review follow-up.

## Experiment recording — 2026-10-04
- Scope: experiment create/update only; no training, comparison, decision or submission commands.
- Branch: feat/experiment-recording based on PR #2 head 5dcf804; origin/dev still lacked PR #2 at initial fetch despite reported merge. Recheck before delivery.
- Plan: add failing public CLI tests, implement generated snapshots and readiness/budget guards, immutable plans and valid execution transitions, then verify all tests and document usage.
- Completion: failed mutations preserve originals; experiment writes do not change project selection; completed results remain immutable and artifacts append-only.
- Initial verification: 8 of 9 new tests failed because experiment commands were absent; the malformed-input test already returned the expected argument exit code and is not counted as a behavior reproduction.
- Completed: experiment create/update, snapshot copying, readiness/budget checks, state transitions, new evidence for unknown resolution, immutable plans/decisions/terminal results and append-only artifacts. Added reusable create input and README usage.
- Verification: 45 tests passed; diff whitespace check passed; wheel/sdist built; installed wheel exercised init/project set/experiment create/update/check outside the repository. Independent review found no blocking issues in this scope. No actual ML execution; native Windows/Linux remain unverified.
- Remote recheck still reports PR #2 OPEN with mergedAt=null and dev at a6ff623. Follow-up work remains local on feat/experiment-recording pending actual base integration; no merge was performed.

## Delivery — experiment recording
- PR #2 merge confirmed at fe40b97 on origin/dev. User requested commit and PR for feat/experiment-recording.
- Pre-delivery verification: all 45 tests and git diff --check passed. Commit this increment, align with merged dev and publish a PR targeting dev; exclude incidental .DS_Store.

## Critical review — experiment recording
- Independent read-only review of fe40b97..5108ea6 found no blocking state/revision/immutability defects. Parent review reproduced a text-output UnicodeEncodeError after a successful experiment save under cp1252; added a failing regression then escaped unencodable characters in human output. JSON output and stored Unicode are unchanged.
- Direction assessment: still a dependency-free record helper; no process runner, Docker or LLM service. The end-to-end research workflow remains incomplete until review recording, comparisons/decisions and the agent skill exist.
- Follow-up design concern: save_experiment scans/hashes the complete history twice; large artifacts/history can make each update expensive. Separate mutation-local validation from explicit full evidence checks before large real-project use. No large-data performance benchmark was run.
- Contract wording to clarify: §4's prohibition on '..' should distinguish JSON storage destinations (ID confined) from read-only command/evidence/artifact references. Independent review reported this as a low-priority ambiguity, not a storage escape finding; no path behavior was changed.
- Final verification after review fix: all 46 unittest tests and git diff --check passed; publish both implementation and focused output fix in the dev-targeted PR.

## Git-based research history — 2026-10-04
- Goal: build on code commits and follow-up evidence/result commits, with no Docker or custom execution service.
- Plan: read-only Git status; opt-in experiment create --git-head binds clean code/config HEAD; document tracked records versus external data/artifacts; update both program templates and all current design docs; test in temporary Git repositories only.
- Compatibility: schema v1 code_ref remains a string; Git-backed records use git:<full SHA>. Legacy/manual code_ref remains accepted and is not Git-verified. No automatic git add/commit/checkout/reset/push in the CLI.
- Completion checks: staged/unstaged/untracked code blocks creation, record-only changes do not block it, HEAD stays unchanged, missing repository/commit is diagnosed; docs and templates agree on the two-commit flow.
- Initial three regression tests failed because Git commands/flags were absent.
- Completed docs: canonical Git history guide, README architecture/commands, product direction, workflow, environment connection, CLI contract, experiment report template, both program templates and fixture explanation.
- Independent review found trailing-space repository paths were trimmed; reproduced with a failing test and fixed by removing only Git's final newline. Documented Git-visible cleanliness and ignored/external input limits.
- Verification: 51 tests passed; 33 local Markdown links and packaged/source template equality passed; wheel/sdist built; installed wheel exercised Git status and --git-head creation with updated instructions outside the repository. The separate result-commit test preserves the original code SHA. No ML executed. Windows/Linux native execution remains unverified.

## Design verification — Git history document set
- Used shower skill with a context-free reviewer reading an isolated copy of all eight focused documents (712 lines). Reviewer opened no neighboring source files. Verdict: needs work; intended lightweight Git/JSON/agent responsibility split was correctly understood.
- High-priority gaps: no correction lineage for a mistyped immutable terminal experiment result; unknown requires a known start timestamp although guidance includes unknown execution/start; abandoned planned records have no non-executed closure and continue consuming the creation budget.
- Document inconsistencies: workflow asks for metric/time settings in program.md while contract/template prohibit duplicated JSON settings; report template fields lack explicit JSON-source/missing-value mappings.
- Additional operating gap: preserve unrelated user changes versus whole-repository clean requirement has no documented worktree/defer path. Do not silently commit or reset those changes.
- Evidence: inspected state/validation code and confirmed never-run interrupted closure is rejected for absent start/finish times. Checked 26 local design links and source/package program template equality. No ML execution; no claim of full runtime or defect-free verification.
- Review only: no design decisions or implementation changed in this audit. Recommended next work is defining correction, unknown-start and planned-cancellation semantics before extending the research loop, then aligning the document source-of-truth and report mapping.

## Lifecycle fixes and research delivery — 2026-10-04
- Dedicated branch feat/git-history-lifecycle carries uncommitted Git tracking work and fixes from the design audit. PR #4 remains open; new PR will identify that prerequisite while targeting dev.
- Plan: regression-test no-start unknown/cancel and append-only corrections; keep records and original refs; define budget/selection semantics; align all docs and report field mapping; verify package and independent review; create separate PR and research-backed issues.
- TDD: six lifecycle regressions failed before implementation. No ML execution is authorized or needed.
- Compatibility: experiment.correction is the only optional v1 extension (omission means null); new records include it. Corrections point to original execution records and do not consume another run; cancelled never-run plans release their budget slot.
- Research: checked primary arXiv pages through September 2026 and official autoresearch repository; created issues #5–#8 with evidence, dates, acceptance criteria and explicit lightweight non-goals. Investigation targets research search trees/DAGs rather than unrelated GNN modeling.
- Independent lifecycle review found optional correction omission could raise KeyError; added a failing regression and fixed null/omission compatibility. Report mapping now displays raw evidence references without inventing values from arbitrary logs.
- Final verification: all 61 tests passed; 43 local documentation links and source/package template equality passed; git diff --check passed. Wheel/sdist built, and an isolated installed-wheel smoke check passed unknown-start recovery, success, correction, cancellation, original-byte preservation, budget accounting and packaged instructions. No ML executed; native Windows/Linux remain unverified.
- Research deliverables: https://github.com/ziholee/zihoAutoResearch/issues/5 (lineage), /issues/6 (failure memory), /issues/7 (comparison), /issues/8 (candidate selection). Primary-source findings and application limits are recorded in docs/research-update-2026-10.md.

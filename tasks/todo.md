# AutoResearch tool design

## Objective
Build a lightweight workflow that helps an LLM understand existing ML projects, check preprocessing/training/validation, and improve the complete pipeline using existing commands and evidence-backed experiments.

## Current plan — updated 2026-10-06

Current completion target is the reusable tool itself; real ML application is performed later by the user. Current scope supersedes earlier platform-oriented proposals: a lightweight LLM research workflow in existing ML projects. No Docker requirement, custom execution platform, or separate tool-quality benchmark in the initial scope. Existing data, local validation, and competition scores provide the experimental feedback.

- [x] Consolidate product definition, workflow, and project connection around the lightweight loop.
- [x] Adapt Karpathy's research instructions, baseline-first loop, bounded experiments, and evidence-backed keep/discard decisions.
- [x] Add reusable project instructions and experiment record templates.
- [x] Verify leakage correction, failed runs, incomparable scores, submission linkage, and safe continuation paths at the document level.
- [x] Independently review the revised documents and resolve concrete gaps.
- [x] Freeze v1 usage flow, CLI commands, file fields, and error/state rules.
- [x] Review representative JSON examples and resolve interface inconsistencies.
- [x] Implement the LLM skill and supported CLI loop (project/experiment/Git/compare/decide), with mock adoption/hold and resume checks.
- [x] Implement review add with evidence diagnostics and append-only corrections.
- [ ] Implement the remaining submission/report commands.
- [ ] Verify the complete v1 tool with sample files and simulated results; current subset passes, remaining commands pending. Do not run actual ML training or submit models.
- [ ] Complete v1 packaging and usage instructions; CLI wheel, source-distributed skill, and mock-cycle examples are available for the implemented subset.

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

## PR #4 evidence retention follow-up — 2026-10-04
- Scope: accept the evidence deletion/reuse review finding; defer file-mode changes because shared-user access is not a current requirement. Preserve 0600 for new atomic files.
- Plan: add a failing public CLI regression; require append-only execution evidence on updates; document nonterminal correction by retained evidence plus note/new source; run full suites and publish to PR #4, then integrate into dependent PR #9.
- Reproduction: the new regression failed because running/unknown evidence deletion was accepted, allowing old evidence to be reused as new confirmation. No actual ML execution.
- Verification: all 47 tests passed on PR #4 branch, including rejected deletion/replacement/reordering preserving original bytes, old-evidence-only resolution rejection and appended confirmation success; git diff --check passed. Native Windows/Linux not tested.
- Integration into PR #9: preserved both task histories, updated the unknown-start fixture to append confirmation rather than replace earlier evidence, and passed all 62 tests plus git diff --check. The correction command still creates a separate record and preserves the original.

## Issue #7 comparison and decisions — 2026-10-04
- Branch feat/comparison-decisions from merged origin/dev 6520a35.
- Scope: read-only compare, revision-guarded decide with immutable decision history, exact decimal delta/threshold, explicit optional run_context (scope/seed/budget_ref), conservative confirmation statistics and stale baseline diagnostics. No ML, automatic keep/selection or execution service.
- Plan: failing CLI/decimal regressions; implement schema-compatible optional context and comparison/decision logic; align docs/templates; full tests and independent review.
- Completion: mismatched or unknown scope/budget/environment blocks numeric comparison; ties never count as improvement; active same-plan confirmation counts exclude superseded originals, single-run variance remains unknown; evidence availability remains distinct from content truth; decision updates preserve project selection and original execution.
- Implemented compare/decide with optional immutable run_context, explicit unknown constraints, exact decimal subtraction and rational repetition statistics. No new evaluation server or duplicate Comparison schema.
- Initial regressions failed before implementation (run_context rejected); two test setup errors also exposed the existing changed-comparison-ID guard and were corrected without changing that guard.
- Independent review found command mismatch aggregation and lost confirmation links after anchor correction. A new regression reproduced the lost-link failure; fixed command matching and ancestry lookup while preserving explicit baseline references and excluding superseded originals.
- Intermediate full suite: 72 tests passed. Added final cases for corrected confirmation deduplication, unknown seeds/environment, missing evidence versus numeric comparability, evidence-free keep rejection and tie keep by explicit decision. Final verification pending below.
- Final verification (2026-10-05 KST): all 75 unittest tests passed; git diff --check passed; 39 local links across README/docs/templates and source/package template equality passed. Wheel/sdist built; an isolated installed wheel exercised init/project set/create/update/compare/decide/check and preserved selection. No ML executed; native Windows/Linux remain unverified.
- Independent final review found no further blocking issues. Existing missing run_context and corrected baseline references remain immutable and explicitly limited; no automatic migration or silent baseline redirection.
- Implementation is on feat/comparison-decisions in the working tree; no commit, PR publication or issue closure requested in this increment.

## Delivery — comparison and decisions — 2026-10-05
- User authorized continuing with commit and a PR targeting dev after the progress briefing.
- Plan: align README implementation status, rerun the full regression suite and documentation/package checks, commit the comparison increment, push the branch and open a dev-targeted PR referencing #7.
- Completion: verify the published branch SHA and PR base/head; leave merging and issue closure to integration. Preserve the unrelated .DS_Store file.
- Verification: reran all 75 unittest tests successfully; git diff --check, 39 local documentation links and source/package template equality passed. Fresh wheel/sdist build passed. README now lists compare/decide as implemented; origin/dev still matches the branch base 6520a35. No ML execution; native Windows/Linux remain unverified.

## LLM skill and mock research cycle — 2026-10-06

- Goal: connect the implemented CLI to reusable agent instructions and demonstrate one bounded research cycle with simulated observations.
- Branch: codex/llm-research-skill from comparison commit 6fdd193; depends on PR #10, which was open at the progress check. No merge or publication in this increment.
- Scope: repository-distributed skill with self-contained CLI recipes, executable mock example, behavioral verification, and usage/status documentation. No real training, submission, LLM service, or new review/submission/report commands.
- Plan: write the skill and command reference; build a fresh-directory mock baseline/candidate cycle; test adoption and incomparable hold paths plus non-overwrite behavior; independently apply the skill in isolated mock scenarios; run regression and structural checks.
- Completion: current selection and workspace identity remain explicit; unknown jobs are not repeated; missing evidence/comparison conditions are not turned into success; immutable records are changed only through supported commands. Record concrete verification below.
- Implemented: skills/ziho-autoresearch with a standalone entrypoint and CLI input recipes; examples/mock-cycle.py with comparable adoption and scope-mismatch hold; three integration tests for record outcomes, workspace/selection distinction, no training execution and destination preservation. CLI runtime behavior remains unchanged.
- Distribution: MANIFEST.in includes the skill, recipes, example, fixtures and linked documentation in the source archive. The wheel remains CLI-only; README explains source-based skill use and does not claim global agent installation or automatic discovery.
- Independent forward testing: an isolated agent used only the skill/recipes and supplied synthetic observations. It retained baseline selection on proxy/full mismatch, recorded hold with no numeric delta, and preserved unknown-start work without retrying when no new confirmation existed. Parent inspected command transcript and final JSON artifacts. The trial exposed a missing init-root precondition; clarified that the target directory must already exist.
- Verification: all 78 unittest tests passed on macOS/Python 3.14 (including three new example integration tests); official quick_validate.py passed using PyYAML in a temporary verification environment; 44 local Markdown links, source/package program template equality and git diff --check passed. Source archive and wheel built successfully. Outside the repository, the freshly installed wheel ran both examples extracted from the source archive; adoption selected mock-candidate, hold retained mock-baseline, and actual workspace identity was reported separately. Source-archive local links also passed.
- Verification artifacts: /private/tmp/zar-skill-verification-20261006 contains build logs, distributions and installed-example outputs; /private/tmp/zar-skill-trial-rU7zA9 contains independent trial inputs, command transcript and outcomes. Initial host validation lacked build/PyYAML; required development tools were installed only in a temporary venv, without adding runtime dependencies.
- Limits: bounded mock scenarios do not establish ML research quality or compatibility with every agent. No actual ML, submission, global skill install, native Windows/Linux execution, commit, push or PR creation. Remaining product work is review/submission/report commands and complete-v1 verification.

## Evidence-first context architecture — 2026-10-07

- Goal: apply SoL-Pi's selective recall and evidence preservation to the existing lightweight tool without introducing an agent runtime or model service.
- Scope: invocation-scoped record snapshots; read-only `context` with bounded JSON output and explicit omissions; `evidence read` with registered references, exact UTF-8 line recall and content identity checks; align the skill, architecture, workflow and current contracts. Preserve prior uncommitted skill work and schema v1 records.
- Plan: define contracts and regression expectations; implement snapshot, context and evidence modules with separate ownership; integrate CLI; independent review; full suite, package smoke and document checks.
- Context contract: deterministic prioritized cards (focus/selected/baseline, unfinished, related failures, recent history), offset/limit pagination, full-project blocker counts, bounded successful JSON envelope, explicit metadata-only evidence scope. No semantic summarizer or automatic selection. `--max-bytes` measures ASCII-escaped JSON envelope bytes and errors if indispensable metadata cannot fit.
- Evidence contract: JSON Pointer to a registered evidence object in an experiment/review/submission; streamed hash and exact whole-line page from the same read; reject changed recorded hashes, nontext and nonregular sources; unhashed references are explicitly unverified. Original files are not rewritten or automatically archived; remote sources are not fetched.
- Completion/verification: unknown and failure counts survive truncation; omitted cards/diagnostics are visible; source identity and line boundaries survive recall; malformed metadata still fails; full `check` retains evidence checks; no mutation except temporary cooperative locks; regression tests and installed CLI run without ML execution. Runtime savings are measured only where tested, not inferred from SoL-Pi results.
- Completed: records.py provides an invocation-scoped validated snapshot reused by state/compare/mutations/context; context.py provides prioritized paginated cards, global safety counts, explicit preview/diagnostic omissions and a successful-envelope byte bound; evidence.py provides exact streamed UTF-8 pages, recorded and caller-pinned SHA-256, revision pins, and explicit unsupported/missing/changed-source failures. No schema migration or persistent cache.
- Regression evidence: context initially failed because the command was absent; three initial setup failures came from Decimal serialization in the test helper and were corrected before the five missing-command failures were confirmed. Evidence module tests failed before the module existed. Added snapshot reuse/overlay/validation checks, CLI paging/source-change tests, original correction-reference retention and long-comparison-ID cases.
- Independent implementation review reproduced one valid-input failure: an unbounded Comparison ID could make every context page exceed even the largest output budget. Added a regression and marked comparison-ID previews as truncated with source references. Corrected a macOS /var versus /private/var alias in read-count instrumentation. No remaining blocking issue was reported in the reviewed scope.
- Independent skill trial used the installed CLI on an isolated mock project with 102 records. It found the selected candidate, unseen unknown work and exhausted budget; refused changed evidence; distinguished current workspace byte identity from past execution proof. A concurrent read encountered the existing cooperative lock, so skill/recipes now explicitly serialize same-project CLI calls without deleting locks.
- Final verification: 108 unittest tests passed on macOS/Python 3.14; official skill validator passed; 52 local documentation links, template/package equality and diff whitespace passed. Fresh source archive and wheel built. A separate installed-wheel environment outside the repository ran both revised mock examples and emitted context/evidence-page artifacts; source-archive links and templates also passed.
- Output measurement: one synthetic 102-record history occupied 2,730,201 experiment-JSON bytes. With an 8,192-byte cap, the first context envelope was 8,134 bytes and returned 5 cards while preserving unknown=1 and failed=1. All 102 records were recovered once across snapshot-pinned pages. Measured local first-call wall time was 0.1868 seconds; this is not a representative performance or provider token/cost benchmark. Measurement and package artifacts are under /private/tmp/zar-context-verification-20261007.
- Documentation aligned: README architecture/usage, product direction, workflow, CLI contract, research update, the new context-and-evidence contract, both program templates, skill and command recipes. Remaining v1 review/submission/report commands and dedicated failure-memory policies stay explicitly pending.
- Limits: metadata context still scans all JSON; evidence pages hash their entire target on every call; existing mutations retain both full evidence checks. Original files are not archived or restored; concurrent filesystem changes are only best-effort detected. No ML, external submission, native Windows/Linux verification, provider-cost claim, commit, push or PR creation. Earlier uncommitted skill work and unrelated .DS_Store remain preserved.

## Skill-guided verification — 2026-10-07

- User requested verification with skills. Apply verification-before-completion for fresh execution evidence and sip for changed-scope risks; no commit or publication.
- Plan: fresh full regression suite; independent bounded risk review; skill/schema/document consistency checks; fresh package build and isolated installed-wheel examples. Resolve supported defects, rerun affected checks, and record limitations.
- Completed: fresh full suite passed 108 tests on macOS/Python 3.14; official skill validator, 52 local documentation links, template/package equality and diff whitespace checks passed.
- Additional independent expectations: 100 generated UTF-8 files reconstructed exactly across 436 evidence pages, including LF/CRLF and final-line variants. Independent sip reviewer checked 350 evidence boundary combinations and paginated 80 records under a 4,096-byte envelope cap, confirming no omissions/duplicates, preserved unknown/failed totals and unchanged source dictionaries. No confirmed defect was found in this bounded review.
- Packaging: rebuilt source archive and wheel, installed the new wheel without dependencies into a fresh temporary environment, confirmed imports came from site-packages, and ran both source-archive mock examples outside the repository. Comparable adoption selected mock-candidate; scope mismatch held the candidate and retained mock-baseline. Evidence text/hash, no training execution and byte-for-byte preservation of project files after context/check/status reads all passed.
- Evidence: /private/tmp/zar-skill-audit-tests-20261007.log (108 tests), /private/tmp/zar-skill-audit-build-20261007.log (build), and /private/tmp/zar-skill-audit-20261007 (distributions, fresh environment and example outputs). No production change was needed; this verification record is the only new repository edit in this cycle.
- Limits: bounded synthetic verification does not establish real ML quality, provider-cost savings or native Windows/Linux compatibility. Concurrent filesystem changes retain the documented best-effort size/mtime detection limit. No ML execution, commit, push, PR or external submission was performed; pending v1 product features remain pending.

## RRSI-inspired pre-execution review — 2026-10-07

- Goal: complete the highest-priority review registration contract and apply RRSI's evidence-backed pre-evaluation screening through the existing research skill. Preserve existing local context/evidence/skill work and include it in the requested PR; exclude unrelated .DS_Store.
- Plan: implement review add with generated metadata, full validation and append-only same-version corrections; regression-test rejected writes and experiment links; update skill, recipes and product docs; independent review, full suite and isolated package smoke; commit and create a PR targeting dev after checking remote state.
- Scope: existing Finding fields describe declared changes/hypotheses, evaluation integrity and limits; the agent reviews evidence, CLI validates records. No automatic critic, runtime, new scoring rule or schema migration. Submission/report remain pending.
- Acceptance: incomplete project settings permit review registration; invalid schema/links or duplicate IDs preserve originals; missing/changed source files retain existing warning semantics; review supersession does not redirect experiment links or alter selection; documentation distinguishes recorded review from proof of ML validity.

- Completed: review add accepts only author fields, generates metadata, rejects global ID collisions, validates a copied record snapshot and writes one new canonical file. Same-version active-target corrections retain original bytes and all existing links. Added seven regression tests; implementation was available before test execution, so no missing-command red result is claimed.
- Verification: 115 unittest tests passed on macOS/Python 3.14; official skill validator, 54 local documentation links, template equality and git diff --check passed. Fresh wheel/sdist build and isolated wheel installation passed both source-archive mock cycles and incomplete-project review registration/correction/context smoke. Independent review additionally injected replacement failure and tested symlink collisions: original files stayed unchanged, temporary files/locks were cleaned up; no confirmed defect found.
- Documentation: README, v1 contract, workflow, research update, skill/recipes and both program templates distinguish pre-execution agent review from automatic CLI enforcement. Missing/changed evidence retains warning semantics; selection and immutable experiment links are never rewritten by review registration.
- Delivery: current branch includes prerequisite comparison commit 6fdd193 from open PR #10. Publish a dev-targeted PR with this dependency called out, including the previously verified skill/context/evidence work; do not merge. No real ML, external submission, native Windows/Linux test or cost-saving claim.

## PR #11 document and conversation audit — 2026-10-07

- Scope: inspect published head bae83798d6023df6688cc93d39569bfa4f61830c using sip and verification-before-completion; compare code/docs/skill against the agreed lightweight workflow, SoL-Pi selective recall and bounded RRSI pre-execution review. Two independent readers reviewed contracts and scope. Review only: no product edits, commit, push or merge.
- Fresh verification: full unittest suite passed 115 tests (23.810s; /private/tmp/zar-pr11-audit-tests.log). Published PR head matches local HEAD.
- Finding P2: docs/context-and-evidence.md example hardcodes offset 5 instead of returned page.next_offset. Reproduced with six schema-valid mock records and 16,384-byte budget: first page returned three cards with next_offset=3; offset=5 skipped two records. Body and skill correctly require next_offset, so fix the example.
- Finding P2: templates/program.md and packaged zar/program.md unconditionally preserve selection on hold, omitting the skill's explicit deselection of a known-invalid selected baseline. Align the templates and workflow table with the valid-baseline exception; CLI hold not changing selection remains correct.
- Finding P3: docs/context-and-evidence.md describes all same-class ordering as reverse created_at/ID, but ancestry uses baseline/parent/correction traversal; newest-first applies to unfinished/related unsuccessful/recent groups only.
- Scope verdict: no added LLM runner, Docker, real training, automatic semantic compression, external submission or automatic cost/noise policy. Evidence warnings are not automatic ML approval; original records and links remain preserved. submission/report remain explicitly pending. The three document findings remain open for a focused correction; runtime tests do not establish prose consistency.

## PR #11 document corrections

- User authorized fixing the three audit findings. Plan: replace fixed-offset example with returned pagination fields; describe ancestry traversal separately from recent ordering; align source/packaged instructions and workflow on deselecting an invalid baseline. Verify links, templates and relevant context/selection behavior, then publish the correction to PR #11 without merging.
- Resolved all three audit findings: pagination example uses next_offset and stops on null; ancestry order matches baseline/parent/correction breadth-first traversal; both program templates and workflow preserve only a valid selection and explicitly deselect an invalid baseline. Runtime code unchanged.
- Verification: context tests 10/10 and comparison/selection tests 13/13 passed; 54 local links, source/package template equality and git diff --check passed. Existing 115-test full-suite result belongs to the preceding audit; no new full-suite claim. Publish only the six documentation/record files; preserve unrelated .DS_Store.

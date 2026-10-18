# zihoAutoResearch

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

[![PyPI version](https://img.shields.io/pypi/v/ziho-autoresearch?logo=pypi&logoColor=white)](https://pypi.org/project/ziho-autoresearch/)
[![Python 3.11 or later](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Contract CI](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml/badge.svg?branch=dev&event=push)](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml?query=branch%3Adev)
[![Agent Skills: Codex / Claude Code](https://img.shields.io/badge/Agent%20Skills-Codex%20%2F%20Claude%20Code-5865F2)](docs/agent-installation.md)

**A lightweight CLI and agent skill that records experiment evidence, results, and decisions locally in your existing ML project, so you can pick up where you left off in the next session.**

When you change preprocessing, models, loss functions, or optimization methods, keep a record of why you tried each change, under what conditions you compared it, and what you adopted. Use your existing project without moving your data or training environment to a new platform.

The badges show the latest PyPI version, supported Python version, license, CI status for the `dev` branch, and supported agents. Click each badge for details.

[PyPI](https://pypi.org/project/ziho-autoresearch/) · [GitHub releases](https://github.com/ziholee/zihoAutoResearch/releases) · [Changelog](CHANGELOG.md) · [Report an issue](https://github.com/ziholee/zihoAutoResearch/issues)

> This README is available in English. The detailed documentation and skill references linked below are currently primarily in Korean.

## What does it do?

- **CLI (`zar`)**: Saves experiment plans, observations, comparisons, and decisions as JSON, and checks their format, references, and evidence files.
- **Agent skill**: Guides your coding agent through a research workflow within the scope you authorize, using your existing project.
- **Resuming and reporting**: Looks up unfinished experiments, failure memory, candidate rationale, and experiment lineage, and generates Markdown reports.

The record commands in public v0.3.0 do not call an LLM or run training. **The development branch adds an unreleased `research` command.** It sends role-specific instructions to an OpenAI-compatible API or installed Codex and runs and records one local experiment after user approval. See the [API research session guide](docs/research-api.md) for connection, approval, recovery, and verification scope. Real cloud API connections remain unverified; automatic code restoration and competition submission are not provided. Passing `check` does not establish that there is no data leakage or that a model is good.

**Development source only:** Run `zar research setup --project ./my-ml-project` in an interactive terminal to answer questions and reach a first experiment plan without editing JSON. Saving and model transmission require separate confirmation; setup stops for plan approval. Bring your existing training code and evaluation protocol. See the [interactive setup guide](docs/research-api.md#질문에-답해-첫-계획-만들기). If a pre-execution plan is blocked or needs changes, use `zar research revise SESSION_ID --project ./my-ml-project` to answer follow-up questions and create a linked new plan. `research status` provides next-action guidance; the revised plan requires fresh approval.

Use `baseline` mode to measure the current original code without model edits. Candidate plans require a compatible selected valid keep experiment. After completion, `zar research next SESSION_ID --project ./my-ml-project` carries settings and bounded decision/memory context into a new plan, with a fresh metric path, transmission consent and approval. It does not restore code or run experiments automatically.

In development source, select installed Codex with `research start --provider codex --codex-command codex --model <model>` or choose the backend in `research setup`. This requires a trusted Codex CLI 0.162.1 or later on macOS/Linux. It uses existing Codex authentication and may send context to a billable model service. Codex returns proposals; zar retains its transmission, execution and decision approval steps. Validation uses a fake agent; actual Codex authentication/inference remain unverified. See [connection scope and limits](docs/research-api.md#설치된-codex로-연결하기).

In development source, `zar research metrics SESSION_ID --project ./my-ml-project --json` reports role-call time, message bytes and reported token usage. Missing values and partial observations remain explicit; it does not estimate delivered network traffic or cost. See [measurement scope](docs/research-api.md#역할별-호출-측정-조회).

`zar` is **the abbreviation for zihoAutoResearch and its executable command**. The package you install is named `ziho-autoresearch`; after installation, use commands such as `zar init` and `zar status`.

## 1. Install

Requires **Python 3.11 or later**. There are no external runtime library dependencies. The Git executable is required only for Git integration features.

If you have [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install ziho-autoresearch
zar --help
```

The pinned-version examples below use v0.3.0. Check the [release list](https://github.com/ziholee/zihoAutoResearch/releases) for current releases.

If `zar` cannot be found, run `uv tool update-shell` and reopen your terminal. To pin a version, use `uv tool install 'ziho-autoresearch==0.3.0'`; to update, use `uv tool upgrade ziho-autoresearch`. See the [uv guide](docs/uv-installation.md) for updating pinned versions or URL installations.

To install without uv:

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# On Windows PowerShell, use this instead of the line above:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
zar --help
```

## 2. Connect an existing project

Replace `./my-ml-project` below with an **existing ML project directory**. On Windows too, wrap paths containing spaces in quotes.

```sh
zar init --project ./my-ml-project
zar status --project ./my-ml-project --json
```

This creates `.autoresearch/` inside the project. Existing code, the root `program.md`, and `AGENTS.md` are preserved. If you omit `--project`, the current directory is used; parent directories are not searched automatically.

Seeing `ready:false` initially is normal. You need to fill in the objective, comparison metric, data and code identifiers, execution environment, commands, budget, and paths that may be modified. Ask the agent in the next step to help configure these, or follow the [first-run guide](docs/first-run-and-resume.md) yourself.

## 3. Use the skill in an agent

### Install directly for Codex / Claude Code

**Available from v0.3.0.** See the [agent installation guide](docs/agent-installation.md) for installation options and the full procedure. Once the CLI is installed, choose the agent you use.

```sh
# Codex: install only in the specified ML project
zar skill install --agent codex --project ./my-ml-project

# For Claude Code
zar skill install --agent claude --project ./my-ml-project
```

The command creates the required skill directories and copies the complete bundle. It does not overwrite existing skills. Open the target project in your agent, select `$ziho-autoresearch` in Codex or `/ziho-autoresearch` in Claude Code, and ask:

> Inspect this project without running training, and propose a plan for the first experiment.

If the skill does not appear in the list, restart your agent and check its skill settings. `zar --help` must also work in the agent's execution environment. Since the skill is installed in a discovery location, manually linking it in `AGENTS.md` is not required for basic use. Installing the skill does not authorize training or verify that the agent actually recognizes it.

### Connect manually in other agents

Run the following from a convenient working directory outside your ML project. `--dest` specifies a **new skill directory to create**; its parent directory must already exist.

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json
```

This extracts `SKILL.md` and the complete `references/` directory bundled in the wheel. It does not overwrite an existing directory or register the skill automatically with an agent. Give the printed absolute path to your coding agent:

> Read `<printed skill directory>/SKILL.md` and inspect `<absolute path to the ML project>`. First, without executing anything, summarize the current code, data, evaluation method, and missing configuration, then propose a plan for the first experiment.

When delegating experiment execution too, specify the **objective, allowed modification paths, execution environment, and limits on run count and time**. Do not paste secret keys or raw personal information into conversations or experiment evidence. When updating the skill, extract it into a new directory and compare it with your customizations.

### Link the skill in your project's AGENTS.md

To keep a manual connection or specify when the skill applies to a project, add the skill's `SKILL.md` path and usage conditions to the **experiment project's** `AGENTS.md`. Preserve existing rules; do not copy the full skill or frequently changing experiment state into it. Check your agent's settings to ensure it reads that instruction file.

The following command for generating linking instructions is available from v0.3.0.

```sh
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0
```

This prints linking instructions that include the location of an existing skill. Review the output and merge only the relevant parts into the target project's existing `AGENTS.md`. It does not create or overwrite files, or automatically register the skill with an agent. Do not redirect the output with `> AGENTS.md`, because the shell may erase the existing file. You can also use the [manual linking example](docs/uv-installation.md#프로젝트-지침에-연결) with the published release.

## 4. Check records and resume

```sh
zar status --project ./my-ml-project --json
zar context --project ./my-ml-project --max-bytes 16384 --json
zar check --project ./my-ml-project --json
```

- `status`: Checks missing configuration, the current selection, unfinished experiments, and budget.
- `context`: Retrieves size-limited context to pass to a new session. It does not check evidence file existence or hashes.
- `check`: Checks records and evidence. Read the warnings as well as the exit code. Incomplete initial configuration may produce exit code 3.

After an interruption, you can ask your agent:

> Read the same skill and project, and check the current state with `context` and `status`. Do not rerun an `unknown` experiment until you have checked its actual logs and process state. Reconcile its status using new evidence.

**A recorded adoption decision is separate from the code in your actual working directory.** A `keep` decision or selection change does not restore code. See the [first-run and resume guide](docs/first-run-and-resume.md) for the precise interruption and recovery procedure.

## Workflow for recording results directly

You can write JSON inputs yourself or review drafts prepared by an agent. The [CLI recipes](skills/ziho-autoresearch/references/cli-recipes.md) provide input examples; the [file contract](docs/cli-and-file-contract.md) describes required fields and state transitions.

| Purpose | Command | Guidance |
|---|---|---|
| Initialize a project | `zar init` | Creates the record directory in an existing project |
| Generate linking instructions | `zar skill guidance --skill-dir` | Prints text for AGENTS.md using an existing skill path |
| Install for an agent | `zar skill install --agent` | Installs into a Codex/Claude Code discovery location |
| Extract the skill | `zar skill install` | Copies the skill into a new directory |
| Save configuration | `zar project set --file <json>` | Copy the current project.json into a separate draft and edit it |
| Review before execution | `zar review add --file <json>` | Record verified evidence and unverified items |
| Record the next candidate | `zar candidate add --file <json>` | [Observations, predictions, and selection rationale](docs/candidate-rationale.md) |
| Create an experiment / update results | `zar experiment create`, `zar experiment update` | [Input example](examples/experiment-create.json); record actual observations only |
| Compare and decide | `zar experiment compare`, `zar experiment decide` | Check comparison conditions such as proxy/full; no automatic code adoption |
| Correct completed results | `zar experiment correct` | Preserves the original under its ID and creates a new record ID |
| Record failure memory | `zar memory add --file <json>` | [Failure causes, responses, and limits](docs/failure-memory.md) |
| Record a verified external score | `zar submission add --file <json>` | Perform the actual submission separately |
| Read original evidence | `zar evidence read` | [Hashes and partial reads](docs/context-and-evidence.md) |
| View experiment relationships | `zar lineage` | [JSON and Mermaid lineage](docs/experiment-lineage.md) |
| Generate a report | `zar report --output summary.md` | Saves to `.autoresearch/reports/summary.md` |
| Link a code commit | `zar git status`, `zar experiment create --git-head` | [Using Git history](docs/git-research-history.md) |

You can also append `--project <project path>` to these commands. See `zar <command> --help` for detailed arguments. Write JSON inputs to a different file from the original. If you use `.autoresearch/drafts/`, you must create it yourself first.

## Try it without training

Examples are not included in the wheel. Extract the [source distribution](https://github.com/ziholee/zihoAutoResearch/releases/tag/v0.3.0) or download this repository, then run the following from the source directory in a Python environment with the CLI installed.

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# On Windows PowerShell, use this instead of the line above:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
python examples/mock-cycle.py --output ./demo-cycle
```

`demo-cycle` must be a new path that does not exist yet. The example uses mock scores and logs to demonstrate recording → comparison → decision → reporting, without training. The Python environment used by uv tool and a separate Python environment do not share packages, so install the package in the example's virtual environment as shown above. See the [resume example](docs/first-run-and-resume.md#학습-없는-두-세션-연습) for a two-session exercise.

## Before sharing records

`.autoresearch/` and reports may contain commands, file paths, log excerpts, and evidence you recorded. Check for secret keys, personal data, private datasets, and private logs before committing or uploading them. The CLI's JSON validation does not detect secrets or anonymize data automatically. Modifying original evidence may invalidate its stored hash, so create a separate copy for public sharing.

If a lock remains, verify that no CLI process is running before recovering. Do not blindly delete `.autoresearch/.lock` or `.autoresearch.init.lock` in the project root. For large record histories, start with `context`. Full output from `report` and `lineage` has no size limit.

## Learn more

- [Agent installation, invocation, and troubleshooting](docs/agent-installation.md)
- [Installation, updates, and skill updates](docs/uv-installation.md)
- [From initial setup to interruption and resumption](docs/first-run-and-resume.md)
- [Research workflow and decision rules](docs/research-workflow.md)
- [Project integration and environment configuration](docs/project-adapter-and-environment.md)
- [Record-scale performance measurements and limitations](docs/record-scale-performance.md)
- [Product direction and research references](docs/product-direction.md)
- [Release artifact verification](docs/releasing.md) · [Contribution and CI requirements](docs/automation.md)

Software verification primarily uses synthetic records; it does not guarantee real-world ML quality or reduced training costs. Licensed under [MIT](LICENSE).

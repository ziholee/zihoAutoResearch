# zihoAutoResearch

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

[![PyPI 版本](https://img.shields.io/pypi/v/ziho-autoresearch?logo=pypi&logoColor=white)](https://pypi.org/project/ziho-autoresearch/)
[![Python 3.11 及以上](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT 许可证](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![契约检查 CI](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml/badge.svg?branch=dev&event=push)](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml?query=branch%3Adev)
[![智能体技能：Codex / Claude Code](https://img.shields.io/badge/Agent%20Skills-Codex%20%2F%20Claude%20Code-5865F2)](docs/agent-installation.md)

**一款轻量级 CLI 和智能体技能，用于在本地记录现有 ML 项目的实验证据、结果与决策，并在下一次会话中继续工作。**

调整预处理、模型、损失函数或优化方法时，同时记录“为什么尝试、在什么条件下比较、最终采用了什么”。直接在现有项目中使用，无需将数据或训练环境迁移到新平台。

上方徽章展示最新 PyPI 版本、支持的 Python 版本、许可证、`dev` 分支的 CI 状态及支持的智能体。点击各徽章可查看详情。

[PyPI](https://pypi.org/project/ziho-autoresearch/) · [GitHub 发布](https://github.com/ziholee/zihoAutoResearch/releases) · [更新日志](CHANGELOG.md) · [问题反馈](https://github.com/ziholee/zihoAutoResearch/issues)

本文为简体中文使用指南；链接中的详细文档目前主要使用韩语。

## 这是什么工具？

- **CLI（`zar`）**：以 JSON 保存实验计划、观测、比较和决策，并检查格式、引用及证据文件。
- **智能体技能**：指导你使用的编程智能体读取项目，并在授权范围内遵循研究流程。
- **恢复与报告**：查看未完成实验、失败记录、候选方案依据及实验谱系，生成 Markdown 报告。

公开版 v0.3.0 的记录命令不会调用 LLM 或执行训练。**开发分支新增了尚未发布的 `research` 命令。** 它向 OpenAI 兼容 API 传递各角色的指令，并在用户批准后执行和记录一次本地实验。连接、批准、恢复流程及验证范围请参阅 [API 研究会话指南](docs/research-api.md)。真实云端 API 连接尚未验证，也不提供自动代码恢复或竞赛提交。通过 `check` 并不代表已确认不存在数据泄漏或模型质量合格。

`zar` 是 **zihoAutoResearch 的简称，也是可执行命令**。安装包名为 `ziho-autoresearch`，安装后通过 `zar init`、`zar status` 等命令使用。

## 1. 安装

需要 Python **3.11 及以上**。运行时不依赖外部库。仅在使用 Git 集成功能时需要安装 Git 可执行程序。

如果已安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```sh
uv tool install ziho-autoresearch
zar --help
```

下方固定版本示例以 v0.3.0 为准。当前发布状态请查看[发布列表](https://github.com/ziholee/zihoAutoResearch/releases)。

如果找不到 `zar`，请运行 `uv tool update-shell` 后重新打开终端。固定版本使用 `uv tool install 'ziho-autoresearch==0.3.0'`，更新使用 `uv tool upgrade ziho-autoresearch`。固定版本或通过 URL 安装后的更新方法，请参阅 [uv 指南](docs/uv-installation.md)。

不使用 uv 时：

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell 中请用以下命令替代上一行：
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
zar --help
```

## 2. 连接现有项目

将下方的 `./my-ml-project` 替换为**已存在的 ML 项目文件夹**。Windows 下路径含空格时，也请用引号括起来。

```sh
zar init --project ./my-ml-project
zar status --project ./my-ml-project --json
```

这会在项目中创建 `.autoresearch/`。现有代码、根目录下的 `program.md` 和 `AGENTS.md` 会被保留。省略 `--project` 时使用当前文件夹，不会自动向上搜索父目录。

初始状态为 `ready:false` 是正常的。你需要填写目标、比较指标、数据与代码标识、执行环境、命令、预算以及允许修改的路径。可以让下一步中的智能体协助配置，或按照[首次使用指南](docs/first-run-and-resume.md)自行填写。

## 3. 在智能体中使用技能

### 直接安装到 Codex / Claude Code

**自 v0.3.0 起支持。** 安装方式与完整流程见[智能体安装指南](docs/agent-installation.md)。安装 CLI 后，选择要使用的智能体。

```sh
# Codex：仅安装到指定的 ML 项目中
zar skill install --agent codex --project ./my-ml-project

# 使用 Claude Code 时
zar skill install --agent claude --project ./my-ml-project
```

命令会创建所需的技能文件夹并复制完整技能包，不会覆盖现有技能。在智能体中打开目标项目，然后在 Codex 中选择 `$ziho-autoresearch`，或在 Claude Code 中选择 `/ziho-autoresearch`，并提出如下请求：

> 请检查这个项目，不执行训练，并提出第一个实验计划。

如果技能未出现在列表中，请重启智能体并检查技能设置。智能体的执行环境中也必须能够运行 `zar --help`。由于技能安装到了可被发现的路径，基本使用不要求手动在 `AGENTS.md` 中添加关联。安装并不等于授权执行训练，也不代表已经验证智能体实际识别了技能。

### 在其他智能体中手动关联

请在 ML 项目之外的合适工作目录中执行。`--dest` 指定的是**待新建的技能文件夹**，其父目录必须已经存在。

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json
```

这会提取 wheel 内的 `SKILL.md` 和整个 `references/` 目录，不会覆盖现有文件夹，也不会自动注册到智能体。将输出的绝对路径提供给正在使用的编程智能体。

> 请阅读 `<输出的技能文件夹>/SKILL.md` 并检查 `<ML 项目的绝对路径>`。先不要执行任何操作，整理当前代码、数据、评估方法与缺失的配置，再提出第一个实验计划。

如果还要让智能体执行实验，请同时指定**目标、允许修改的路径、执行环境、次数与时间上限**。不要将密钥或原始个人信息粘贴到对话或实验证据中。更新技能时，请提取到新文件夹，并与用户修改过的版本进行比较。

### 在项目的 AGENTS.md 中添加关联

如需保留手动关联，或明确每个项目的适用条件，请在**实验目标项目**的 `AGENTS.md` 中添加技能的 `SKILL.md` 路径和适用条件。保留已有规则，不要复制技能全文或频繁变化的实验状态。请在所用工具中确认智能体已配置为读取该指令文件。

下方的关联文本生成命令自 v0.3.0 起支持。

```sh
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0
```

该命令在屏幕上输出包含现有技能位置的关联文本。请检查内容，仅将必要部分合并到目标项目已有的 `AGENTS.md` 中。它不会创建或覆盖文件，也不会自动注册智能体。不要使用 `> AGENTS.md` 重定向，因为 shell 可能清空已有文件。公开版本也可使用[手动关联示例](docs/uv-installation.md#프로젝트-지침에-연결)。

## 4. 查看记录与恢复工作

```sh
zar status --project ./my-ml-project --json
zar context --project ./my-ml-project --max-bytes 16384 --json
zar check --project ./my-ml-project --json
```

- `status`：查看缺失配置、当前选择、未完成实验及预算。
- `context`：获取用于新会话的有限大小上下文。不会检查证据文件是否存在或其哈希值。
- `check`：检查记录与证据。除退出码外，也请阅读警告内容。初始配置尚未完成时，退出码可能为 3。

中断后，可以向智能体提出如下请求：

> 请读取同一个技能和项目，通过 `context` 与 `status` 确认当前状态。对于 `unknown` 实验，在确认实际日志和进程状态之前不要重新运行，请根据新的证据更新其状态。

**记录中采用的方案与实际工作目录中的代码是两回事。** `keep` 决策或更改当前选择不会回滚代码。完整的中断与恢复流程请参阅[首次使用与恢复指南](docs/first-run-and-resume.md)。

## 手动记录的顺序

可以自行编写 JSON 输入，也可以检查智能体起草的内容。[CLI 操作示例](skills/ziho-autoresearch/references/cli-recipes.md)提供了输入示例，[文件契约](docs/cli-and-file-contract.md)列出了必填字段与状态转换。

| 目的 | 命令 | 说明 |
|---|---|---|
| 初始化项目 | `zar init` | 在现有项目中创建记录文件夹 |
| 生成关联文本 | `zar skill guidance --skill-dir` | 根据现有技能路径输出用于 AGENTS.md 的文本 |
| 安装到智能体 | `zar skill install --agent` | 安装到 Codex/Claude Code 可发现的路径 |
| 提取技能 | `zar skill install` | 将技能复制到新文件夹 |
| 保存配置 | `zar project set --file <json>` | 将当前 project.json 复制为独立草稿后修改 |
| 执行前检查 | `zar review add --file <json>` | 记录已确认的证据与未验证项 |
| 记录下一个候选方案 | `zar candidate add --file <json>` | [观测、预测与选择理由](docs/candidate-rationale.md) |
| 创建实验、更新结果 | `zar experiment create`, `zar experiment update` | [输入示例](examples/experiment-create.json)，仅记录实际观测 |
| 比较与决策 | `zar experiment compare`, `zar experiment decide` | 确认 proxy/full 等比较条件；不会自动采用代码 |
| 更正已完成结果 | `zar experiment correct` | 使用新 ID，保留原始记录 |
| 记录失败经验 | `zar memory add --file <json>` | [失败原因、应对措施与局限](docs/failure-memory.md) |
| 记录已确认的外部分数 | `zar submission add --file <json>` | 实际提交需另行执行 |
| 查看证据原文 | `zar evidence read` | [哈希与部分读取](docs/context-and-evidence.md) |
| 查看实验关系 | `zar lineage` | [JSON 与 Mermaid 谱系](docs/experiment-lineage.md) |
| 生成报告 | `zar report --output summary.md` | 保存到 `.autoresearch/reports/summary.md` |
| 关联代码提交 | `zar git status`, `zar experiment create --git-head` | [Git 历史用法](docs/git-research-history.md) |

上述命令也可以附加 `--project <项目路径>`。详细参数请通过 `zar <命令> --help` 查看。JSON 输入请写入与原始记录不同的文件。如使用 `.autoresearch/drafts/`，需先自行创建该目录。

## 无需训练即可体验

示例未包含在 wheel 中。请解压[源码发布包](https://github.com/ziholee/zihoAutoResearch/releases/tag/v0.3.0)或下载本仓库，并在已安装 CLI 的 Python 环境中，以源码文件夹为当前目录执行。

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell 中请用以下命令替代上一行：
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
python examples/mock-cycle.py --output ./demo-cycle
```

`demo-cycle` 必须是尚不存在的新路径。示例使用模拟分数和日志，展示记录 → 比较 → 决策 → 报告的流程，不会执行训练。uv tool 的 Python 环境与其他 Python 环境不共享包，因此也需在上述示例用虚拟环境中安装此包。跨两个会话的恢复练习请参阅[恢复示例](docs/first-run-and-resume.md#학습-없는-두-세션-연습)。

## 分享记录之前

`.autoresearch/` 和报告可能包含你记录的命令、文件路径、日志摘录及证据。提交或上传前，请检查是否包含密钥、个人数据、私有数据集或日志。CLI 的 JSON 检查不提供秘密信息检测或自动匿名化功能。修改原始证据可能使其与已保存的哈希不一致，因此请单独制作公开用副本。

如果存在残留锁，请先确认没有 CLI 正在运行，再进行恢复。不要直接删除 `.autoresearch/.lock` 或项目根目录下的 `.autoresearch.init.lock`。记录较多时，请优先使用 `context`。`report` 和 `lineage` 的完整输出没有大小限制。

## 了解更多

- [智能体安装、调用与问题排查](docs/agent-installation.md)
- [安装、更新与技能更新](docs/uv-installation.md)
- [从首次配置到中断与恢复](docs/first-run-and-resume.md)
- [研究流程与决策规则](docs/research-workflow.md)
- [项目连接与环境配置](docs/project-adapter-and-environment.md)
- [不同记录规模的性能测量与局限](docs/record-scale-performance.md)
- [产品方向与参考研究](docs/product-direction.md)
- [发布文件验证](docs/releasing.md) · [贡献与 CI 标准](docs/automation.md)

软件验证主要基于合成记录，不保证提升实际 ML 质量或降低训练成本。许可证为 [MIT](LICENSE)。

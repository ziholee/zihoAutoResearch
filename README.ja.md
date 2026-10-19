# zihoAutoResearch

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

[![PyPI バージョン](https://img.shields.io/pypi/v/ziho-autoresearch?logo=pypi&logoColor=white)](https://pypi.org/project/ziho-autoresearch/)
[![Python 3.11 以上](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT ライセンス](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![コントラクト CI](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml/badge.svg?branch=dev&event=push)](https://github.com/ziholee/zihoAutoResearch/actions/workflows/ci.yml?query=branch%3Adev)
[![エージェントスキル: Codex / Claude Code](https://img.shields.io/badge/Agent%20Skills-Codex%20%2F%20Claude%20Code-5865F2)](docs/agent-installation.md)

**既存の ML プロジェクトで、実験の根拠・結果・判断をローカルに記録し、次のセッションから作業を再開できる軽量な CLI とエージェントスキルです。**

前処理、モデル、損失関数、最適化手法を変更するときに、「なぜ試したのか、どの条件で比較したのか、何を採用したのか」を一緒に残します。データや学習環境を新しいプラットフォームに移すことなく、既存のプロジェクトで使用できます。

バッジは最新の PyPI バージョン、対応する Python バージョン、ライセンス、`dev` ブランチの CI 状態、対応エージェントを示します。各バッジをクリックすると詳細を確認できます。

[PyPI](https://pypi.org/project/ziho-autoresearch/) · [GitHub リリース](https://github.com/ziholee/zihoAutoResearch/releases) · [変更履歴](CHANGELOG.md) · [問題の報告](https://github.com/ziholee/zihoAutoResearch/issues)

この README は日本語版です。リンク先の詳細ドキュメントは現在、主に韓国語で提供されています。

## どんなツールですか？

- **CLI (`zar`)**: 実験の計画・観測・比較・判断を JSON で保存し、形式・参照・根拠ファイルを検査します。
- **エージェントスキル**: 使用中のコーディングエージェントがプロジェクトを読み、許可された範囲内で研究手順に従えるように案内します。
- **再開とレポート**: 未完了の実験、失敗の記録、候補の根拠、実験の系譜を参照し、Markdown レポートを作成します。

公開版 v0.3.0 の記録コマンドは LLM の呼び出しや学習を実行しません。**開発ブランチには未リリースの `research` コマンドを追加しています。** OpenAI 互換 API またはインストール済み Codex に役割別の指示を渡し、ユーザーの承認後にローカル実験を一度実行して記録します。接続・承認・再開の手順と検証範囲は [API 研究セッションガイド](docs/research-api.md)を参照してください。実際のクラウド API 接続は未検証で、自動コード復元やコンペへの提出は提供しません。`check` の合格も、データリークがないことやモデル品質を保証しません。

**開発ソース限定：** 対話型ターミナルで `zar research setup --project ./my-ml-project` を実行し、質問に答えると、JSON を手作業で編集せずに設定から最初の実験計画まで進めます。保存とモデルへの送信は別々に確認し、計画の承認待ちで停止します。既存の学習コードと評価手順は事前に用意してください。[対話型設定ガイド](docs/research-api.md#질문에-답해-첫-계획-만들기)を参照してください。 実行前の計画が停止した場合や修正が必要な場合は、`zar research revise SESSION_ID --project ./my-ml-project` で追加質問に回答し、関連付けられた新しい計画を作成できます。`research status` は次の操作を案内し、修正後の計画には新たな承認が必要です。

`baseline` モードはモデルによるコード変更なしで現在の元コードを測定します。候補計画には、比較可能で選択済みの有効な keep 実験が必要です。完了後は `zar research next SESSION_ID --project ./my-ml-project` で設定と限定された判断・記憶の文脈を次の計画へ引き継ぎます。新しい指標ファイルのパス、送信への同意、承認が必要です。コードの自動復元や実験の自動反復は行いません。

開発ソースでは `research start --provider codex --codex-command codex --model <モデル>`、または `research setup` の接続方式の質問で Codex を選べます。macOS/Linux 上の信頼できる Codex CLI 0.162.1 以上が必要です。既存の Codex 認証を使用し、モデルサービスへの送信や課金が発生する場合があります。Codex は提案を返し、zar の送信・実行・判断の承認手順は維持されます。模擬エージェントで検証しており、実際の Codex 認証・推論は未検証です。[接続の範囲と制限](docs/research-api.md#설치된-codex로-연결하기)を確認してください。

開発ソースでは `zar research metrics SESSION_ID --project ./my-ml-project --json` で役割別の呼び出し時間・メッセージのバイト数・報告されたトークン使用量を確認できます。欠損値と部分的な観測を明示し、実際の通信量や料金は推定しません。[測定範囲](docs/research-api.md#역할별-호출-측정-조회)を参照してください。

`zar` は **zihoAutoResearch の略称であり、実行コマンド名**です。インストールするパッケージ名は `ziho-autoresearch` で、インストール後は `zar init`、`zar status` のように使用します。

## 1. インストール

Python **3.11 以上**が必要です。実行時に必要な外部ライブラリへの依存はありません。Git 連携機能を使用する場合のみ、Git の実行ファイルが必要です。

[uv](https://docs.astral.sh/uv/getting-started/installation/) がある場合:

```sh
uv tool install ziho-autoresearch
zar --help
```

以下のバージョン固定の例は v0.3.0 を対象としています。現在の公開状況は[リリース一覧](https://github.com/ziholee/zihoAutoResearch/releases)を確認してください。

`zar` が見つからない場合は、`uv tool update-shell` を実行してターミナルを開き直してください。バージョンを固定するには `uv tool install 'ziho-autoresearch==0.3.0'`、更新するには `uv tool upgrade ziho-autoresearch` を使います。固定バージョンや URL からインストールした場合の更新方法は [uv ガイド](docs/uv-installation.md)を参照してください。

uv を使わずにインストールする場合:

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell では上の行の代わりに:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
zar --help
```

## 2. 既存のプロジェクトを接続する

以下の `./my-ml-project` を、**既存の ML プロジェクトのフォルダー**に置き換えてください。Windows でも、パスに空白が含まれる場合は引用符で囲んでください。

```sh
zar init --project ./my-ml-project
zar status --project ./my-ml-project --json
```

プロジェクト内に `.autoresearch/` が作成されます。既存のコード、ルートの `program.md`、`AGENTS.md` は保持されます。`--project` を省略すると現在のフォルダーを使用し、親フォルダーを自動検索しません。

初回に `ready:false` が表示されるのは正常です。目標、比較指標、データとコードの識別子、実行環境、コマンド、予算、変更を許可するパスを設定する必要があります。次の手順でエージェントに設定を手伝ってもらうか、[はじめての利用ガイド](docs/first-run-and-resume.md)に沿って自分で設定してください。

## 3. エージェントでスキルを使う

### Codex / Claude Code に直接インストールする

**v0.3.0 から対応しています。** インストール方法と全体の手順は[エージェント導入ガイド](docs/agent-installation.md)を参照してください。CLI のインストール後、使用するエージェントを 1 つ選びます。

```sh
# Codex: 指定した ML プロジェクトにのみインストール
zar skill install --agent codex --project ./my-ml-project

# Claude Code を使用する場合
zar skill install --agent claude --project ./my-ml-project
```

必要なスキルフォルダーを作成し、バンドル全体をコピーします。既存のスキルは上書きしません。対象プロジェクトをエージェントで開き、Codex では `$ziho-autoresearch`、Claude Code では `/ziho-autoresearch` を選択して、次のように依頼してください。

> このプロジェクトを学習を実行せずに点検し、最初の実験計画を提案してください。

一覧に表示されない場合は、エージェントを再起動してスキル設定を確認してください。エージェントの実行環境でも `zar --help` が実行できる必要があります。スキルの検出先にインストールするため、基本的な利用では `AGENTS.md` への手動の追記は必須ではありません。インストールは学習実行の許可や、エージェントによる実際の認識の検証を行うものではありません。

### 他のエージェントに手動で接続する

ML プロジェクトの外にある作業しやすいフォルダーで実行してください。`--dest` は**新しく作成するスキルフォルダー**で、親フォルダーはあらかじめ存在している必要があります。

```sh
zar skill install --dest ./ziho-autoresearch-skill-0.3.0 --json
```

wheel に含まれる `SKILL.md` と `references/` 全体を展開します。既存のフォルダーを上書きしたり、エージェントに自動登録したりはしません。出力された絶対パスを、使用中のコーディングエージェントに渡してください。

> `<出力されたスキルフォルダー>/SKILL.md` を読み、`<ML プロジェクトの絶対パス>` を点検してください。まずは実行せずに、現在のコード・データ・評価方法と不足している設定を整理し、最初の実験計画を提案してください。

実験の実行まで任せる場合は、**目標、変更を許可するパス、実行環境、回数と時間の上限**も指定してください。秘密鍵や未加工の個人情報を、会話や実験の根拠に貼り付けないでください。スキルを更新する場合は、新しいフォルダーに展開してユーザーによる変更と比較します。

### プロジェクトの AGENTS.md に接続する

手動の接続を維持したり、プロジェクトごとの適用条件を明記したりする場合は、**実験対象プロジェクト**の `AGENTS.md` に、スキルの `SKILL.md` のパスと適用条件を追加してください。既存のルールは維持し、スキルの全文や頻繁に変わる実験状態はコピーしません。エージェントがその指示ファイルを読むように設定されているかどうかは、使用中のツールで確認してください。

以下の接続用テキストを生成するコマンドは v0.3.0 から対応しています。

```sh
zar skill guidance --skill-dir ./ziho-autoresearch-skill-0.3.0
```

このコマンドは、既存のスキルの場所を含む接続用テキストを画面に出力します。内容を確認し、対象プロジェクトの既存の `AGENTS.md` に必要な部分だけをマージしてください。ファイルの作成・上書き・エージェントへの自動登録は行いません。`> AGENTS.md` にリダイレクトすると、シェルが既存ファイルの内容を消去する可能性があるため、使用しないでください。公開版でも[手動接続の例](docs/uv-installation.md#프로젝트-지침에-연결)を利用できます。

## 4. 記録を確認して再開する

```sh
zar status --project ./my-ml-project --json
zar context --project ./my-ml-project --max-bytes 16384 --json
zar check --project ./my-ml-project --json
```

- `status`: 不足している設定、現在の選択、未完了の実験、予算を確認します。
- `context`: 新しいセッションに渡す、サイズを制限したコンテキストを取得します。根拠ファイルの存在やハッシュは検査しません。
- `check`: 記録と根拠を検査します。終了コードだけでなく、警告の内容も読んでください。初期設定が未完了の場合、終了コード 3 が返ることがあります。

中断後は、エージェントに次のように依頼できます。

> 同じスキルとプロジェクトを読み、`context` と `status` で現在の状態を確認してください。`unknown` の実験は、実際のログとプロセスの状態を確認する前に再実行せず、新たな根拠に基づいて状態を整理してください。

**記録上の採用と、実際の作業フォルダー内のコードは別です。** `keep` の判断や選択の変更は、コードを元に戻しません。詳しい中断・再開の手順は[初回利用・再開ガイド](docs/first-run-and-resume.md)を参照してください。

## 直接記録する場合の手順

JSON 入力を自分で作成することも、エージェントが作成した下書きを確認することもできます。[CLI レシピ](skills/ziho-autoresearch/references/cli-recipes.md)に入力例があり、[ファイル仕様](docs/cli-and-file-contract.md)に必須フィールドと状態遷移がまとめられています。

| 目的 | コマンド | 説明 |
|---|---|---|
| プロジェクトの初期化 | `zar init` | 既存のプロジェクトに記録用フォルダーを作成 |
| 接続用テキストの生成 | `zar skill guidance --skill-dir` | 既存のスキルのパスを使い、AGENTS.md 用のテキストを出力 |
| エージェントへのインストール | `zar skill install --agent` | Codex/Claude Code の検出先にインストール |
| スキルの展開 | `zar skill install` | 新しいフォルダーにスキルをコピー |
| 設定の保存 | `zar project set --file <json>` | 現在の project.json を別の下書きファイルにコピーして編集 |
| 実行前の点検 | `zar review add --file <json>` | 確認した根拠と未検証の項目を記録 |
| 次の候補の記録 | `zar candidate add --file <json>` | [観測・予測・選択理由](docs/candidate-rationale.md) |
| 実験の作成・結果の更新 | `zar experiment create`, `zar experiment update` | [入力例](examples/experiment-create.json)。実際に観測した内容のみを記録 |
| 比較・判断 | `zar experiment compare`, `zar experiment decide` | proxy/full などの比較条件を確認。コードの自動採用はなし |
| 完了した結果の訂正 | `zar experiment correct` | 新しい ID を使い、元の記録を保持 |
| 失敗の記録 | `zar memory add --file <json>` | [失敗の原因・対応と限界](docs/failure-memory.md) |
| 確認済みの外部スコア | `zar submission add --file <json>` | 実際の提出は別途実施 |
| 根拠の原文の参照 | `zar evidence read` | [ハッシュ・部分取得](docs/context-and-evidence.md) |
| 実験間の関係の参照 | `zar lineage` | [JSON・Mermaid による系譜](docs/experiment-lineage.md) |
| レポートの生成 | `zar report --output summary.md` | `.autoresearch/reports/summary.md` に保存 |
| コードのコミットとの連携 | `zar git status`, `zar experiment create --git-head` | [Git 履歴の使い方](docs/git-research-history.md) |

上記のコマンドにも `--project <プロジェクトのパス>` を追加できます。詳しい引数は `zar <コマンド> --help` で確認してください。JSON 入力は元のファイルとは別のファイルに作成します。`.autoresearch/drafts/` を使う場合は、先に自分で作成する必要があります。

## 学習せずに試す

サンプルは wheel に含まれていません。[ソース配布物](https://github.com/ziholee/zihoAutoResearch/releases/tag/v0.3.0)を展開するか、このリポジトリをダウンロードし、CLI をインストールした Python 環境で、ソースフォルダーから実行してください。

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell では上の行の代わりに:
# .venv\Scripts\Activate.ps1
python -m pip install ziho-autoresearch
python examples/mock-cycle.py --output ./demo-cycle
```

`demo-cycle` は、まだ存在しない新しいパスである必要があります。サンプルは仮のスコアとログを使って、記録 → 比較 → 判断 → レポートの流れを示し、学習は行いません。uv tool の Python 環境と別の Python 環境ではパッケージを共有しないため、上記のサンプル用仮想環境にもパッケージをインストールします。2 つのセッションで再開を試すには、[再開のサンプル](docs/first-run-and-resume.md#학습-없는-두-세션-연습)を参照してください。

## 実際の学習・評価ループを試す（開発ソース）

[合成回帰のサンプル](docs/ml-loop-example.md)は、模擬 LLM と実際のローカル学習で、基準実験 → 候補の比較 → 安全な中断・再開を確認します。現在の開発ソースを取得し、上記の仮想環境で `python -m pip install .` を実行してから、`python examples/ml-loop.py --output ./demo-ml` を実行してください。出力先は存在しない新しいパスを指定します。公開済み v0.3.0 には必要な `research` コマンドがありません。クラウド API や有料モデルは呼び出しません。

Linux/macOS では[CLI 障害復旧の例](docs/crash-recovery-validation.md)で、実行中の CLI 終了後の unknown 保持、重複実行の拒否、証拠に基づく復旧を確認できます。モックプロバイダーのみを使用し、Windows のプロセス復旧は検証範囲外です。

## 記録を共有する前に

`.autoresearch/` とレポートには、記録したコマンド、ファイルパス、ログの抜粋、根拠が含まれる場合があります。コミットやアップロードの前に、秘密鍵、個人データ、非公開のデータセットやログが含まれていないか確認してください。CLI の JSON 検査は、秘密情報の検出や自動匿名化を行いません。元の根拠を変更すると保存済みのハッシュと一致しなくなる場合があるため、公開用のコピーを別途作成してください。

ロックが残っている場合は、実行中の CLI がないことを確認してから復旧してください。`.autoresearch/.lock` やプロジェクトルートの `.autoresearch.init.lock` を無条件に削除しないでください。記録の履歴が大きい場合は、まず `context` を使ってください。`report` と `lineage` の全体出力にはサイズ制限がありません。

## 詳細情報

- [エージェントの導入・呼び出し・トラブルシューティング](docs/agent-installation.md)
- [インストール・更新・スキルの更新](docs/uv-installation.md)
- [初期設定から中断・再開まで](docs/first-run-and-resume.md)
- [研究手順と判断ルール](docs/research-workflow.md)
- [プロジェクトの接続・環境設定](docs/project-adapter-and-environment.md)
- [記録規模別の性能測定と限界](docs/record-scale-performance.md)
- [製品の方向性と参考研究](docs/product-direction.md)
- [配布ファイルの検証](docs/releasing.md) · [貢献・CI の基準](docs/automation.md)

ソフトウェアの検証は合成記録を中心に行っており、実際の ML 品質や学習コストの削減を保証するものではありません。ライセンスは [MIT](LICENSE) です。

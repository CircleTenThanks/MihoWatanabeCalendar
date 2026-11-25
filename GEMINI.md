# MihoWatanabeCalendar 開発・運用ルール

このリポジトリは、渡邉美穂さん公式サイト（`https://mihowatanabe.jp`）のニュース一覧・詳細APIからスケジュール情報を抽出し、公開Googleカレンダーへ自動登録するPythonパッケージです。

---

## 1. 設計思想とアーキテクチャ上の重要ルール

### 1. Next.js SSR (`__NEXT_DATA__`) からのデータ取得とフォールバック
- **ニュース一覧**: `https://mihowatanabe.jp/news/all/pages/{page}` は Next.js (Tailwind CSS) で構成されており、HTML内の `<script id="__NEXT_DATA__">` の `props.pageProps.newsListData` に記事一覧JSONが埋め込まれている。一覧取得では `newsListData` の `id` 抽出を第一優先とし、構造変更時に備えて `a[href^="/news/detail/"]` タグからのURL抽出へフォールバックする二段構えを維持する（旧来の Chakra UI `css-*` クラスや `/api/news/{id}/fc-server` エンドポイントは廃止済み）。
- **ニュース詳細**: 詳細ページ（`/news/detail/{id}`）も同様に `<script id="__NEXT_DATA__">` 内の `props.pageProps.newsDataForFree` に `title`, `publishTime`, `bodyRichText` が格納されているため、これを抽出・キャッシュして使用する。
- **サーバー負荷軽減**: 記事ごとのリクエスト間に必ず `_SCRAPE_WAIT_SECONDS = 1` のスリープを入れ、リクエストにはタイムアウト（`_REQUEST_TIMEOUT_SECONDS = 10`, `_LIST_TIMEOUT_SECONDS = 30`）を設定する。

### 2. 自然言語テキストからの日時解析パイプライン
公式サイトのニュース本文（`bodyRichText`）には定型のスケジュール欄がなく、自由記述のテキストで放送日時やイベント日時が書かれるため、以下のルールで解析する：
- **テキスト正規化**: `jaconv.z2h(text, kana=False)` で全角英数記号を半角化し、`年`/`月`/`日`/`時`/`分`/`〜` を統一形式へ正規化する。
- **12時間表記の補正**: 「午後」「よる」「夜」が含まれる行（`_has_hour12_flag()`）は12時間を加算する。また、`25:00` などの24時超え表記（`over_24h_datetime()`）は翌日へ繰り上げる。
- **年跨ぎの推定**: 本文に「月日」しか書かれていない場合、**単純に `datetime.now().year` を使うのではなく**、現在月と対象月の関係から前年・当年・翌年を推定する `_target_year_for_month()` を使用する（例: 11〜12月に翌年1〜6月の予定が出た場合は翌年と判定）。本文に西暦年が明記されている場合は必ずその年を優先する。
- **複数日時対応**: 1つのニュース記事内に複数の放送日・イベント日時が記載されているケースに対応するため、段落ごとに `_SCHEDULE_PARSERS` でマッチしたすべての日時（重複除外済み）を登録対象とする。時刻が抽出できない記事は終日イベントとして扱う。

### 3. 徹底した二重登録（重複）防止と冪等性
過去にタイトル微修正や再実行による重複登録が課題となった経緯から、**3段階の重複防止機構**を設けている。改修時もこの仕組みを絶対に壊さないこと：
1. **タイトル基準 & 記事URL基準の照合（`check_duplicate_event` / `search_events`）**:
   - カレンダー上の既存イベントから `日付-タイトル(-時刻)` だけでなく、説明欄（`description`）に保存した記事URLを用いた `日付-記事URL(-時刻)` の両方を作成して照合する。これにより、公式サイト側で後から記事タイトルが微修正されても同一記事・同一日時の予定であれば重複登録を防ぐ。
2. **決定論的 `eventId` による冪等な Insert（`generate_event_id`）**:
   - `mw-{日付}-{タイトル}(-{時刻})(-{URLパス})` の SHA-1 ハッシュ（先頭32文字、0-9a-f）を Google Calendar API の `id` として指定する。
3. **HTTP 409 Conflict のハンドリング（`add_info_to_calendar`）**:
   - 万が一 `search_events` の検索範囲外などで同一 `eventId` が既に存在していた場合、Google Calendar API が返す `HttpError`（ステータス `409`）をキャッチして正常スキップとして扱う。

### 4. 安全なローカル検証・過去分バックフィルオプションと多重起動防止
- **`--no-calendar`**: Googleカレンダーへの書き込み（`insert`）をスキップし、スクレイピングと日時解析結果のログ出力のみを行うドライラン用フラグ。
- **`--test-run`**: テスト用カレンダー等で検証する際、固定ハッシュではなくランダムなUUIDを `eventId` に使うフラグ。
- **`--start-page` / `--end-page` / `--since-date`**: 取得する一覧ページ範囲（デフォルト `1`〜`1`）や登録対象の最小日付（`YYYY-MM-DD`）を指定して過去分をバックフィル登録できるオプション。また、過去記事を再解析する際にも年推定が狂わないよう、`_target_year_for_month()` は記事の公開日（`publishTime`）を基準日（`base_date`）として西暦年を推定する。
- **`tendo.singleton.SingleInstance()`**: バッチの多重起動を防ぐ。
- **親リポジトリ（RenderWrapper）連携**: 本番の Render.com CRON JOB では親リポジトリ `RenderWrapper` から `miho_watanabe_calendar.main:main` が引数なしで呼び出される。`main(argv: list[str] | None = None)` のシグネチャと `src` レイアウトを維持すること。

---

## 2. コーディング規約・品質基準

### Ruff 厳格設定（`ALL` + `preview = true`）の遵守
- **コード側での解消**: `pyproject.toml` では `select = ["ALL"]` かつ `preview = true` を有効にしている。Lint 指摘が出た際は **`pyproject.toml` の `ignore` 追加や `# noqa` コメントで回避せず、コードをリファクタリングして解消する**こと。
  - マジックナンバーはモジュール先頭でプライベート定数（`_LOOKBACK_DAYS = 1` 等）として定義する。
  - 関数の引数や分岐が増えた場合は、`dataclass(frozen=True)`（`CalendarEventDraft`, `CalendarSyncContext`）や `Protocol`（`_ScheduleParser`）のディスパッチテーブルを用いて複雑度を下げる。
  - すべての関数に型アノテーションと Google スタイルの Docstring（1行目末尾は `.`）を記述する。
- **ログ出力**:
  - `print()` は禁止。`LOGGER = logging.getLogger(__name__)` を使用する。
- **著作権ヘッダ**:
  - `src/miho_watanabe_calendar/main.py` の先頭には原著者 `ddn` 氏と `CircleTenThanks` の併記ヘッダを維持する。

---

## 3. 開発コマンドとコミット規約

### 検証コマンド（変更後は必ず実行）
CI（`.github/workflows/ruff.yml`）の Required status checks を通過させるため、変更後は必ず以下を実行する：

```zsh
uv run --frozen ruff check
uv run --frozen ruff format --check
```

動作検証（ドライラン）を行う場合：
```zsh
source scripts/load_env.sh
uv run miho-watanabe-calendar --no-calendar
```

### コミットメッセージ規約
- コードや設定ファイルを変更した際は、完了報告時に**コミットメッセージ案を1つだけ提示する**こと。
- 以下のプレフィックスを付けた簡潔な日本語で記述する：
  - `Add: ...`（新規機能・ファイル追加）
  - `Update: ...`（仕様変更・改善・リファクタリング）
  - `Fix: ...`（バグ修正）
  - `Remove: ...`（不要ファイル・機能の削除）
  - `Upgrade: ...`（依存パッケージのバージョン更新）

### 実行環境・認証情報
- 環境変数: `CALENDAR_ID_MW`（`config.env` および `scripts/load_env.sh` で読み込み可能）
- サービスアカウント認証ファイル: カレントディレクトリの `credentials_mw.json`（Git管理外・秘匿情報のため絶対にコミットしない）

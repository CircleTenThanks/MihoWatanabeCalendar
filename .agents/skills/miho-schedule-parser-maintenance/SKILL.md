---
name: miho-schedule-parser-maintenance
description: >-
  渡邉美穂さん公式サイト（mihowatanabe.jp）のニュース記事・JSON APIからの日時抽出パーサーの追加・修正、
  およびGoogleカレンダーの重複判定ロジックを保守するためのスキル。新しい日時表記パターンへの対応やスクレイピング不具合調査時に使用する。
---

# 渡邉美穂カレンダー 日時パーサー・重複防止保守スキル

`MihoWatanabeCalendar` で新しいニュース記事の日時表記パターンへの対応や、一覧・API取得の不具合を修正する際の手順です。

## 1. データ取得と日時解析の仕組み（`src/miho_watanabe_calendar/main.py`）

1. **記事一覧の取得（`get_schedule_list`）**
   - `https://mihowatanabe.jp/news/all/pages/{page}` から記事リンクを取得する。
   - `div.css-izgksv` が見つからない場合は `_fallback_article_divs()` で `css-` クラスを持つ `div` の親 `a[href]` を辿る。

2. **記事詳細JSONの取得と基準日の決定（`fetch_news_detail_json` / `get_schedule_info`）**
   - `/news/detail/{id}` から末尾の `{id}` を取り出し、`https://mihowatanabe.jp/api/news/{id}/fc-server` を取得する。
   - `bodyRichText` の段落（`nodeType == "paragraph"`）からプレーンテキスト行リスト（`extract_text_lines_from_body_rich`）を取り出す。
   - 基準日の決定優先順位：
     1. `_parse_full_date`: 本文中の年月日（`YYYY年M月D日`, `YYYY/M/D`, `YYYY.M.D`）
     2. `_parse_month_day_with_year`: 本文中の月日（`M月D日`）
     3. `_parse_publish_time`: APIの `publishTime`（`YYYY.M.D`）

3. **開始・終了時刻の抽出パイプライン（`get_schedule_time` / `_SCHEDULE_PARSERS`）**
   - 各段落を `_normalize_schedule_line()` で半角・記号正規化し、`_has_hour12_flag()` で「午後」「よる」「夜」の有無を判定した上で、`_SCHEDULE_PARSERS` の各パーサー関数を順番に試行する：
     1. `_parse_md_hour_minute`: 年なし `M/D ... HH:MM`（24時超え対応、終了時刻は開始+1時間）
     2. `_parse_ymd_range`: `YYYY/M/D ... HH:MM~HH:MM`
     3. `_parse_ymd_start`: `YYYY/M/D ... HH:MM`
     4. `_parse_md_range`: `M/D ... HH:MM~HH:MM`（年は `_target_year_for_month` で推定）
     5. `_parse_md_start`: `M/D ... HH:MM`（年は `_target_year_for_month` で推定）
     6. `_parse_md_hour_only`: `M/D ... HH:`（分省略パターン）

## 2. 新しい日時表記パターンを追加する手順

1. **正規化後の文字列を確認する**
   - 対象記事の本文が `_normalize_schedule_line()` を通った後にどのような文字列になるか確認する（`年`/`月` → `/`, `日`/`分` → 空文字, `時` → `:`, `〜`/`-` → `~`）。
2. **パーサー関数の実装**
   - `_ScheduleParser` プロトコル（`(line_text: str, *, hour12: bool) -> tuple[dt.datetime, dt.datetime] | None`）に準拠した関数を作成する。
   - 年が明記されていないパターンでは必ず `_target_year_for_month(month)` を使い、24時超えの時刻があり得る場合は `over_24h_datetime()` を使用する。
3. **`_SCHEDULE_PARSERS` への登録順序に注意する**
   - `_SCHEDULE_PARSERS` は上から順に試行され、最初に `None` 以外を返したパーサーが採用される。
   - **より具体的（年月日あり・終了時刻あり）なパーサーを、より汎用的（月日のみ・開始時刻のみ）なパーサーより前に配置する**こと。

## 3. 検証手順

1. **Ruff チェックの実行**
   ```zsh
   uv run --frozen ruff check
   uv run --frozen ruff format --check
   ```
2. **ドライランでの動作確認（認証情報がある場合）**
   - `--no-calendar` を付けることで、Googleカレンダーへ一切書き込まずに抽出・重複判定ログ（`add:` / `pass:`）だけを確認できる：
   ```zsh
   source scripts/load_env.sh
   uv run miho-watanabe-calendar --no-calendar
   ```

# Copyright (c) 2026 CircleTenThanks
"""渡邉美穂さんのスケジュールをGoogleカレンダーへ登録する."""

import argparse
import datetime
import hashlib
import logging
import os
import re
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from operator import itemgetter
from typing import Protocol

import jaconv
import requests
from bs4 import BeautifulSoup, Tag
from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from tendo import singleton

LOGGER = logging.getLogger(__name__)
_CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar",)
_CREDENTIALS_PATH = "credentials_mw.json"
_JST = datetime.timezone(datetime.timedelta(hours=9))
_REQUEST_TIMEOUT_SECONDS = 10
_LIST_TIMEOUT_SECONDS = 30
_SCRAPE_WAIT_SECONDS = 1
_HALF_DAY_HOURS = 12
_HOURS_PER_DAY = 24
_MAX_DAY = 31
_MONTHS_PER_YEAR = 12
_FIRST_HALF_MAX_MONTH = 6
_YEAR_CROSS_MONTH = 7
_NIGHT_HOUR_MIN = 6
_HTTP_CONFLICT = 409
_MAX_EVENT_RESULTS = 2500
_EVENT_ID_LENGTH = 32
_LOOKBACK_DAYS = 1
_LOOKAHEAD_DAYS = 30
_DEFAULT_DURATION = datetime.timedelta(hours=1)
_SITE_ORIGIN = "https://mihowatanabe.jp"


class _ScheduleParser(Protocol):
    """1行のスケジュール文字列を日時へ変換する関数."""

    def __call__(
        self,
        line_text: str,
        *,
        hour12: bool,
    ) -> tuple[datetime.datetime, datetime.datetime] | None:
        """1行を解析する.

        Args:
            line_text: 正規化済みの行.
            hour12: 12時間表記として扱うなら True.

        Returns:
            開始と終了日時. 不一致なら None.
        """
        ...


@dataclass(frozen=True)
class CalendarEventDraft:
    """Googleカレンダーへ登録するイベント."""

    summary: str
    event_day: str
    start_time: datetime.datetime | None
    end_time: datetime.datetime | None
    event_link: str


def build_calendar_api() -> Resource:
    """Google Calendar APIクライアントを生成する.

    Returns:
        Google Calendar APIのサービスインスタンス。
    """
    creds = service_account.Credentials.from_service_account_file(
        _CREDENTIALS_PATH,
        scopes=_CALENDAR_SCOPES,
    )
    return build("calendar", "v3", credentials=creds)


def remove_blank(text: str) -> str:
    """改行とタブを除いて前後空白を落とす.

    Args:
        text: 処理対象のテキスト。

    Returns:
        整形後のテキスト。
    """
    return text.replace("\n", "").replace("\t", "").strip()


def get_schedule_list(
    start_page: int,
    end_page: int,
) -> list[tuple[str, str, str, str]]:
    """ニュース一覧からスケジュール候補を取得する.

    Args:
        start_page: 取得開始ページ。
        end_page: 取得終了ページ。

    Returns:
        `(日付, タイトル, リンクパス, 記事URL)` のリスト。
    """
    schedule_list: list[tuple[str, str, str, str]] = []
    for page in range(start_page, end_page + 1):
        url = f"{_SITE_ORIGIN}/news/all/pages/{page}"
        result = requests.get(url, timeout=_LIST_TIMEOUT_SECONDS)
        soup = BeautifulSoup(result.content, features="lxml")
        articles = list(soup.find_all("div", {"class": "css-izgksv"}))
        if not articles:
            articles.extend(_fallback_article_divs(soup))

        for article in articles:
            link_tag = article.find_parent("a", href=True)
            if not link_tag:
                continue
            article_url = f"{_SITE_ORIGIN}{link_tag['href']}"
            event_time, event_name, event_link = get_schedule_info(article_url)
            if event_time and event_name:
                schedule_list.append((event_time, event_name, event_link, article_url))
            time.sleep(_SCRAPE_WAIT_SECONDS)

    return schedule_list


def _fallback_article_divs(soup: BeautifulSoup) -> list[Tag]:
    """クラス名が動的な場合の記事divフォールバック.

    Returns:
        記事とみなしたdiv要素.
    """
    articles: list[Tag] = []
    for div in soup.find_all("div"):
        classes = div.get("class")
        if not classes or not any("css-" in cls for cls in classes):
            continue
        if div.find_parent("a", href=True):
            articles.append(div)
    return articles


def fetch_news_detail_json(article_url: str) -> dict[str, object]:
    """ニュース詳細ページが内部で叩いているJSON APIからデータを取得する.

    例: https://mihowatanabe.jp/news/detail/{id}
         -> https://mihowatanabe.jp/api/news/{id}/fc-server

    Args:
        article_url: ニュース詳細ページのURL。

    Returns:
        APIが返すJSONオブジェクト。
    """
    parsed = urllib.parse.urlparse(article_url)
    news_id = parsed.path.rstrip("/").split("/")[-1]
    api_url = f"{_SITE_ORIGIN}/api/news/{news_id}/fc-server"
    resp = requests.get(api_url, timeout=_REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict):
        return payload
    return {}


def _collect_text(node: object, text_parts: list[str]) -> None:
    """リッチテキストノードから文字列を集める."""
    if not isinstance(node, dict):
        return
    if node.get("nodeType") == "text":
        val = node.get("value") or ""
        if val:
            text_parts.append(str(val))
    children = node.get("content") or []
    if isinstance(children, list):
        for child in children:
            _collect_text(child, text_parts)


def extract_text_lines_from_body_rich(body_rich: dict[str, object]) -> list[str]:
    """BodyRichText フィールドから、各段落ごとのプレーンテキスト行を抽出する.

    Args:
        body_rich: 本文リッチテキスト。

    Returns:
        段落ごとのテキスト行。
    """
    contents = body_rich.get("content") or []
    if not isinstance(contents, list):
        return []

    lines: list[str] = []
    for node in contents:
        if not isinstance(node, dict) or node.get("nodeType") != "paragraph":
            continue
        text_parts: list[str] = []
        for child in node.get("content") or []:
            _collect_text(child, text_parts)
        line = "".join(text_parts).strip()
        if line:
            lines.append(line)
    return lines


def _parse_full_date(line: str) -> str | None:
    """年月日を含む日付文字列を ISO 日付へ変換する.

    Returns:
        ISO日付. 見つからなければ None.
    """
    match = (
        re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", line)
        or re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", line)
        or re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", line)
    )
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def get_schedule_info(
    article_url: str,
) -> tuple[str | None, str | None, str | None]:
    """ニュース詳細APIからイベント日付とタイトル等を取得する.

    Args:
        article_url: ニュース詳細ページのURL。

    Returns:
        日付、タイトル、リンクパス。取得できない項目は None。
    """
    try:
        data = fetch_news_detail_json(article_url)
    except (requests.RequestException, ValueError) as exc:
        LOGGER.info("failed to fetch detail json for %s: %s", article_url, exc)
        return None, None, None

    event_name = data.get("title")
    event_name_text = event_name if isinstance(event_name, str) else None
    event_time: str | None = None
    body_rich_raw = data.get("bodyRichText") or {}
    body_rich = body_rich_raw if isinstance(body_rich_raw, dict) else {}
    lines = extract_text_lines_from_body_rich(body_rich)

    for line in lines:
        event_time = _parse_full_date(line)
        if event_time:
            break

    target_year = datetime.datetime.now(tz=_JST).year
    if event_time is None:
        event_time = _parse_month_day_with_year(lines, target_year)

    if event_time is None:
        event_time = _parse_publish_time(data.get("publishTime"))

    parsed = urllib.parse.urlparse(article_url)
    event_link = parsed.path or "/news/detail/unknown"
    if not event_name_text or not event_time:
        return None, None, None
    return event_time, event_name_text, event_link


def _parse_month_day_with_year(lines: list[str], target_year: int) -> str | None:
    """年なしの月日表記から日付を組み立てる.

    Returns:
        ISO日付. 見つからなければ None.
    """
    for line in lines:
        match = re.search(r"(\d{1,2})月(\d{1,2})日", line)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            return f"{target_year}-{month:02d}-{day:02d}"
    return None


def _parse_publish_time(publish_time: object) -> str | None:
    """PublishTime をフォールバック日付として使う.

    Returns:
        ISO日付. 使えなければ None.
    """
    if not isinstance(publish_time, str) or not re.match(
        r"\d{4}\.\d{1,2}\.\d{1,2}",
        publish_time,
    ):
        return None
    year, month, day = publish_time.split(".")
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _now_jst() -> datetime.datetime:
    """現在の日本時間を返す.

    Returns:
        タイムゾーン付きの現在日時.
    """
    return datetime.datetime.now(tz=_JST)


def _target_year_for_month(month: int) -> int:
    """月だけから掲載年を推定する.

    Returns:
        推定した西暦年.
    """
    now = _now_jst()
    current_year = now.year
    current_month = now.month
    if current_month >= _YEAR_CROSS_MONTH and month <= _FIRST_HALF_MAX_MONTH:
        return current_year + 1
    if current_month <= _FIRST_HALF_MAX_MONTH and month >= _YEAR_CROSS_MONTH:
        return current_year - 1
    return current_year


def _has_hour12_flag(line_text: str) -> bool:
    """12時間表記として扱うべき行なら True.

    Returns:
        12時間表記なら True.
    """
    afternoon = re.search(r"午後(\d+)", line_text)
    if afternoon is not None and int(afternoon[1]) <= _HALF_DAY_HOURS:
        return True
    night = re.search(r"(よる|夜)(\d+)", line_text)
    return bool(
        night is not None and _NIGHT_HOUR_MIN <= int(night[2]) <= _HALF_DAY_HOURS
    )


def _normalize_schedule_line(original_text: str) -> str:
    """時刻解析しやすいように行を正規化する.

    Returns:
        正規化後の行.
    """
    line_text = jaconv.z2h(original_text, kana=False)
    line_text = line_text.replace("-", "~")
    line_text = line_text.replace("\u301c", "~")
    line_text = line_text.replace("年", "/")
    line_text = line_text.replace("月", "/")
    line_text = line_text.replace("日", "")
    line_text = line_text.replace("時", ":")
    return line_text.replace("分", "")


def _apply_hour12(hour: int, *, hour12: bool) -> int:
    """12時間表記なら12時間加算する.

    Returns:
        24時間表記の時.
    """
    return hour + _HALF_DAY_HOURS if hour12 else hour


def over_24h_datetime(
    year: int,
    month: int,
    day: int,
    times: str,
) -> datetime.datetime:
    """24時間以上の時刻をdatetimeに変換する.

    Args:
        year: 年。
        month: 月。
        day: 日。
        times: `HH:MM` 形式の時刻。

    Returns:
        タイムゾーン付きの日時。
    """
    hour, minute = times.split(":")
    minutes = int(hour) * 60 + int(minute)
    dt = datetime.datetime(
        year=int(year),
        month=int(month),
        day=int(day),
        tzinfo=_JST,
    )
    return dt + datetime.timedelta(minutes=minutes)


def _parse_md_hour_minute(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """`8/28 25:00` 形式を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    del hour12
    match = re.search(
        r"^(?!\d{4}/)(\d{1,2})/(\d{1,2}).*?(\d{1,2}):(\d{2})",
        line_text,
    )
    if match is None:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    hour = int(match.group(3))
    minute = int(match.group(4))
    target_year = _target_year_for_month(month)
    if hour >= _HOURS_PER_DAY:
        hour -= _HOURS_PER_DAY
        day += 1
        if day > _MAX_DAY:
            day = 1
            month += 1
            if month > _MONTHS_PER_YEAR:
                month = 1
                target_year += 1
    event_start = datetime.datetime(target_year, month, day, hour, minute, tzinfo=_JST)
    return event_start, event_start + _DEFAULT_DURATION


def _parse_ymd_range(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """年月日と開始・終了時刻が揃った行を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    match = re.search(
        r"(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)",
        line_text,
    )
    if match is None:
        return None
    year = int(match[1])
    month = int(match[2])
    day = int(match[3])
    hour_start = _apply_hour12(int(match[4]), hour12=hour12)
    minute_start = int(match[5])
    hour_end = _apply_hour12(int(match[6]), hour12=hour12)
    minute_end = int(match[7])
    return (
        over_24h_datetime(year, month, day, f"{hour_start:02d}:{minute_start:02d}"),
        over_24h_datetime(year, month, day, f"{hour_end:02d}:{minute_end:02d}"),
    )


def _parse_ymd_start(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """年月日と開始時刻だけの行を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    match = re.search(r"(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)", line_text)
    if match is None:
        return None
    year = int(match[1])
    month = int(match[2])
    day = int(match[3])
    hour_start = _apply_hour12(int(match[4]), hour12=hour12)
    minute_start = int(match[5])
    event_start = over_24h_datetime(
        year,
        month,
        day,
        f"{hour_start:02d}:{minute_start:02d}",
    )
    return event_start, event_start


def _parse_md_range(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """月日と開始・終了時刻の行を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    match = re.search(r"(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)", line_text)
    if match is None:
        return None
    month = int(match[1])
    target_year = _target_year_for_month(month)
    day = int(match[2])
    hour_start = _apply_hour12(int(match[3]), hour12=hour12)
    minute_start = int(match[4])
    hour_end = _apply_hour12(int(match[5]), hour12=hour12)
    minute_end = int(match[6])
    return (
        over_24h_datetime(
            target_year,
            month,
            day,
            f"{hour_start:02d}:{minute_start:02d}",
        ),
        over_24h_datetime(target_year, month, day, f"{hour_end:02d}:{minute_end:02d}"),
    )


def _parse_md_start(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """月日と開始時刻の行を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    match = re.search(r"(\d+)/(\d+).+?(\d+):(\d+)", line_text)
    if match is None:
        return None
    month = int(match[1])
    target_year = _target_year_for_month(month)
    day = int(match[2])
    hour_start = _apply_hour12(int(match[3]), hour12=hour12)
    minute_start = int(match[4])
    event_start = over_24h_datetime(
        target_year,
        month,
        day,
        f"{hour_start:02d}:{minute_start:02d}",
    )
    return event_start, event_start


def _parse_md_hour_only(
    line_text: str,
    *,
    hour12: bool,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """月日と開始時だけの行を解析する.

    Args:
        line_text: 正規化済みの行.
        hour12: 12時間表記として扱うなら True.

    Returns:
        開始と終了日時. 不一致なら None.
    """
    match = re.search(r"(\d+)/(\d+).+?(\d+):", line_text)
    if match is None:
        return None
    month = int(match[1])
    target_year = _target_year_for_month(month)
    day = int(match[2])
    hour_start = _apply_hour12(int(match[3]), hour12=hour12)
    event_start = over_24h_datetime(target_year, month, day, f"{hour_start:02d}:00")
    return event_start, event_start


_SCHEDULE_PARSERS: tuple[_ScheduleParser, ...] = (
    _parse_md_hour_minute,
    _parse_ymd_range,
    _parse_ymd_start,
    _parse_md_range,
    _parse_md_start,
    _parse_md_hour_only,
)


def _remember_event_time(
    event_times: dict[str, tuple[datetime.datetime, datetime.datetime]],
    event_start: datetime.datetime,
    event_end: datetime.datetime,
) -> None:
    """重複しない日時を記録する."""
    time_key = (
        f"{event_start.strftime('%Y-%m-%d %H:%M')}-"
        f"{event_end.strftime('%Y-%m-%d %H:%M')}"
    )
    event_times.setdefault(time_key, (event_start, event_end))


def get_schedule_time(
    url: str,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """記事詳細APIから開始・終了時刻を解析する.

    Args:
        url: 記事詳細ページのURL。

    Returns:
        開始・終了日時のリスト。
    """
    try:
        data = fetch_news_detail_json(url)
    except (requests.RequestException, ValueError) as exc:
        LOGGER.info("failed to fetch detail json for time parsing: %s %s", url, exc)
        return []

    body_rich_raw = data.get("bodyRichText") or {}
    body_rich = body_rich_raw if isinstance(body_rich_raw, dict) else {}
    event_times: dict[str, tuple[datetime.datetime, datetime.datetime]] = {}
    processed_lines: set[str] = set()

    for line in extract_text_lines_from_body_rich(body_rich):
        original_text = line if isinstance(line, str) else str(line)
        if original_text in processed_lines:
            continue
        line_text = _normalize_schedule_line(original_text)
        hour12 = _has_hour12_flag(line_text)
        parsed = None
        for parse in _SCHEDULE_PARSERS:
            parsed = parse(line_text, hour12=hour12)
            if parsed is not None:
                break
        if parsed is None:
            continue
        _remember_event_time(event_times, parsed[0], parsed[1])
        processed_lines.add(original_text)

    return list(event_times.values())


def check_duplicate_event(
    event_name: str,
    event_date: str,
    event_time_str: str,
    previous_add_event_lists: list[str],
    *,
    article_url: str | None = None,
) -> bool:
    """既存イベントとの重複を判定する.

    Args:
        event_name: イベント名。
        event_date: 日付文字列 (YYYY-MM-DD形式)。
        event_time_str: 時刻文字列 (HH:MM形式、時刻がない場合は空文字列)。
        previous_add_event_lists: 既存のイベントリスト。
        article_url: 記事URL。description 照合に使う。

    Returns:
        重複している場合は True。
    """
    candidate_keys = []
    if event_time_str:
        candidate_keys.append(f"{event_date}-{event_name}-{event_time_str}")
    else:
        candidate_keys.append(f"{event_date}-{event_name}")

    if article_url:
        if event_time_str:
            candidate_keys.append(f"{event_date}-{article_url}-{event_time_str}")
        else:
            candidate_keys.append(f"{event_date}-{article_url}")

    for key in candidate_keys:
        if key in previous_add_event_lists:
            suffix = f" {event_time_str}" if event_time_str else ""
            LOGGER.info("pass: %s %s%s", event_date, event_name, suffix)
            return True
    return False


def generate_event_id(
    summary: str,
    event_day: str,
    event_start_time: datetime.datetime | None,
    event_link: str,
    *,
    test_run: bool,
) -> str:
    """Googleカレンダー用の自前eventIdを生成する.

    同じ予定であれば毎回同じIDになるようにすることで、insertを冪等にする。

    Args:
        summary: イベント名。
        event_day: イベント日。
        event_start_time: 開始日時。
        event_link: 記事URL。
        test_run: テスト実行ならランダムIDを返す。

    Returns:
        カレンダーeventId。
    """
    if test_run:
        return uuid.uuid4().hex

    if isinstance(event_start_time, datetime.datetime):
        time_str = event_start_time.strftime("%H:%M")
    else:
        time_str = ""

    base = f"mw-{event_day}-{summary}"
    if time_str:
        base += f"-{time_str}"
    if event_link:
        cleaned_link = str(event_link).strip()
        cleaned_link = cleaned_link.replace(_SITE_ORIGIN, "")
        cleaned_link = cleaned_link.replace("/", "-")
        base += f"-{cleaned_link}"

    return hashlib.sha1(
        base.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:_EVENT_ID_LENGTH]


def change_event_starttime_to_jst(
    events: list[dict],
) -> list[tuple[str, str]]:
    """イベント開始時間を日本時間の日付と時刻へ変換する.

    Args:
        events: Googleカレンダーのイベントリスト。

    Returns:
        `(日付, 時刻)` のリスト。終日は時刻が空文字。
    """
    events_starttime: list[tuple[str, str]] = []
    for event in events:
        if "date" in event["start"]:
            events_starttime.append((event["start"]["date"], ""))
            continue
        str_event_uct_time = event["start"]["dateTime"]
        event_jst_time = datetime.datetime.strptime(
            str_event_uct_time,
            "%Y-%m-%dT%H:%M:%S%z",
        )
        events_starttime.append((
            event_jst_time.strftime("%Y-%m-%d"),
            event_jst_time.strftime("%H:%M"),
        ))
    return events_starttime


def search_events(
    service: Resource,
    calendar_id: str,
    start_datetime: datetime.datetime,
    end_datetime: datetime.datetime,
) -> list[str]:
    """期間内の既存イベントキーを取得する.

    Args:
        service: Google Calendar APIのサービスインスタンス。
        calendar_id: カレンダーID。
        start_datetime: 検索開始日。
        end_datetime: 検索終了日。

    Returns:
        タイトル基準・URL基準のキー一覧。
    """
    start_day = start_datetime.strftime("%Y-%m-%d")
    end_day = end_datetime.strftime("%Y-%m-%d")
    events_result = (
        service
        .events()
        .list(
            maxResults=_MAX_EVENT_RESULTS,
            calendarId=calendar_id,
            timeMin=start_day + "T00:00:00+09:00",
            timeMax=end_day + "T23:59:00+09:00",
        )
        .execute()
    )
    events = events_result.get("items", [])
    if not events:
        return []

    events_starttime = change_event_starttime_to_jst(events)
    result_keys: list[str] = []
    for event, (event_date, event_time) in zip(
        events,
        events_starttime,
        strict=True,
    ):
        title_key = (
            f"{event_date}-{event['summary']}"
            if not event_time
            else f"{event_date}-{event['summary']}-{event_time}"
        )
        result_keys.append(title_key)
        desc = event.get("description") or ""
        if desc:
            url_key = (
                f"{event_date}-{desc}"
                if not event_time
                else f"{event_date}-{desc}-{event_time}"
            )
            result_keys.append(url_key)
    return result_keys


def add_info_to_calendar(
    service: Resource,
    calendar_id: str,
    draft: CalendarEventDraft,
    *,
    test_run: bool,
) -> None:
    """イベントをGoogleカレンダーへ登録する.

    Args:
        service: Google Calendar APIのサービスインスタンス。
        calendar_id: カレンダーID。
        draft: 登録するイベント。
        test_run: テスト実行ならランダムなeventIdを使う.

    Raises:
        HttpError: 409以外のGoogle Calendar APIエラー.
    """
    event_id = generate_event_id(
        draft.summary,
        draft.event_day,
        draft.start_time,
        draft.event_link,
        test_run=test_run,
    )
    if draft.start_time is None:
        event = {
            "id": event_id,
            "summary": draft.summary,
            "description": f"{draft.event_link}",
            "start": {
                "date": draft.event_day,
                "timeZone": "Japan",
            },
            "end": {
                "date": draft.event_day,
                "timeZone": "Japan",
            },
        }
    else:
        event = {
            "id": event_id,
            "summary": draft.summary,
            "description": f"{draft.event_link}",
            "start": {
                "dateTime": draft.start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Japan",
            },
            "end": {
                "dateTime": draft.end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Japan",
            },
        }

    try:
        service.events().insert(calendarId=calendar_id, body=event).execute()
    except HttpError as exc:
        if hasattr(exc, "resp") and getattr(exc.resp, "status", None) == _HTTP_CONFLICT:
            LOGGER.info(
                "already exists in calendar (id=%s): %s %s",
                event_id,
                draft.event_day,
                draft.summary,
            )
            return
        raise


def _existing_event_keys(
    service: Resource,
    calendar_id: str,
    schedule_list: list[tuple[str, str, str, str]],
) -> list[str]:
    """スケジュール期間に対応する既存イベントキーを取得する.

    Returns:
        既存イベントの照合キー一覧.
    """
    if not schedule_list:
        return []
    schedule_list.sort(key=itemgetter(0))
    start_datetime = datetime.datetime.strptime(
        schedule_list[0][0],
        "%Y-%m-%d",
    ).replace(tzinfo=_JST) + datetime.timedelta(days=-_LOOKBACK_DAYS)
    end_datetime = datetime.datetime.strptime(
        schedule_list[-1][0],
        "%Y-%m-%d",
    ).replace(tzinfo=_JST) + datetime.timedelta(days=_LOOKAHEAD_DAYS)
    return search_events(service, calendar_id, start_datetime, end_datetime)


@dataclass(frozen=True)
class CalendarSyncContext:
    """カレンダー同期に必要な実行時コンテキスト."""

    service: Resource
    calendar_id: str
    previous_keys: list[str]
    no_calendar: bool
    test_run: bool


def _add_or_skip_event(
    ctx: CalendarSyncContext,
    draft: CalendarEventDraft,
    check_date: str,
    check_time: str,
) -> None:
    """重複していなければカレンダーへ追加する."""
    if check_duplicate_event(
        draft.summary,
        check_date,
        check_time,
        ctx.previous_keys,
        article_url=draft.event_link,
    ):
        return

    if draft.start_time is None:
        LOGGER.info("add:%s %s", draft.event_day, draft.summary)
    else:
        LOGGER.info(
            "add: %s %s",
            draft.start_time.strftime("%Y-%m-%d %H:%M"),
            draft.summary,
        )
    if ctx.no_calendar:
        LOGGER.info("Googleカレンダーへの追加をスキップします。")
        return
    add_info_to_calendar(
        ctx.service,
        ctx.calendar_id,
        draft,
        test_run=ctx.test_run,
    )


def main(argv: list[str] | None = None) -> None:
    """ニュース記事からスケジュールを取得しカレンダーへ反映する.

    Args:
        argv: コマンドライン引数。None なら sys.argv を使う。
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Googleカレンダーへの追加を防ぐモードを設定します。",
    )
    parser.add_argument(
        "--no-calendar",
        action="store_true",
        help="Googleカレンダーへの追加を防ぎます。",
    )
    parser.add_argument(
        "--test-run",
        action="store_true",
        help="テスト用にランダムなeventIdを使用します。",
    )
    args = parser.parse_args(argv)
    singleton.SingleInstance()

    calendar_id = os.environ["CALENDAR_ID_MW"]
    service = build_calendar_api()
    schedule_list = get_schedule_list(1, 1)
    ctx = CalendarSyncContext(
        service=service,
        calendar_id=calendar_id,
        previous_keys=_existing_event_keys(service, calendar_id, schedule_list),
        no_calendar=args.no_calendar,
        test_run=args.test_run,
    )

    for event_time, event_name, _event_link, article_url in schedule_list:
        event_times = get_schedule_time(article_url)
        if not event_times:
            _add_or_skip_event(
                ctx,
                CalendarEventDraft(
                    summary=event_name,
                    event_day=event_time,
                    start_time=None,
                    end_time=None,
                    event_link=article_url,
                ),
                event_time,
                "",
            )
            continue

        for event_start_time, event_end_time in event_times:
            _add_or_skip_event(
                ctx,
                CalendarEventDraft(
                    summary=event_name,
                    event_day=event_start_time.strftime("%Y-%m-%d"),
                    start_time=event_start_time,
                    end_time=event_end_time,
                    event_link=article_url,
                ),
                event_start_time.strftime("%Y-%m-%d"),
                event_start_time.strftime("%H:%M"),
            )


if __name__ == "__main__":
    main()

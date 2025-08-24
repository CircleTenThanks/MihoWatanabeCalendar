import time
import pickle
import os
import sys
from tendo import singleton
import mojimoji
import re

import requests
from bs4 import BeautifulSoup

import datetime
from dateutil.relativedelta import relativedelta

from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.auth.transport.requests import Request

import argparse

# コマンドライン引数のパーサーを作成
parser = argparse.ArgumentParser(description='Googleカレンダーへの追加を防ぐモードを設定します。')
parser.add_argument('--no-calendar', action='store_true', help='Googleカレンダーへの追加を防ぎます。')
args = parser.parse_args()


def build_calendar_api():
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = service_account.Credentials.from_service_account_file("credentials_mw.json", scopes=SCOPES)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    service = build("calendar", "v3", credentials=creds)

    return service


def remove_blank(text):
    text = text.replace("\n", "")
    text = text.replace("\t", "")
    text = text.strip()
    return text


def get_schedule_list(start_page, end_page):
    schedule_list = []
    for page in range(start_page, end_page + 1):
        url = f"https://mihowatanabe.jp/news/all/pages/{page}"
        result = requests.get(url)
        soup = BeautifulSoup(result.content, features="lxml")

        # 各記事のリンクを取得
        # Chakra UIの動的クラス名に対応
        articles = soup.find_all("div", {"class": "css-izgksv"})
        
        # フォールバック - 記事らしいdiv要素を検索
        if not articles:
            # 記事の可能性が高いdiv要素を検索
            potential_articles = soup.find_all("div")
            for div in potential_articles:
                if div.get("class") and any("css-" in cls for cls in div.get("class")):
                    # リンク要素が含まれているかチェック
                    if div.find_parent("a", href=True):
                        articles.append(div)
        
        for article in articles:
            link_tag = article.find_parent("a", href=True)
            if link_tag:
                article_url = f"https://mihowatanabe.jp{link_tag['href']}"
                article_result = requests.get(article_url)
                if article_result.status_code == 200:
                    article_soup = BeautifulSoup(article_result.content, features="lxml")
                    
                    # 記事から日付とイベント名を抽出
                    event_time, event_name, event_link = get_schedule_info(article_soup)
                    if event_time and event_name:
                        schedule_list.append((event_time, event_name, event_link, article_url))

            time.sleep(1)  # サーバーへの負荷を解消

    return schedule_list


def get_schedule_info(article_soup):
    # イベント名を取得 - Chakra UIの動的クラス名に対応
    event_name = None
    
    # chakra-textクラスを持つh1要素を検索（CSSハッシュ部分は無視）
    h1_elements = article_soup.find_all("h1")
    for h1 in h1_elements:
        if h1.get("class") and any("chakra-text" in cls for cls in h1.get("class")):
            event_name = h1.get_text(strip=True)
            break
    
    # フォールバック - 最初のh1要素を使用
    if not event_name:
        h1_element = article_soup.find("h1")
        if h1_element:
            event_name = h1_element.get_text(strip=True)
    
    if not event_name:
        return None, None, None

    # 記事内容から実際のイベント日時を取得
    event_time = None
    
    # 特定のクラスを持つdiv要素を検索
    content_div = article_soup.find("div", {"class": "css-ikmllp"})
    
    # フォールバック - 記事本文らしいdiv要素を検索
    if not content_div:
        # 記事本文の可能性が高いdiv要素を検索
        potential_content_divs = article_soup.find_all("div")
        for div in potential_content_divs:
            if div.get("class") and any("css-" in cls for cls in div.get("class")):
                # 段落要素が含まれているかチェック
                if div.find_all("p"):
                    content_div = div
                    break
    
    if content_div:
        # chakra-textクラスを持つp要素を検索
        content_paragraphs = content_div.find_all("p")
        chakra_paragraphs = []
        for p in content_paragraphs:
            if p.get("class") and any("chakra-text" in cls for cls in p.get("class")):
                chakra_paragraphs.append(p)
        
        # フォールバック - すべてのp要素を使用
        if not chakra_paragraphs:
            chakra_paragraphs = content_paragraphs
        
        for p in chakra_paragraphs:
            text = p.get_text(strip=True)
            # "8月28日（木）25:00〜" のような形式を検索
            time_pattern = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2}):(\d{2})', text)
            if time_pattern:
                month = int(time_pattern.group(1))
                day = int(time_pattern.group(2))
                hour = int(time_pattern.group(3))
                
                # 現在の年を使用
                current_year = datetime.datetime.now().year
                
                # 25時などの表記を翌日に変換
                if hour >= 24:
                    day += 1
                    # 簡単な月末処理
                    if day > 31:
                        day = 1
                        month += 1
                        if month > 12:
                            month = 1
                            current_year += 1
                
                event_time = f"{current_year}-{month:02d}-{day:02d}"
                break
    
    # フォールバック: 記事の投稿日を使用
    if not event_time:
        # chakra-textクラスを持つp要素から日付を検索
        all_p_elements = article_soup.find_all("p")
        for p in all_p_elements:
            if p.get("class") and any("chakra-text" in cls for cls in p.get("class")):
                date_text = p.get_text(strip=True)
                # "2025.08.22" 形式を "2025-08-22" 形式に変換
                if re.match(r'\d{4}\.\d{1,2}\.\d{1,2}', date_text):
                    event_time = date_text.replace('.', '-')
                    break
        
        # フォールバック - 日付らしいテキストを検索
        if not event_time:
            for p in all_p_elements:
                date_text = p.get_text(strip=True)
                if re.match(r'\d{4}\.\d{1,2}\.\d{1,2}', date_text):
                    event_time = date_text.replace('.', '-')
                    break

    # 記事のリンクは現在のURLから取得
    current_url = article_soup.find("link", {"rel": "canonical"})
    if current_url:
        event_link = current_url.get('href', '')
        if event_link.startswith('https://mihowatanabe.jp'):
            event_link = event_link.replace('https://mihowatanabe.jp', '')
    else:
        event_link = "/news/detail/unknown"

    return event_time, event_name, event_link


def get_schedule_time(event_time, url):
    result = requests.get(url)
    soup = BeautifulSoup(result.content, features="lxml")

    # 記事の本文を取得（Chakra UIの動的クラス名に対応）
    content_div = soup.find("div", {"class": "css-ikmllp"})
    
    # フォールバック - 記事本文らしいdiv要素を検索
    if not content_div:
        # 記事本文の可能性が高いdiv要素を検索
        potential_content_divs = soup.find_all("div")
        for div in potential_content_divs:
            if div.get("class") and any("css-" in cls for cls in div.get("class")):
                # 段落要素が含まれているかチェック
                if div.find_all("p"):
                    content_div = div
                    break
    
    if content_div:
        # chakra-textクラスを持つp要素を検索
        all_p_elements = content_div.find_all("p")
        chakra_paragraphs = []
        for p in all_p_elements:
            if p.get("class") and any("chakra-text" in cls for cls in p.get("class")):
                chakra_paragraphs.append(p)
        
        # フォールバック - すべてのp要素を使用
        if chakra_paragraphs:
            line_list = chakra_paragraphs
        else:
            line_list = all_p_elements
    else:
        # フォールバック: 従来の方法
        schedule_detail = soup.find("div")
        line_list = schedule_detail.find_all("p") if schedule_detail else []

    # 複数の日時を格納するリスト（重複を防ぐためsetを使用）
    event_times_set = set()
    # 処理済みの行を追跡するためのset
    processed_lines = set()

    def add_event_time(event_start, event_end):
        """日時をsetに追加する共通処理"""
        time_key = f"{event_start.strftime('%Y-%m-%d %H:%M')}-{event_end.strftime('%Y-%m-%d %H:%M')}"
        if time_key not in event_times_set:
            event_times_set.add(time_key)
            event_times_set.add((event_start, event_end))

    def get_target_year(month):
        """年を動的に判定する共通処理"""
        current_year = datetime.datetime.now().year
        current_month = datetime.datetime.now().month
        
        # 年をまたぐ場合の処理
        # 例：7-12月に翌年1-6月のスケジュールが投稿された場合
        if current_month >= 7 and month <= 6:  # 7-12月に1-6月のスケジュール
            return current_year + 1
        elif current_month <= 6 and month >= 7:  # 1-6月に7-12月のスケジュール
            return current_year - 1
        else:
            return current_year

    for line in line_list:
        original_text = line.get_text(strip=True) if hasattr(line, 'get_text') else str(line)
        
        # 既に処理済みの行はスキップ
        if original_text in processed_lines:
            continue
        
        # まず、すべてのパターンで使用する統一されたテキスト処理を行う
        line_text = mojimoji.zen_to_han(original_text, kana=False)
        line_text = line_text.replace("-", "~")
        line_text = line_text.replace("〜", "~")
        line_text = line_text.replace("年", "/")
        line_text = line_text.replace("月", "/")
        line_text = line_text.replace("日", "")
        line_text = line_text.replace("時", ":")
        line_text = line_text.replace("分", "")
        
        # 12時間表記で記載されているパターン
        hour12_flg = False
        date_text_arr = re.search(r'午後(\d+)', line_text)
        if date_text_arr != None:
            if int(date_text_arr[1]) <= 12:
                hour12_flg = True
        date_text_arr = re.search(r'(よる|夜)(\d+)', line_text)
        if date_text_arr != None:
            if 6 <= int(date_text_arr[2]) <= 12:
                hour12_flg = True

        # 日付と時刻のパターンを検索（優先度1: 最も具体的なパターン）
        # "8/28 25:00" のような形式（統一処理後のline_textで検索）
        # 年を含む日付形式（2025/7/7）にはマッチしないように修正
        # 行の先頭が4桁の数字で始まらないことを確認
        
        time_pattern1 = re.search(r'^(?!\d{4}/)(\d{1,2})/(\d{1,2}).*?(\d{1,2}):(\d{2})', line_text)
        if time_pattern1:
            month = int(time_pattern1.group(1))
            day = int(time_pattern1.group(2))
            hour = int(time_pattern1.group(3))
            minute = int(time_pattern1.group(4))
            
            # 年を動的に判定
            target_year = get_target_year(month)
            
            # 25時などの表記を翌日に変換
            if hour >= 24:
                hour -= 24
                day += 1
                # 月末の処理
                if day > 31:
                    day = 1
                    month += 1
                    if month > 12:
                        month = 1
                        target_year += 1
            
            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = datetime.datetime(target_year, month, day, hour, minute)
            event_end = event_start + datetime.timedelta(hours=1)  # デフォルトで1時間後
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue

        # 年月日、開始時分、終了時分まですべて記載されているパターン（優先度2）
        date_text_arr = re.search(r'(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)', line_text)

        if date_text_arr != None:
            year = int(date_text_arr[1])
            month = int(date_text_arr[2])
            day = int(date_text_arr[3])
            if hour12_flg:
                hour_start = int(date_text_arr[4]) + 12
            else:
                hour_start = int(date_text_arr[4])
            minute_start = int(date_text_arr[5])
            if hour12_flg:
                hour_end = int(date_text_arr[6]) + 12
            else:
                hour_end = int(date_text_arr[6])
            minute_end = int(date_text_arr[7])

            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = over24Hdatetime(year, month, day, f'{hour_start:02d}:{minute_start:02d}')
            event_end = over24Hdatetime(year, month, day, f'{hour_end:02d}:{minute_end:02d}')
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue

        # 年月日、開始時分が記載されているパターン（優先度3）
        date_text_arr = re.search(r'(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)', line_text)

        if date_text_arr != None:
            year = int(date_text_arr[1])
            month = int(date_text_arr[2])
            day = int(date_text_arr[3])
            if hour12_flg:
                hour_start = int(date_text_arr[4]) + 12
            else:
                hour_start = int(date_text_arr[4])
            minute_start = int(date_text_arr[5])

            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = event_end = over24Hdatetime(year, month, day, f'{hour_start:02d}:{minute_start:02d}')
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue
            
        # 月日、開始時分、終了時分が記載されているパターン（優先度4）
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)', line_text)

        if date_text_arr != None:
            # 年を動的に判定
            month = int(date_text_arr[1])
            target_year = get_target_year(month)
            
            day = int(date_text_arr[2])
            if hour12_flg:
                hour_start = int(date_text_arr[3]) + 12
            else:
                hour_start = int(date_text_arr[3])
            minute_start = int(date_text_arr[4])
            if hour12_flg:
                hour_end = int(date_text_arr[5]) + 12
            else:
                hour_end = int(date_text_arr[5])
            minute_end = int(date_text_arr[6])

            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = over24Hdatetime(target_year, month, day, f'{hour_start:02d}:{minute_start:02d}')
            event_end = over24Hdatetime(target_year, month, day, f'{hour_end:02d}:{minute_end:02d}')
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue
        
        # 月日、開始時分が記載されているパターン（優先度5）
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):(\d+)', line_text)

        if date_text_arr != None:
            # 年を動的に判定
            month = int(date_text_arr[1])
            target_year = get_target_year(month)
            
            day = int(date_text_arr[2])
            if hour12_flg:
                hour_start = int(date_text_arr[3]) + 12
            else:
                hour_start = int(date_text_arr[3])
            minute_start = int(date_text_arr[4])

            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = event_end = over24Hdatetime(target_year, month, day, f'{hour_start:02d}:{minute_start:02d}')
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue
            
        # 月日、開始時が記載されているパターン（優先度6）
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):', line_text)

        if date_text_arr != None:
            # 年を動的に判定
            month = int(date_text_arr[1])
            target_year = get_target_year(month)
            
            day = int(date_text_arr[2])
            if hour12_flg:
                hour_start = int(date_text_arr[3]) + 12
            else:
                hour_start = int(date_text_arr[3])
            minute_start = 0

            # すべての日時を取得（記事の基本日付に関係なく）
            event_start = event_end = over24Hdatetime(target_year, month, day, f'{hour_start:02d}:{minute_start:02d}')
            add_event_time(event_start, event_end)
            
            # この行を処理済みとしてマーク
            processed_lines.add(original_text)
            continue
    
    # setから実際の日時タプルのみを抽出
    event_times = []
    for item in event_times_set:
        if isinstance(item, tuple):
            event_times.append(item)
    
    # 複数の日時が見つかった場合はリストで返す、見つからなかった場合は空のリストを返す
    if event_times:
        return event_times
    else:
        return []


def over24Hdatetime(year, month, day, times):
    """
    24H以上の時刻をdatetimeに変換する
    """
    hour, minute = times.split(":")

    # to minute
    minutes = int(hour) * 60 + int(minute)

    dt = datetime.datetime(year=int(year), month=int(month), day=int(day))
    dt += datetime.timedelta(minutes=minutes)

    return dt


def prepare_info_for_calendar(
    event_name, event_time, previous_add_event_lists, confirm
):
    if (
        f"{event_time}-{event_name}" in previous_add_event_lists
    ):  
        print(f"pass: {event_time} {event_name}")
        return True
    else:
        if confirm:
            return False
        return False


def change_event_starttime_to_jst(events):
    events_starttime = []
    for event in events:
        if "date" in event["start"].keys():
            events_starttime.append(event["start"]["date"])
        else:
            str_event_uct_time = event["start"]["dateTime"]
            event_jst_time = datetime.datetime.strptime(
                str_event_uct_time, "%Y-%m-%dT%H:%M:%S+09:00"
            )
            # 重複チェック用には日付のみを返す（時刻情報は別途管理）
            str_event_jst_time = event_jst_time.strftime("%Y-%m-%d")
            events_starttime.append(str_event_jst_time)
    return events_starttime


def search_events(service, calendar_id, start_datetime, end_datetime):
    start_day = start_datetime.strftime("%Y-%m-%d")
    end_day = end_datetime.strftime("%Y-%m-%d")

    events_result = (
        service.events()
        .list(
            maxResults=2500,
            calendarId=calendar_id,
            timeMin=start_day + "T00:00:00+09:00",  # NOTE:+09:00とするのが肝。（UTCをJSTへ変換）
            timeMax=end_day + "T23:59:00+09:00",  # NOTE;来月までをサーチ期間に。
        )
        .execute()
    )
    events = events_result.get("items", [])

    if not events:
        return []
    else:
        events_starttime = change_event_starttime_to_jst(events)
        return [
            event_starttime + "-" +  event["summary"]
            for event, event_starttime in zip(events, events_starttime)
        ]


def add_info_to_calendar(calendarId, summary, event_day, event_start_time, event_end_time, event_link):
    if(event_start_time == ""):
        event = {
            "summary": summary,
            "description": f"{event_link}",
            "start": {"date": event_day, "timeZone": "Japan",},
            "end": {"date": event_day, "timeZone": "Japan",},
        }
    else:
        event = {
            "summary": summary,
            "description": f"{event_link}",
            "start": {"dateTime": event_start_time.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Japan",},
            "end": {"dateTime": event_end_time.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Japan",},
        }

    event = service.events().insert(calendarId=calendarId, body=event,).execute()


me = singleton.SingleInstance() 

# API系
calendarId = (
    os.environ['CALENDAR_ID_MW']  # NOTE:自分のカレンダーID
)
service = build_calendar_api()

schedule_list = get_schedule_list(1, 1)  # ページ1から1まで処理

if schedule_list == None:
    sys.exit()

# 初期化
if schedule_list:
    # スケジュールリストを日付順にソート
    schedule_list.sort(key=lambda x: x[0])
    
    # スケジュールリストから期間を計算
    start_day = schedule_list[0][0]  # 最初のイベントの日付（最も古い日付）
    end_day = schedule_list[-1][0]   # 最後のイベントの日付（最も新しい日付）
    
    start_datetime = datetime.datetime.strptime(start_day, "%Y-%m-%d")
    start_datetime = start_datetime + datetime.timedelta(days=-1)
    end_datetime = datetime.datetime.strptime(end_day, "%Y-%m-%d")
    end_datetime = end_datetime + datetime.timedelta(days=1)
    
    # 既存のイベントを取得
    previous_add_event_lists = search_events(service, calendarId, start_datetime, end_datetime)
else:
    previous_add_event_lists = []

for event_time, event_name, event_link, article_url in schedule_list:
    # 時刻情報を取得
    event_times = get_schedule_time(event_time, article_url)
    
    # 時刻情報がない場合の処理
    if not event_times:
        # 重複チェック
        if prepare_info_for_calendar(
            event_name,
            event_time,
            previous_add_event_lists,
            False,
        ) == True:
            continue

        print("add:" + event_time + " " + event_name)

        # カレンダーへ情報を追加
        if args.no_calendar:
            print("Googleカレンダーへの追加をスキップします。")
        else:
            add_info_to_calendar(
                calendarId,
                event_name,
                event_time,
                "",  # 時刻なし
                "",  # 時刻なし
                article_url,
            )
    else:
        # 複数の時刻情報がある場合の処理
        for i, (event_start_time, event_end_time) in enumerate(event_times):
            
            # 重複チェック（時刻情報がある場合は時刻付きの日付で）
            check_date = event_start_time.strftime("%Y-%m-%d")
            
            # イベント名と日時を組み合わせて重複チェック
            # 同じ記事内の異なる日時は個別のイベントとして扱う
            check_key = f"{check_date}-{event_name}-{event_start_time.strftime('%H:%M')}"
            
            # 既存のイベントリストから、同じ日付・イベント名・時刻の組み合わせをチェック
            # 時刻が異なる場合は個別のイベントとして扱う
            if check_key in previous_add_event_lists:
                # 同じ日付・イベント名・時刻の組み合わせが既に存在する場合
                print(f"pass: {check_date} {event_name} {event_start_time.strftime('%H:%M')}")
                continue
            
            if prepare_info_for_calendar(
                event_name,
                check_date,
                previous_add_event_lists,
                False,
            ) == True:
                print(f"pass: {check_date} {event_name} {event_start_time.strftime('%H:%M')}")
                continue

            print(f"add: {event_start_time.strftime('%Y-%m-%d %H:%M')} {event_name}")

            # カレンダーへ情報を追加
            if args.no_calendar:
                print("Googleカレンダーへの追加をスキップします。")
            else:
                add_info_to_calendar(
                    calendarId,
                    event_name,
                    event_time,
                    event_start_time,
                    event_end_time,
                    article_url,
                )

import time
import pickle
import os.path

import requests
from bs4 import BeautifulSoup

import datetime
from dateutil.relativedelta import relativedelta

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


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
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    service = build("calendar", "v3", credentials=creds)

    return service


def remove_blank(text):
    text = text.replace("\n", "")
    text = text.replace(" ", "")
    return text


def search_event_each_date(year, month):
    url = (
        f"https://www.hinatazaka46.com/s/official/media/list?ima=0000&dy={year}{month}"
    )
    result = requests.get(url)
    soup = BeautifulSoup(result.content, features="lxml")
    events_each_date = soup.find_all("div", {"class": "p-schedule__list-group"})

    time.sleep(3)  # NOTE:サーバーへの負荷を解消

    return events_each_date


def search_start_and_end_time(event_time_text):
    has_end = event_time_text[-1] != "～"
    if has_end:
        start, end = event_time_text.split("～")
    else:
        start = event_time_text.split("～")[0]
        end = start
    start += ":00"
    end += ":00"
    return start, end


def search_event_info(event_each_date):
    event_date_text = remove_blank(event_each_date.contents[1].text)[
        :-1
    ]  # NOTE:曜日以外の情報を取得
    events_time = event_each_date.find_all("div", {"class": "c-schedule__time--list"})
    events_name = event_each_date.find_all("p", {"class": "c-schedule__text"})
    events_category = event_each_date.find_all("div", {"class": "p-schedule__head"},)
    events_link = event_each_date.find_all("li", {"class": "p-schedule__item"})

    return event_date_text, events_time, events_name, events_category, events_link


def search_detail_info(event_name, event_category, event_time, event_link):
    event_name_text = remove_blank(event_name.text)
    event_category_text = remove_blank(event_category.contents[1].text)
    event_time_text = remove_blank(event_time.text)
    event_link = event_link.find("a")["href"]
    active_members = search_active_member(event_link)

    return event_name_text, event_category_text, event_time_text, active_members

def search_active_member(link):
    try:
        url = f"https://www.hinatazaka46.com{link}"
        result = requests.get(url)
        soup = BeautifulSoup(result.content, features="lxml")
        active_members = soup.find("div", {"class": "c-article__tag"}).text
        time.sleep(3)  # NOTE:サーバー負荷の解消
    except AttributeError:
        active_members = ""

    return active_members


def over24Hdatetime(year, month, day, times):
    """
    24H以上の時刻をdatetimeに変換する
    """
    hour, minute = times.split(":")[:-1]

    # to minute
    minutes = int(hour) * 60 + int(minute)

    dt = datetime.datetime(year=int(year), month=int(month), day=int(day))
    dt += datetime.timedelta(minutes=minutes)

    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def prepare_info_for_calendar(
    event_name_text, event_category_text, event_time_text, active_members
):
    event_title = f"({event_category_text}){event_name_text}"
    if event_time_text == "":
        event_start = f"{year}-{month}-{event_date_text}"
        event_end = f"{year}-{month}-{event_date_text}"
        is_date = True
    else:
        start, end = search_start_and_end_time(event_time_text)
        event_start = over24Hdatetime(year, month, event_date_text, start)
        event_end = over24Hdatetime(year, month, event_date_text, end)
        is_date = False
    return event_title, event_start, event_end, is_date


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
            str_event_jst_time = event_jst_time.strftime("%Y-%m-%dT%H:%M:%S")
            events_starttime.append(str_event_jst_time)
    return events_starttime


def search_events(service, calendar_id, start):

    end_datetime = datetime.datetime.strptime(start, "%Y-%m-%d") + relativedelta(
        months=1
    )
    end = end_datetime.strftime("%Y-%m-%d")

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start + "T00:00:00+09:00",  # NOTE:+09:00とするのが肝。（UTCをJSTへ変換）
            timeMax=end + "T23:59:00+09:00",  # NOTE;来月までをサーチ期間に。
        )
        .execute()
    )
    events = events_result.get("items", [])

    if not events:
        return []
    else:
        events_starttime = change_event_starttime_to_jst(events)
        return [
            event["summary"] + "-" + event_starttime
            for event, event_starttime in zip(events, events_starttime)
        ]


def add_date_schedule(
    event_name, event_category, event_time, event_link, previous_add_event_lists
):
    (
        event_name_text,
        event_category_text,
        event_time_text,
        active_members,
    ) = search_detail_info(event_name, event_category, event_time, event_link)

    # カレンダーに反映させる情報の準備
    (event_title, event_start, event_end, is_date,) = prepare_info_for_calendar(
        event_name_text, event_category_text, event_time_text, active_members,
    )

    if (
        f"{event_title}-{event_start}" in previous_add_event_lists
    ):  # NOTE:同じ予定がすでに存在する場合はパス
        pass
    else:
        add_info_to_calendar(
            calendarId, event_title, event_start, event_end, active_members, is_date,
        )


def add_info_to_calendar(calendarId, summary, start, end, active_members, is_date):

    if is_date:
        event = {
            "summary": summary,
            "description": active_members,
            "start": {"date": start, "timeZone": "Japan",},
            "end": {"date": end, "timeZone": "Japan",},
        }
    else:
        event = {
            "summary": summary,
            "description": active_members,
            "start": {"dateTime": start, "timeZone": "Japan",},
            "end": {"dateTime": end, "timeZone": "Japan",},
        }

    event = service.events().insert(calendarId=calendarId, body=event,).execute()


if __name__ == "__main__":

    # -------------------------step1:各種設定-------------------------
    # API系
    calendarId = (
        "〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜〜"  # NOTE:自分のカレンダーID
    )
    service = build_calendar_api()

    # サーチ範囲
    num_search_month = 3  # NOTE;3ヶ月先の予定までカレンダーに反映
    current_search_date = datetime.datetime.now()
    year = current_search_date.year
    month = current_search_date.month

    # -------------------------step2.各日付ごとの情報を取得-------------------------
    for _ in range(num_search_month):
        events_each_date = search_event_each_date(year, month)
        for event_each_date in events_each_date:

            # step3: 特定の日の予定を一括で取得
            (
                event_date_text,
                events_time,
                events_name,
                events_category,
                events_link,
            ) = search_event_info(event_each_date)

            event_date_text = "{:0=2}".format(
                int(event_date_text)
            )  # NOTE;２桁になるように0埋め（ex.0-> 01）
            start = f"{year}-{month}-{event_date_text}"
            previous_add_event_lists = search_events(service, calendarId, start)

            # step4: カレンダーへ情報を追加
            for event_name, event_category, event_time, event_link in zip(
                events_name, events_category, events_time, events_link
            ):
                add_date_schedule(
                    event_name,
                    event_category,
                    event_time,
                    event_link,
                    previous_add_event_lists,
                )

        # step5:次の月へ
        current_search_date = current_search_date + relativedelta(months=1)
        year = current_search_date.year
        month = current_search_date.month

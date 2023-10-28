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
            creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
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
        url = f"https://mihowatanabe.jp/contents/schedule/page/{page}"
        result = requests.get(url)
        soup = BeautifulSoup(result.content, features="lxml")

        schedule_list.extend(soup.find_all("li", {"class": "list-item"}))

        time.sleep(1)  # NOTE:サーバーへの負荷を解消

    return schedule_list


def get_schedule_info(schedule_list):

    event_time = schedule_list.find("time", {"class": "time"})
    if event_time != None:
        event_time = event_time['datetime']

    event_name = schedule_list.find("h3", {"class": "list-title"})
    if event_name != None:
        event_name = event_name.contents[0]
        event_name = remove_blank(event_name)

    event_link = schedule_list.find("a", {"class": "gtm_content_link"})
    if event_link != None:
        event_link = event_link['href']

    return event_time, event_name, event_link


def get_schedule_time(event_time, url):

    result = requests.get(url)
    soup = BeautifulSoup(result.content, features="lxml")

    schedule_detail = soup.find("div", {"class": "body"})
    line_list = schedule_detail.find_all("p")

    for line in line_list:
        
        line = mojimoji.zen_to_han(line.text, kana=False)
        line = line.replace("-", "~")
        line = line.replace("〜", "~")  # 機種依存文字が使われていることがあった
        line = line.replace("年", "/")
        line = line.replace("月", "/")
        line = line.replace("日", "")
        line = line.replace("時", ":")
        line = line.replace("分", "")

        # 年月日、開始時分、終了時分まですべて記載されているパターン
        date_text_arr = re.search(r'(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)', line)

        if date_text_arr != None:
            year = date_text_arr[1]
            month = date_text_arr[2].zfill(2)
            day = date_text_arr[3].zfill(2)
            hour_start = date_text_arr[4].zfill(2)
            minute_start = date_text_arr[5].zfill(2)
            hour_end = date_text_arr[6].zfill(2)
            minute_end = date_text_arr[7].zfill(2)

            if event_time != f'{year}-{month}-{day}':
                continue
            else:
                event_start = over24Hdatetime(year, month, day, f'{hour_start}:{minute_start}')
                event_end = over24Hdatetime(year, month, day, f'{hour_end}:{minute_end}')
                return event_start, event_end

        # 年月日、開始時分が記載されているパターン
        date_text_arr = re.search(r'(\d{4})/(\d+)/(\d+).+?(\d+):(\d+)', line)

        if date_text_arr != None:
            year = date_text_arr[1]
            month = date_text_arr[2].zfill(2)
            day = date_text_arr[3].zfill(2)
            hour_start = date_text_arr[4].zfill(2)
            minute_start = date_text_arr[5].zfill(2)

            if event_time != f'{year}-{month}-{day}':
                continue
            else:
                event_start = event_end = over24Hdatetime(year, month, day, f'{hour_start}:{minute_start}')
                return event_start, event_end
            
        # 月日、開始時分、終了時分が記載されているパターン
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):(\d+)~(\d+):(\d+)', line)

        if date_text_arr != None:
            year = event_time.split('-')[0]
            month = date_text_arr[1].zfill(2)
            day = date_text_arr[2].zfill(2)
            hour_start = date_text_arr[3].zfill(2)
            minute_start = date_text_arr[4].zfill(2)
            hour_end = date_text_arr[5].zfill(2)
            minute_end = date_text_arr[6].zfill(2)

            if event_time != f'{year}-{month}-{day}':
                continue
            else:
                event_start = over24Hdatetime(year, month, day, f'{hour_start}:{minute_start}')
                event_end = over24Hdatetime(year, month, day, f'{hour_end}:{minute_end}')
                return event_start, event_end
        
        # 月日、開始時分が記載されているパターン
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):(\d+)', line)

        if date_text_arr != None:
            year = event_time.split('-')[0]
            month = date_text_arr[1].zfill(2)
            day = date_text_arr[2].zfill(2)
            hour_start = date_text_arr[3].zfill(2)
            minute_start = date_text_arr[4].zfill(2)

            if event_time != f'{year}-{month}-{day}':
                continue
            else:
                event_start = event_end = over24Hdatetime(year, month, day, f'{hour_start}:{minute_start}')
                return event_start, event_end
            
        # 月日、開始時が記載されているパターン
        date_text_arr = re.search(r'(\d+)/(\d+).+?(\d+):', line)

        if date_text_arr != None:
            year = event_time.split('-')[0]
            month = date_text_arr[1].zfill(2)
            day = date_text_arr[2].zfill(2)
            hour_start = date_text_arr[3].zfill(2)
            minute_start = "00"

            if event_time != f'{year}-{month}-{day}':
                continue
            else:
                event_start = event_end = over24Hdatetime(year, month, day, f'{hour_start}:{minute_start}')
                return event_start, event_end
    
    return "", ""


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
        print("pass:" + event_time + " " + event_name)
        return True
    else:
        if confirm:
            print("add:" + event_time + " " + event_name)
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


if __name__ == "__main__":
    me = singleton.SingleInstance() 

    # API系
    calendarId = (
        os.environ['CALENDAR_ID']  # NOTE:自分のカレンダーID
    )
    service = build_calendar_api()

    schedule_list = get_schedule_list(1, 1)

    if schedule_list == None:
        sys.exit()

    
    for schedule in schedule_list:
        start_day_buf = schedule.find("time", {"class": "time"})
        if start_day_buf == None:
            break
        start_day_buf = start_day_buf['datetime']
        if start_day_buf == None:
            break
        else:
           start_day = start_day_buf

    start_datetime = datetime.datetime.strptime(start_day, "%Y-%m-%d")
    start_datetime = start_datetime + datetime.timedelta(days=-1)
    end_day = schedule_list[0].find("time", {"class": "time"})['datetime']
    end_datetime = datetime.datetime.strptime(end_day, "%Y-%m-%d")
    end_datetime = end_datetime + datetime.timedelta(days=1)
    previous_add_event_lists = search_events(service, calendarId, start_datetime, end_datetime)

    for schedule in schedule_list:
        (
            event_day,
            event_name,
            event_link,
        ) = get_schedule_info(schedule)

        if (event_day == None or
            event_name == None or
            event_link == None):
            continue

        if prepare_info_for_calendar(
            event_name,
            event_day,
            previous_add_event_lists,
            False,
        ) == True:
            continue

        url = f'https://mihowatanabe.jp{event_link}'
        (
            event_start_time,
            event_end_time,
        )= get_schedule_time(event_day, url)

        # 24時を跨ぐ時刻表記によって日付が変わっているためもう一度
        if event_start_time != "":
            if prepare_info_for_calendar(
                event_name,
                event_start_time.strftime("%Y-%m-%d"),
                previous_add_event_lists,
                True,
            ) == True:
                continue
        else:
            print("add:" + event_day + " " + event_name)


        # step4: カレンダーへ情報を追加
        add_info_to_calendar(
            calendarId,
            event_name,
            event_day,
            event_start_time,
            event_end_time,
            url,
        )

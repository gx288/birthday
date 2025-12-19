import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from telegram import Bot
from telegram.error import BadRequest
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import json
import asyncio
from lunarcalendar import Converter, Solar, Lunar
import pytz

# Cấu hình
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
SHEET_NAME = 'Trang tính1'
RANGE_NAME = f'{SHEET_NAME}!A:E'

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')  # Chat chính (nhận cả sinh nhật + mùng 1/rằm)
TELEGRAM_CHAT_ID_SPECIAL = os.getenv('TELEGRAM_CHAT_ID_SPECIAL')  # Chat thứ 2 (chỉ nhận mùng 1/rằm)

VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')

# Đọc Google Sheet
def get_sheet_data():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SHEET_ID, range=RANGE_NAME).execute()
        data = result.get('values', [])
        print(f"Sheet data loaded: {len(data)} rows")
        return data
    except Exception as e:
        print(f"Error reading Google Sheet: {e}")
        raise

# Ghi dữ liệu vào Google Sheet
def update_sheet_data(values):
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()
        body = {'values': values}
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=RANGE_NAME,
            valueInputOption='RAW',
            body=body
        ).execute()
        print("Google Sheet updated successfully")
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        raise

# Gửi tin nhắn Telegram - hỗ trợ gửi đến nhiều chat
async def send_telegram_message(message, extra_chat_ids=None):
    """
    Gửi tin nhắn đến chat chính, và tùy chọn thêm các chat khác (extra_chat_ids)
    """
    chat_ids = [TELEGRAM_CHAT_ID]
    
    if extra_chat_ids:
        if isinstance(extra_chat_ids, str):
            chat_ids.append(extra_chat_ids)
        else:
            chat_ids.extend(extra_chat_ids)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    for chat_id in chat_ids:
        if not chat_id:
            continue  # Bỏ qua nếu chat ID rỗng
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
            print(f"Sent to {chat_id}: {message}")
        except BadRequest as e:
            print(f"Markdown error for {chat_id}, retrying plain text: {e}")
            await bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")

# Chuyển âm → dương
def convert_lunar_to_solar(lunar_day, lunar_month, target_year):
    try:
        lunar = Lunar(target_year, lunar_month, lunar_day, isleap=False)
        solar = Converter.Lunar2Solar(lunar)
        return datetime(solar.year, solar.month, solar.day)
    except ValueError as e:
        print(f"Error converting lunar {lunar_day}/{lunar_month}/{target_year}: {e}")
        return None

# Chuyển dương → âm (để kiểm tra mùng 1, rằm)
def convert_solar_to_lunar(solar_date):
    try:
        solar = Solar(solar_date.year, solar_date.month, solar_date.day)
        lunar = Converter.Solar2Lunar(solar)
        return lunar.day, lunar.month, lunar.isleap
    except Exception as e:
        print(f"Error converting solar {solar_date} to lunar: {e}")
        return None, None, None

# Cập nhật cột D và E từ ngày âm lịch
def update_lunar_solar_dates():
    current_year = datetime.now(VN_TIMEZONE).year
    previous_year = current_year - 1
    data = get_sheet_data()
    updated_data = data.copy()
    updated = False

    for i, row in enumerate(data[1:], start=1):
        if len(row) <= 2 or not row[2].strip():
            continue
        lunar_date = row[2].strip()
        try:
            parts = lunar_date.split('/')
            if len(parts) < 2:
                continue
            lunar_day = int(parts[0])
            lunar_month = int(parts[1])

            solar_prev = convert_lunar_to_solar(lunar_day, lunar_month, previous_year)
            solar_curr = convert_lunar_to_solar(lunar_day, lunar_month, current_year)

            while len(updated_data[i]) < 5:
                updated_data[i].append('')

            prev_str = solar_prev.strftime('%d/%m/%Y') if solar_prev else ''
            curr_str = solar_curr.strftime('%d/%m/%Y') if solar_curr else ''

            if updated_data[i][3] != prev_str or updated_data[i][4] != curr_str:
                updated_data[i][3] = prev_str
                updated_data[i][4] = curr_str
                updated = True
        except (ValueError, IndexError):
            continue

    if updated:
        update_sheet_data(updated_data)
    else:
        print("No updates needed for lunar dates")

# Kiểm tra sinh nhật
def check_birthdays(target_date, is_tomorrow=False):
    target_month_day = target_date.strftime('%m/%d')
    data = get_sheet_data()
    birthdays = []

    for row in data[1:]:
        if not row:
            continue
        name = row[0].strip()
        solar_date = row[1].strip() if len(row) > 1 else ''
        lunar_prev = row[3].strip() if len(row) > 3 else ''
        lunar_curr = row[4].strip() if len(row) > 4 else ''
        lunar_date = row[2].strip() if len(row) > 2 else ''

        # Dương lịch
        if solar_date:
            try:
                if datetime.strptime(solar_date, '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    msg = (
                        f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                        f"Theo ngày dương: {solar_date}"
                    )
                    birthdays.append((msg, name))
            except ValueError:
                pass

        # Âm lịch năm trước
        if lunar_prev and lunar_date:
            try:
                if datetime.strptime(lunar_prev, '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    parts = lunar_date.split('/')
                    day_month = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ''
                    msg = (
                        f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                        f"Theo ngày âm: ({lunar_date} - {day_month}/{target_date.year - 1})"
                    )
                    birthdays.append((msg, name))
            except ValueError:
                pass

        # Âm lịch năm nay
        if lunar_curr and lunar_date:
            try:
                if datetime.strptime(lunar_curr, '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    parts = lunar_date.split('/')
                    day_month = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ''
                    msg = (
                        f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                        f"Theo ngày âm: ({lunar_date} - {day_month}/{target_date.year})"
                    )
                    birthdays.append((msg, name))
            except ValueError:
                pass

    return birthdays

# Kiểm tra mùng 1 và rằm trong 3 ngày tới (hôm nay, mai, kia)
async def check_mung_ram():
    today = datetime.now(VN_TIMEZONE).date()
    messages = []

    for i in range(3):  # 0: hôm nay, 1: mai, 2: kia
        check_date = today + timedelta(days=i)
        lunar_day, lunar_month, _ = convert_solar_to_lunar(check_date)

        if lunar_day is not None and lunar_day in [1, 15]:
            event = "mùng 1" if lunar_day == 1 else "rằm"
            day_word = "Hôm nay" if i == 0 else "Ngày mai" if i == 1 else "Ngày kia"
            message = f"*{day_word} là {event} tháng {lunar_month} âm lịch*"
            messages.append(message)
            print(f"Special day: {day_word} là {event} tháng {lunar_month}")

    return messages

# Hàm chính
async def main():
    print(f"Script started at {datetime.now(VN_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S %Z')}")

    update_lunar_solar_dates()

    today = datetime.now(VN_TIMEZONE)
    tomorrow = today + timedelta(days=1)

    # Sinh nhật: chỉ gửi đến chat chính
    today_birthdays = check_birthdays(today, is_tomorrow=False)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    for msg, _ in today_birthdays:
        await send_telegram_message(msg)  # Không có extra

    for msg, _ in tomorrow_birthdays:
        await send_telegram_message(msg)  # Không có extra

    # Mùng 1 / Rằm: gửi đến cả 2 chat (nếu có TELEGRAM_CHAT_ID_SPECIAL)
    special_events = await check_mung_ram()
    for msg in special_events:
        await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)

    if not today_birthdays and not tomorrow_birthdays and not special_events:
        print("Không có sinh nhật hoặc ngày mùng 1/rằm nào trong 3 ngày tới.")

if __name__ == '__main__':
    asyncio.run(main())

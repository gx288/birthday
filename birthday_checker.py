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
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
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

# Gửi thông báo Telegram
async def send_telegram_message(message):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.MARKDOWN)
        print(f"Sent Telegram: {message}")
    except BadRequest as e:
        print(f"Markdown error, retrying without Markdown: {e}")
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)  # Gửi lại không format
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        raise

# Chuyển âm lịch → dương lịch
def convert_lunar_to_solar(lunar_day, lunar_month, target_year):
    try:
        lunar = Lunar(target_year, lunar_month, lunar_day, isleap=False)
        solar = Converter.Lunar2Solar(lunar)
        return datetime(solar.year, solar.month, solar.day)
    except ValueError as e:
        print(f"Error converting lunar {lunar_day}/{lunar_month}/{target_year}: {e}")
        return None

# Chuyển dương lịch → âm lịch (để kiểm tra mùng 1, rằm)
def convert_solar_to_lunar(solar_date):
    try:
        solar = Solar(solar_date.year, solar_date.month, solar_date.day)
        lunar = Converter.Solar2Lunar(solar)
        return lunar.day, lunar.month, lunar.isleap
    except Exception as e:
        print(f"Error converting solar {solar_date} to lunar: {e}")
        return None, None, None

# Cập nhật cột D (năm trước) và E (năm hiện tại) từ ngày âm lịch
def update_lunar_solar_dates():
    current_year = datetime.now(VN_TIMEZONE).year
    previous_year = current_year - 1
    data = get_sheet_data()
    updated_data = data.copy()
    updated = False

    for i, row in enumerate(data[1:], start=1):  # Bỏ hàng tiêu đề
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

# Kiểm tra sinh nhật (hôm nay hoặc ngày mai)
def check_birthdays(target_date, is_tomorrow=False):
    target_month_day = target_date.strftime('%m/%d')
    data = get_sheet_data()
    birthdays = []

    for row in data[1:]:
        if not row:
            continue
        name = row[0]
        solar_date = row[1] if len(row) > 1 else ''
        lunar_prev = row[3] if len(row) > 3 else ''
        lunar_curr = row[4] if len(row) > 4 else ''
        lunar_date = row[2] if len(row) > 2 else ''

        # Sinh nhật dương lịch
        if solar_date:
            try:
                if datetime.strptime(solar_date.strip(), '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    msg = (
                        f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                        f"Theo ngày dương: {solar_date}"
                    )
                    birthdays.append((msg, name))
            except ValueError:
                pass

        # Sinh nhật âm lịch năm trước
        if lunar_prev and lunar_date:
            try:
                if datetime.strptime(lunar_prev.strip(), '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    parts = lunar_date.strip().split('/')
                    day_month = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ''
                    msg = (
                        f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                        f"Theo ngày âm: ({lunar_date} - {day_month}/{target_date.year - 1})"
                    )
                    birthdays.append((msg, name))
            except ValueError:
                pass

        # Sinh nhật âm lịch năm nay
        if lunar_curr and lunar_date:
            try:
                if datetime.strptime(lunar_curr.strip(), '%d/%m/%Y').strftime('%m/%d') == target_month_day:
                    parts = lunar_date.strip().split('/')
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

    for i in range(3):  # 0: hôm nay, 1: ngày mai, 2: ngày kia
        check_date = today + timedelta(days=i)
        lunar_day, lunar_month, _ = convert_solar_to_lunar(check_date)

        if lunar_day in [1, 15]:
            if lunar_day == 1:
                event = "mùng 1"
            else:
                event = "rằm"

            if i == 0:
                day_word = "Hôm nay"
            elif i == 1:
                day_word = "Ngày mai"
            else:
                day_word = "Ngày kia"

            message = f"*{day_word} là {event} tháng {lunar_month} âm lịch*"
            messages.append(message)
            print(f"Special day detected: {message}")

    return messages

# Hàm chính
async def main():
    print(f"Script started at {datetime.now(VN_TIMEZONE)}")

    # Cập nhật ngày âm lịch sang dương lịch trong sheet
    update_lunar_solar_dates()

    today = datetime.now(VN_TIMEZONE)
    tomorrow = today + timedelta(days=1)

    # Kiểm tra sinh nhật
    today_birthdays = check_birthdays(today, is_tomorrow=False)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    for msg, _ in today_birthdays:
        await send_telegram_message(msg)
    for msg, _ in tomorrow_birthdays:
        await send_telegram_message(msg)

    # Kiểm tra mùng 1 và rằm
    special_events = await check_mung_ram()
    for msg in special_events:
        await send_telegram_message(msg)

    if not today_birthdays and not tomorrow_birthdays and not special_events:
        print("Không có sinh nhật hoặc ngày đặc biệt (mùng 1/rằm) nào trong 3 ngày tới.")

if __name__ == '__main__':
    asyncio.run(main())

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

# Cấu hình
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
SHEET_NAME = 'Trang tính1'
RANGE_NAME = f'{SHEET_NAME}!A:E'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

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
        print(f"Sheet data: {data}")
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
        print(f"Updated sheet with data: {values}")
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        raise

# Gửi thông báo Telegram
async def send_telegram_message(message):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.MARKDOWN)
        print(f"Sent Telegram message: {message}")
    except BadRequest as e:
        print(f"Telegram error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error when sending Telegram message: {e}")
        raise

# Chuyển đổi ngày âm lịch sang dương lịch
def convert_lunar_to_solar(lunar_day, lunar_month, target_year):
    try:
        lunar = Lunar(target_year, lunar_month, lunar_day, isleap=False)
        solar = Converter.Lunar2Solar(lunar)
        solar_datetime = datetime(solar.year, solar.month, solar.day)
        print(f"Converted lunar {lunar_day}/{lunar_month}/{target_year} to solar {solar_datetime.strftime('%d/%m/%Y')}")
        return solar_datetime
    except ValueError as e:
        print(f"Error converting lunar date {lunar_day}/{lunar_month}/{target_year}: {e}")
        return None

# Cập nhật cột D (năm trước) và E (năm hiện tại)
def update_lunar_solar_dates():
    current_year = datetime.now().year
    previous_year = current_year - 1
    data = get_sheet_data()
    updated_data = data.copy()
    updated = False

    for i, row in enumerate(data[1:], start=1):  # Bỏ hàng tiêu đề
        lunar_date = row[2] if len(row) > 2 else ''
        if lunar_date:
            try:
                lunar_parts = lunar_date.strip().split('/')
                if len(lunar_parts) != 3:
                    print(f"Invalid lunar date format for row {i+1}: {lunar_date}")
                    continue
                lunar_day = int(lunar_parts[0])
                lunar_month = int(lunar_parts[1])
                # Chuyển đổi cho năm trước và năm hiện tại
                solar_prev_year = convert_lunar_to_solar(lunar_day, lunar_month, previous_year)
                solar_curr_year = convert_lunar_to_solar(lunar_day, lunar_month, current_year)
                while len(updated_data[i]) < 5:
                    updated_data[i].append('')
                prev_year_str = solar_prev_year.strftime('%d/%m/%Y') if solar_prev_year else ''
                curr_year_str = solar_curr_year.strftime('%d/%m/%Y') if solar_curr_year else ''
                if updated_data[i][3] != prev_year_str or updated_data[i][4] != curr_year_str:
                    updated_data[i][3] = prev_year_str
                    updated_data[i][4] = curr_year_str
                    updated = True
                    print(f"Updated row {i+1}: D={prev_year_str}, E={curr_year_str}")
            except (ValueError, IndexError) as e:
                print(f"Error processing lunar date for row {i+1}: {e}")
                continue

    if updated:
        update_sheet_data(updated_data)
    else:
        print("No updates needed for columns D and E")

# Kiểm tra sinh nhật
def check_birthdays(target_date, is_tomorrow=False):
    target_month_day = target_date.strftime('%m/%d')
    data = get_sheet_data()
    birthdays = []

    for i, row in enumerate(data[1:], start=1):
        name = row[0]
        solar_date = row[1] if len(row) > 1 else ''
        lunar_solar_prev = row[3] if len(row) > 3 else ''
        lunar_solar_curr = row[4] if len(row) > 4 else ''
        lunar_date = row[2] if len(row) > 2 else ''

        if solar_date:
            try:
                solar_month_day = datetime.strptime(solar_date.strip(), '%d/%m/%Y').strftime('%m/%d')
                if solar_month_day == target_month_day:
                    message = (
                        f"{'Ngày mai ' if is_tomorrow else 'Hôm nay '}"
                        f"sinh nhật {name} "                        
                        f"Theo ngày dương: {solar_date}"
                    )
                    birthdays.append((message, name))
                    print(f"Found solar birthday for {name}: {solar_date}")
            except ValueError:
                print(f"Invalid solar date format for row {i+1}: {solar_date}")
                pass

        if lunar_solar_prev and lunar_date:
            try:
                lunar_solar_month_day = datetime.strptime(lunar_solar_prev.strip(), '%d/%m/%Y').strftime('%m/%d')
                if lunar_solar_month_day == target_month_day:
                    lunar_parts = lunar_date.strip().split('/')
                    lunar_day_month = f"{lunar_parts[0]}/{lunar_parts[1]}" if len(lunar_parts) >= 2 else 'Unknown'
                    message = (
                        f"{'Ngày mai ' if is_tomorrow else 'Hôm nay '}"
                        f"sinh nhật {name} "                        
                        f"theo ngày âm:\n({lunar_date} - {lunar_day_month}/{target_date.year - 1})"
                    )
                    birthdays.append((message, name))
                    print(f"Found lunar birthday for {name}: {lunar_date} -> {lunar_solar_prev}")
            except ValueError:
                print(f"Invalid lunar solar date (prev year) for row {i+1}: {lunar_solar_prev}")
                pass

        if lunar_solar_curr and lunar_date:
            try:
                lunar_solar_month_day = datetime.strptime(lunar_solar_curr.strip(), '%d/%m/%Y').strftime('%m/%d')
                if lunar_solar_month_day == target_month_day:
                    lunar_parts = lunar_date.strip().split('/')
                    lunar_day_month = f"{lunar_parts[0]}/{lunar_parts[1]}" if len(lunar_parts) >= 2 else 'Unknown'
                    message = (
                        f"{'Ngày mai ' if is_tomorrow else 'Hôm nay '}"
                        f"sinh nhật {name} "                        
                        f"theo ngày âm:\n({lunar_date} - {lunar_day_month}/{target_date.year - 1})"
                    )
                    birthdays.append((message, name))
                    print(f"Found lunar birthday for {name}: {lunar_date} -> {lunar_solar_curr}")
            except ValueError:
                print(f"Invalid lunar solar date (curr year) for row {i+1}: {lunar_solar_curr}")
                pass

    return birthdays

# Hàm chính
async def main():
    update_lunar_solar_dates()

    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    
    today_birthdays = check_birthdays(today)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    # Tạo header
    message_parts = []
    if today_birthdays:
        today_names = [name for _, name in today_birthdays]
        message_parts.append(f"{', '.join(today_names)} sinh nhật hôm nay:")
    if tomorrow_birthdays:
        tomorrow_names = [name for _, name in tomorrow_birthdays]
        message_parts.append(f"{', '.join(tomorrow_names)} sinh nhật ngày mai:")

    # Thêm body
    if today_birthdays or tomorrow_birthdays:
        if message_parts:
            message_parts.append("")  # Dòng trống giữa header và body
        for message, _ in today_birthdays:
            message_parts.append(message)
        for message, _ in tomorrow_birthdays:
            message_parts.append(message)

        # Gộp thành một tin nhắn
        message = "\n\n".join(message_parts)
        await send_telegram_message(message)
    else:
        print("Không có sinh nhật hôm nay hoặc ngày mai.")

if __name__ == '__main__':
    asyncio.run(main())

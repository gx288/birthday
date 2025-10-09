import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import json
import asyncio
from lunarcalendar import Converter, Solar, Lunar

# Cấu hình
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
SHEET_NAME = 'Trang tính1'  # Tên sheet chính xác
RANGE_NAME = f'{SHEET_NAME}!A:D'  # Cột A:D (Họ tên, Dương lịch, Âm lịch, Dương lịch từ âm lịch)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Đọc Google Sheet
def get_sheet_data():
    creds_json = os.getenv('GOOGLE_CREDENTIALS')
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict)
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SHEET_ID, range=RANGE_NAME).execute()
    return result.get('values', [])

# Ghi dữ liệu vào Google Sheet
def update_sheet_data(values):
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

# Gửi thông báo Telegram
async def send_telegram_message(message):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.MARKDOWN)

# Chuyển đổi ngày âm lịch sang dương lịch
def convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, target_year):
    try:
        lunar = Lunar(lunar_year, lunar_month, lunar_day, isleap=False)
        solar = Converter.Lunar2Solar(lunar)
        # Chuyển Solar thành datetime
        solar_datetime = datetime(solar.year, solar.month, solar.day)
        # Thay năm bằng target_year
        solar_datetime = solar_datetime.replace(year=target_year)
        return solar_datetime
    except ValueError:
        return None

# Cập nhật cột Dương lịch từ âm lịch
def update_lunar_solar_dates():
    current_year = datetime.now().year
    data = get_sheet_data()
    updated_data = data.copy()

    for i, row in enumerate(data[1:], start=1):  # Bỏ hàng tiêu đề
        lunar_date = row[2] if len(row) > 2 else ''
        if lunar_date:
            try:
                lunar_parts = lunar_date.split('/')
                lunar_day = int(lunar_parts[0])
                lunar_month = int(lunar_parts[1])
                lunar_year = int(lunar_parts[2])
                solar_from_lunar = convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, current_year)
                if solar_from_lunar:
                    solar_date_str = solar_from_lunar.strftime('%d/%m/%Y')
                    while len(updated_data[i]) < 4:
                        updated_data[i].append('')
                    updated_data[i][3] = solar_date_str
            except (ValueError, IndexError):
                pass

    if updated_data != data:
        update_sheet_data(updated_data)

# Kiểm tra sinh nhật
def check_birthdays(target_date, is_tomorrow=False):
    target_month_day = target_date.strftime('%m/%d')
    data = get_sheet_data()
    birthdays = []

    for row in data[1:]:
        name = row[0]
        solar_date = row[1] if len(row) > 1 else ''
        lunar_solar_date = row[3] if len(row) > 3 else ''

        if solar_date:
            try:
                solar_month_day = datetime.strptime(solar_date, '%d/%m/%Y').strftime('%m/%d')
                if solar_month_day == target_month_day:
                    birthdays.append(f"{name} (Dương lịch: {solar_date})")
            except ValueError:
                pass

        if lunar_solar_date:
            try:
                lunar_solar_month_day = datetime.strptime(lunar_solar_date, '%d/%m/%Y').strftime('%m/%d')
                if lunar_solar_month_day == target_month_day:
                    birthdays.append(f"{name} (Âm lịch: {row[2]})")
            except ValueError:
                pass

    return birthdays

# Hàm chính
async def main():
    update_lunar_solar_dates()

    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    
    today_birthdays = check_birthdays(today)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    messages = []
    if today_birthdays:
        messages.append(f"🎉 **Hôm nay ({today.strftime('%d/%m/%Y')}) là sinh nhật của**:\n{'\n'.join(today_birthdays)}")
    if tomorrow_birthdays:
        messages.append(f"📅 **Ngày mai ({tomorrow.strftime('%d/%m/%Y')}) là sinh nhật của**:\n{'\n'.join(tomorrow_birthdays)}")
    
    if messages:
        message = "\n\n".join(messages)
        await send_telegram_message(message)
    else:
        print("Không có sinh nhật hôm nay hoặc ngày mai.")

if __name__ == '__main__':
    asyncio.run(main())

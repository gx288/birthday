import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import telegram
from datetime import datetime
import json
import asyncio
from lunarcalendar import Converter, Solar, Lunar

# Cấu hình
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
RANGE_NAME = 'Sheet1!A:C'  # Cột A:C (Họ tên, Dương lịch, Âm lịch)
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

# Gửi thông báo Telegram
async def send_telegram_message(message):
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')

# Chuyển đổi ngày âm lịch sang dương lịch cho năm hiện tại
def convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, current_year):
    try:
        lunar = Lunar(lunar_year, lunar_month, lunar_day, isleap=False)  # Giả định không phải năm nhuận
        solar = Converter.Lunar2Solar(lunar)
        # Thay năm bằng năm hiện tại
        solar_current_year = Solar(current_year, solar.month, solar.day)
        return solar_current_year
    except ValueError:
        return None

# Hàm chính
def main():
    today = datetime.now()
    today_month_day = today.strftime('%m/%d')
    current_year = today.year  # Lấy năm hiện tại (ví dụ: 2025)
    data = get_sheet_data()
    birthdays = []

    # Bỏ hàng tiêu đề
    for row in data[1:]:
        name = row[0]
        solar_date = row[1] if len(row) > 1 else ''
        lunar_date = row[2] if len(row) > 2 else ''

        # Kiểm tra sinh nhật dương lịch
        if solar_date:
            try:
                solar_month_day = datetime.strptime(solar_date, '%d/%m/%Y').strftime('%m/%d')
                if solar_month_day == today_month_day:
                    birthdays.append(f"{name} (Dương lịch: {solar_date})")
            except ValueError:
                pass

        # Kiểm tra sinh nhật âm lịch
        if lunar_date:
            try:
                # Giả sử định dạng âm lịch: dd/mm/yyyy
                lunar_parts = lunar_date.split('/')
                lunar_day = int(lunar_parts[0])
                lunar_month = int(lunar_parts[1])
                lunar_year = int(lunar_parts[2])  # Năm sinh âm lịch
                # Chuyển sang dương lịch cho năm hiện tại
                solar_from_lunar = convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, current_year)
                if solar_from_lunar and solar_from_lunar.strftime('%m/%d') == today_month_day:
                    birthdays.append(f"{name} (Âm lịch: {lunar_date})")
            except (ValueError, IndexError):
                pass

    # Gửi thông báo nếu có sinh nhật
    if birthdays:
        message = f"🎉 Hôm nay là sinh nhật của:\n{'\n'.join(birthdays)}"
        asyncio.run(send_telegram_message(message))
    else:
        print("Không có sinh nhật hôm nay.")

if __name__ == '__main__':
    main()

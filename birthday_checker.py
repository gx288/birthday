import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import telegram
from datetime import datetime, timedelta
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

# Chuyển đổi ngày âm lịch sang dương lịch cho năm cụ thể
def convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, target_year):
    try:
        lunar = Lunar(lunar_year, lunar_month, lunar_day, isleap=False)  # Giả định không phải năm nhuận
        solar = Converter.Lunar2Solar(lunar)
        solar_target_year = Solar(target_year, solar.month, solar.day)
        return solar_target_year
    except ValueError:
        return None

# Kiểm tra sinh nhật
def check_birthdays(target_date, is_tomorrow=False):
    target_month_day = target_date.strftime('%m/%d')
    current_year = target_date.year
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
                if solar_month_day == target_month_day:
                    birthdays.append(f"{name} (Dương lịch: {solar_date})")
            except ValueError:
                pass

        # Kiểm tra sinh nhật âm lịch
        if lunar_date:
            try:
                lunar_parts = lunar_date.split('/')
                lunar_day = int(lunar_parts[0])
                lunar_month = int(lunar_parts[1])
                lunar_year = int(lunar_parts[2])
                solar_from_lunar = convert_lunar_to_solar(lunar_day, lunar_month, lunar_year, current_year)
                if solar_from_lunar and solar_from_lunar.strftime('%m/%d') == target_month_day:
                    birthdays.append(f"{name} (Âm lịch: {lunar_date})")
            except (ValueError, IndexError):
                pass

    return birthdays

# Hàm chính
async def main():
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    
    # Kiểm tra sinh nhật hôm nay
    today_birthdays = check_birthdays(today)
    # Kiểm tra sinh nhật ngày mai
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    # Tạo thông báo
    messages = []
    if today_birthdays:
        messages.append(f"🎉 **Hôm nay ({today.strftime('%d/%m/%Y')}) là sinh nhật của**:\n{'\n'.join(today_birthdays)}")
    if tomorrow_birthdays:
        messages.append(f"📅 **Ngày mai ({tomorrow.strftime('%d/%m/%Y')}) là sinh nhật của**:\n{'\n'.join(tomorrow_birthdays)}")
    
    # Gửi thông báo nếu có sinh nhật
    if messages:
        message = "\n\n".join(messages)
        await send_telegram_message(message)
    else:
        print("Không có sinh nhật hôm nay hoặc ngày mai.")

if __name__ == '__main__':
    asyncio.run(main())

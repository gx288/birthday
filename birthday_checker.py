import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import json
import asyncio
from lunarcalendar import Converter, Solar, Lunar
import pytz

# ────────────────────────────────────────────────
# CẤU HÌNH
# ────────────────────────────────────────────────
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
SHEET_NAME = 'Trang tính1'
RANGE_NAME = f'{SHEET_NAME}!A:E'

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')

def get_sheet_data():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
        service = build('sheets', 'v4', credentials=creds)
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=RANGE_NAME).execute()
        return result.get('values', [])
    except Exception as e:
        print(f"❌ Lỗi Sheet: {e}")
        return []

def convert_solar_to_lunar(solar_date):
    try:
        solar = Solar(solar_date.year, solar_date.month, solar_date.day)
        lunar = Converter.Solar2Lunar(solar)
        return lunar.day, lunar.month, lunar.isleap
    except: return None, None, None

# ────────────────────────────────────────────────
# HÀM CHECK TỔNG HỢP (ÂM + DƯƠNG)
# ────────────────────────────────────────────────
def check_birthdays_combined(target_date, is_tomorrow=False):
    # 1. Lấy thông số ngày mục tiêu (Dương lịch)
    d_solar = target_date.day
    m_solar = target_date.month
    
    # 2. Lấy thông số ngày mục tiêu (Âm lịch)
    d_lunar, m_lunar, is_leap = convert_solar_to_lunar(target_date)
    
    label = "NGÀY MAI" if is_tomorrow else "HÔM NAY"
    print(f"\n--- 🔍 DEBUG CHECK {label} ({target_date.strftime('%d/%m/%Y')}) ---")
    print(f"☀️ Mục tiêu Dương: {d_solar}/{m_solar}")
    print(f"🌙 Mục tiêu Âm  : {d_lunar}/{m_lunar} (Nhuận: {is_leap})")

    data = get_sheet_data()
    if not data: return []
    
    birthdays = []
    
    # Giả sử: Cột A: Tên, Cột B: Ngày Dương (dd/mm/yyyy), Cột C: Ngày Âm (dd/mm)
    for i, row in enumerate(data[1:], start=2):
        if len(row) < 3: continue
        
        name = row[0].strip()
        solar_birth_raw = row[1].strip() if len(row) > 1 else "" # Cột B
        lunar_birth_raw = row[2].strip().lower()                # Cột C
        
        is_match = False
        match_type = ""

        # --- KIỂM TRA NGÀY DƯƠNG (Cột B) ---
        if solar_birth_raw:
            try:
                # Thử parse dd/mm/yyyy hoặc dd/mm
                s_parts = solar_birth_raw.split('/')
                sd = int(s_parts[0])
                sm = int(s_parts[1])
                if sd == d_solar and sm == m_solar:
                    is_match = True
                    match_type = "Dương lịch"
            except: pass

        # --- KIỂM TRA NGÀY ÂM (Cột C) ---
        if lunar_birth_raw and not is_match:
            try:
                is_leap_sheet = "nhuận" in lunar_birth_raw
                clean_lunar = lunar_birth_raw.replace("nhuận", "").strip()
                l_parts = clean_lunar.split('/')
                ld = int(l_parts[0])
                lm = int(l_parts[1])
                if ld == d_lunar and lm == m_lunar and is_leap_sheet == is_leap:
                    is_match = True
                    match_type = "Âm lịch"
            except: pass

        if is_match:
            print(f"  ✅ Khớp {name} ({match_type})")
            msg = (f"🎂 **SINH NHẬT {label}**\n"
                   f"👤 Nhân vật: **{name}**\n"
                   f"🎉 Chúc mừng sinh nhật theo **{match_type}**!")
            birthdays.append(msg)
            
    print(f"📊 Hoàn tất quét. Tìm thấy: {len(birthdays)}")
    return birthdays

async def main():
    now = datetime.now(VN_TIMEZONE)
    # now = datetime(2026, 2, 14, tzinfo=VN_TIMEZONE) # Có thể set cứng để test
    
    # Check hôm nay và ngày mai
    results = check_birthdays_combined(now, False) + check_birthdays_combined(now + timedelta(days=1), True)
    
    if results:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        for m in results:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=m, parse_mode=ParseMode.MARKDOWN)
            print("➡️ Đã gửi Telegram.")
    else:
        print("\nℹ️ Không có sinh nhật nào trong hôm nay/mai.")

if __name__ == '__main__':
    asyncio.run(main())

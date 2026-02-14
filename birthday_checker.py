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

# ────────────────────────────────────────────────
# CẤU HÌNH
# ────────────────────────────────────────────────
SHEET_ID = '1nWnCXcKhFh1uRgkcs_qEQCGbZkTdyxL_WD8laSi6kok'
SHEET_NAME = 'Trang tính1'
RANGE_NAME = f'{SHEET_NAME}!A:E'

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_CHAT_ID_SPECIAL = os.getenv('TELEGRAM_CHAT_ID_SPECIAL')

VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')

# ────────────────────────────────────────────────
# ĐỌC Google Sheet
# ────────────────────────────────────────────────
def get_sheet_data():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SHEET_ID, range=RANGE_NAME).execute()
        data = result.get('values', [])
        print(f"✅ Đã tải {len(data)} dòng từ Sheet.")
        return data
    except Exception as e:
        print(f"❌ Lỗi đọc Sheet: {e}")
        return []

# ────────────────────────────────────────────────
# GHI Google Sheet
# ────────────────────────────────────────────────
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
        print("✅ Đã cập nhật ngày dương lịch vào Sheet.")
    except Exception as e:
        print(f"❌ Lỗi ghi Sheet: {e}")

# ────────────────────────────────────────────────
# GỬI TIN NHẮN TELEGRAM
# ────────────────────────────────────────────────
async def send_telegram_message(message, extra_chat_ids=None):
    chat_ids = [TELEGRAM_CHAT_ID]
    if extra_chat_ids:
        if isinstance(extra_chat_ids, str):
            chat_ids.append(extra_chat_ids)
        else:
            chat_ids.extend(extra_chat_ids)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    for chat_id in set(chat_ids):
        if not chat_id: continue
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
            print(f"➡️ Gửi đến {chat_id} thành công.")
        except Exception as e:
            print(f"⚠️ Lỗi gửi Telegram ({chat_id}): {e}")
            # Thử gửi lại không dùng Markdown nếu lỗi format
            try:
                await bot.send_message(chat_id=chat_id, text=message)
            except: pass

# ────────────────────────────────────────────────
# CHUYỂN ĐỔI LỊCH
# ────────────────────────────────────────────────
def convert_lunar_to_solar(l_day, l_month, target_year, is_leap=False):
    try:
        lunar = Lunar(target_year, l_month, l_day, isleap=is_leap)
        solar = Converter.Lunar2Solar(lunar)
        return datetime(solar.year, solar.month, solar.day)
    except: return None

def convert_solar_to_lunar(solar_date):
    try:
        solar = Solar(solar_date.year, solar_date.month, solar_date.day)
        lunar = Converter.Solar2Lunar(solar)
        return lunar.day, lunar.month, lunar.isleap
    except: return None, None, None

# ────────────────────────────────────────────────
# KIỂM TRA SINH NHẬT
# ────────────────────────────────────────────────
def check_birthdays(target_date, is_tomorrow=False):
    l_day, l_month, is_leap = convert_solar_to_lunar(target_date)
    if l_day is None: return []

    print(f"🔍 Kiểm tra SN cho ngày âm: {l_day}/{l_month} (Nhuận: {is_leap})")
    
    data = get_sheet_data()
    if not data: return []
    
    birthdays = []
    for row in data[1:]:
        if len(row) < 3 or not row[2].strip(): continue
        
        name = row[0].strip()
        raw_lunar_sheet = row[2].strip().lower()
        
        # Xử lý Logic tháng nhuận
        is_leap_sheet = "nhuận" in raw_lunar_sheet
        clean_date_str = raw_lunar_sheet.replace("nhuận", "").strip()
        
        try:
            # Chuyển "05/01" thành [5, 1] để so sánh số nguyên
            parts = clean_date_str.split('/')
            d_sheet = int(parts[0])
            m_sheet = int(parts[1])
            
            if d_sheet == l_day and m_sheet == l_month and is_leap_sheet == is_leap:
                solar_str = target_date.strftime('%d/%m/%Y')
                status = "ngày mai" if is_tomorrow else "hôm nay"
                msg = (
                    f"🎂 **SINH NHẬT {status.upper()}**\n"
                    f"👤 Họ tên: **{name}**\n"
                    f"📅 Âm lịch: {d_sheet}/{m_sheet}{' (nhuận)' if is_leap else ''}\n"
                    f"☀️ Dương lịch: {solar_str}"
                )
                birthdays.append(msg)
        except: continue
        
    return birthdays

# ────────────────────────────────────────────────
# KIỂM TRA NGÀY LỄ / DỌN DẸP
# ────────────────────────────────────────────────
async def check_special_days():
    today = datetime.now(VN_TIMEZONE)
    messages = []
    
    # Check 3 ngày tới cho Mùng 1 / Rằm
    for i in range(3):
        check_date = today + timedelta(days=i)
        l_day, l_month, _ = convert_solar_to_lunar(check_date)
        if not l_day: continue
        
        prefix = "Hôm nay" if i == 0 else "Ngày mai" if i == 1 else "Ngày kia"
        
        if l_day == 1:
            messages.append(("special", f"🌟 *{prefix} là Mùng 1 tháng {l_month}*"))
        elif l_day == 15:
            messages.append(("special", f"🌕 *{prefix} là ngày Rằm tháng {l_month}*"))

    # Check dọn bàn thờ (Ngày 4 hoặc 18 âm lịch)
    l_day_now, l_month_now, _ = convert_solar_to_lunar(today)
    if l_day_now in [4, 18]:
        origin = "Mùng 1" if l_day_now == 4 else "Rằm"
        msg = (
            f"🧹 **NHẮC DỌN BÀN THỜ**\n"
            f"Hôm nay là {l_day_now}/{l_month_now} âm lịch (3 ngày sau {origin})."
        )
        messages.append(("cleaning", msg))
        
    return messages

# ────────────────────────────────────────────────
# CẬP NHẬT CỘT D & E (DƯƠNG LỊCH)
# ────────────────────────────────────────────────
def sync_solar_columns():
    now = datetime.now(VN_TIMEZONE)
    data = get_sheet_data()
    if not data: return
    
    updated_data = [row[:] for row in data]
    changed = False
    
    for i, row in enumerate(data[1:], start=1):
        if len(row) < 3 or not row[2].strip(): continue
        try:
            raw = row[2].strip().lower()
            is_leap = "nhuận" in raw
            parts = raw.replace("nhuận", "").strip().split('/')
            d, m = int(parts[0]), int(parts[1])
            
            solar_prev = convert_lunar_to_solar(d, m, now.year - 1, is_leap)
            solar_curr = convert_lunar_to_solar(d, m, now.year, is_leap)
            
            while len(updated_data[i]) < 5: updated_data[i].append("")
            
            s_prev_str = solar_prev.strftime('%d/%m/%Y') if solar_prev else ""
            s_curr_str = solar_curr.strftime('%d/%m/%Y') if solar_curr else ""
            
            if updated_data[i][3] != s_prev_str or updated_data[i][4] != s_curr_str:
                updated_data[i][3] = s_prev_str
                updated_data[i][4] = s_curr_str
                changed = True
        except: continue
        
    if changed: update_sheet_data(updated_data)

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
async def main():
    print(f"--- Script khởi chạy lúc: {datetime.now(VN_TIMEZONE)} ---")
    
    # 1. Đồng bộ dữ liệu ngày tháng lên Sheet
    sync_solar_columns()
    
    # 2. Kiểm tra sinh nhật
    today = datetime.now(VN_TIMEZONE)
    tomorrow = today + timedelta(days=1)
    
    all_bday_msgs = check_birthdays(today, False) + check_birthdays(tomorrow, True)
    for m in all_bday_msgs:
        await send_telegram_message(m)
        
    # 3. Kiểm tra ngày đặc biệt
    special_events = await check_special_days()
    for e_type, msg in special_events:
        # Gửi cả chat chính và chat phụ cho chắc chắn
        await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)

    print("--- Hoàn thành chu kỳ kiểm tra ---")

if __name__ == '__main__':
    asyncio.run(main())

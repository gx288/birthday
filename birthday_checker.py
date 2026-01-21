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
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')           # Chat chính (sinh nhật + mùng 1/rằm + dọn bàn thờ)
TELEGRAM_CHAT_ID_SPECIAL = os.getenv('TELEGRAM_CHAT_ID_SPECIAL')  # Chat phụ (thường chỉ mùng 1/rằm)

TELEGRAM_CHANNEL_EXTRA = "-1003599200231"  # Channel hard-code (nếu muốn gửi thêm, hiện tại comment ở dưới)

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
        print(f"Sheet data loaded: {len(data)} rows")
        return data
    except Exception as e:
        print(f"Error reading Google Sheet: {e}")
        raise

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
        print("Google Sheet updated successfully")
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        raise

# ────────────────────────────────────────────────
# GỬI TIN NHẮN TELEGRAM (hỗ trợ nhiều chat)
# ────────────────────────────────────────────────
async def send_telegram_message(message, extra_chat_ids=None):
    chat_ids = [TELEGRAM_CHAT_ID]
    
    if extra_chat_ids:
        if isinstance(extra_chat_ids, str):
            chat_ids.append(extra_chat_ids)
        else:
            chat_ids.extend(extra_chat_ids)
    
    # Luôn thêm channel nếu muốn (bỏ comment nếu cần)
    # chat_ids.append(TELEGRAM_CHANNEL_EXTRA)
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    for chat_id in set(chat_ids):  # tránh trùng
        if not chat_id:
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
            print(f"Sent to {chat_id}: {message[:60]}...")
        except BadRequest as e:
            print(f"Markdown error for {chat_id}, retrying plain: {e}")
            await bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")

# ────────────────────────────────────────────────
# Âm → Dương
# ────────────────────────────────────────────────
def convert_lunar_to_solar(lunar_day, lunar_month, target_year):
    try:
        lunar = Lunar(target_year, lunar_month, lunar_day, isleap=False)
        solar = Converter.Lunar2Solar(lunar)
        return datetime(solar.year, solar.month, solar.day)
    except ValueError as e:
        print(f"Error converting lunar {lunar_day}/{lunar_month}/{target_year}: {e}")
        return None

# ────────────────────────────────────────────────
# Dương → Âm
# ────────────────────────────────────────────────
def convert_solar_to_lunar(solar_date):
    try:
        solar = Solar(solar_date.year, solar_date.month, solar_date.day)
        lunar = Converter.Solar2Lunar(solar)
        return lunar.day, lunar.month, lunar.isleap
    except Exception as e:
        print(f"Error converting solar {solar_date} to lunar: {e}")
        return None, None, None

# ────────────────────────────────────────────────
# Cập nhật cột D,E (dương lịch từ âm lịch)
# ────────────────────────────────────────────────
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

# ────────────────────────────────────────────────
# Kiểm tra sinh nhật hôm nay / mai
# ────────────────────────────────────────────────
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

# ────────────────────────────────────────────────
# Kiểm tra mùng 1, rằm (báo trước tối đa 3 ngày), dọn bàn thờ (chỉ hôm nay)
# ────────────────────────────────────────────────
async def check_special_and_cleaning_days():
    today = datetime.now(VN_TIMEZONE).date()
    messages = []
    
    # ── Mùng 1 / rằm ── báo trước tối đa 3 ngày (hôm nay + mai + kia)
    for i in range(3):  # 0,1,2 → hôm nay, mai, kia
        check_date = today + timedelta(days=i)
        lunar_day, lunar_month, _ = convert_solar_to_lunar(check_date)
        
        if lunar_day is None:
            continue
            
        day_word = "Hôm nay" if i == 0 else "Ngày mai" if i == 1 else "Ngày kia"
        
        if lunar_day in [1, 15]:
            event = "mùng 1" if lunar_day == 1 else "rằm"
            message = f"*{day_word} là {event} tháng {lunar_month} âm lịch*"
            messages.append(("special", message))
    
    # ── Dọn bàn thờ ── CHỈ HÔM NAY (ngày 4 hoặc 18)
    lunar_day_today, lunar_month_today, _ = convert_solar_to_lunar(today)
    
    if lunar_day_today in [4, 18]:
        base = "mùng 1" if lunar_day_today == 4 else "rằm"
        message = (
            f"**Hôm nay {today.strftime('%d/%m/%Y')} là ngày {lunar_day_today} tháng {lunar_month_today} âm lịch**\n"
            f"→ Nhắc **dọn bàn thờ** (sau {base} 3 ngày)"
        )
        messages.append(("cleaning", message))
    
    return messages

# ────────────────────────────────────────────────
# HÀM CHÍNH
# ────────────────────────────────────────────────
async def main():
    now = datetime.now(VN_TIMEZONE)
    print(f"Script started at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    update_lunar_solar_dates()
    
    today = now
    tomorrow = today + timedelta(days=1)
    
    # 1. Sinh nhật ─ chỉ gửi chat chính
    today_birthdays = check_birthdays(today, is_tomorrow=False)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)
    
    for msg, _ in today_birthdays:
        await send_telegram_message(msg)
    for msg, _ in tomorrow_birthdays:
        await send_telegram_message(msg)
    
    # 2. Mùng 1 / rằm / dọn bàn thờ
    events = await check_special_and_cleaning_days()
    
    for event_type, msg in events:
        if event_type == "special":
            # mùng 1 & rằm ─ gửi cả chat chính + chat phụ
            await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)
        else:
            # dọn bàn thờ ─ cũng gửi tương tự
            await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)
    
    if not today_birthdays and not tomorrow_birthdays and not events:
        print("Không có sự kiện nào trong vài ngày tới.")

if __name__ == '__main__':
    asyncio.run(main())

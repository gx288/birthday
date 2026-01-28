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
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')           # Chat chính
TELEGRAM_CHAT_ID_SPECIAL = os.getenv('TELEGRAM_CHAT_ID_SPECIAL')  # Chat phụ

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
def convert_lunar_to_solar(lunar_day, lunar_month, target_year, is_leap=False):
    try:
        lunar = Lunar(target_year, lunar_month, lunar_day, isleap=is_leap)
        solar = Converter.Lunar2Solar(lunar)
        return datetime(solar.year, solar.month, solar.day)
    except ValueError as e:
        print(f"Error converting lunar {lunar_day}/{lunar_month}/{target_year} (leap={is_leap}): {e}")
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
# Cập nhật cột D,E (dương lịch từ âm lịch) - vẫn giữ để tham khảo
# ────────────────────────────────────────────────
def update_lunar_solar_dates():
    now = datetime.now(VN_TIMEZONE)
    current_year = now.year
    previous_year = current_year - 1
    data = get_sheet_data()
    updated_data = [row[:] for row in data]  # deep copy
    updated = False

    for i, row in enumerate(data[1:], start=1):
        if len(row) <= 2 or not row[2].strip():
            continue
        lunar_str = row[2].strip()
        try:
            parts = lunar_str.split('/')
            lunar_day = int(parts[0])
            lunar_month = int(parts[1])
            is_leap = False
            if len(parts) > 2 and 'nhuận' in parts[2].lower():
                is_leap = True

            # Năm trước
            solar_prev = convert_lunar_to_solar(lunar_day, lunar_month, previous_year, is_leap)
            # Năm nay
            solar_curr = convert_lunar_to_solar(lunar_day, lunar_month, current_year, is_leap)

            while len(updated_data[i]) < 5:
                updated_data[i].append('')

            prev_str = solar_prev.strftime('%d/%m/%Y') if solar_prev else ''
            curr_str = solar_curr.strftime('%d/%m/%Y') if solar_curr else ''

            if updated_data[i][3] != prev_str or updated_data[i][4] != curr_str:
                updated_data[i][3] = prev_str
                updated_data[i][4] = curr_str
                updated = True
        except Exception:
            continue

    if updated:
        update_sheet_data(updated_data)
    else:
        print("No updates needed for lunar dates")

# ────────────────────────────────────────────────
# Kiểm tra sinh nhật hôm nay / mai (sửa: so sánh âm lịch trực tiếp)
# ────────────────────────────────────────────────
def check_birthdays(target_date, is_tomorrow=False):
    lunar_day, lunar_month, is_leap = convert_solar_to_lunar(target_date)
    if lunar_day is None:
        return []

    # Chuẩn hóa dạng "ngày/tháng" (ví dụ: "22/12")
    target_lunar = f"{lunar_day}/{lunar_month}"

    data = get_sheet_data()
    birthdays = []

    for row in data[1:]:
        if len(row) < 3 or not row[2].strip():
            continue
        name = row[0].strip()
        lunar_in_sheet = row[2].strip()  # ví dụ: "22/12" hoặc "15/8 nhuận"

        # Xử lý tháng nhuận nếu sheet ghi "ngày/tháng nhuận"
        is_leap_sheet = False
        if 'nhuận' in lunar_in_sheet.lower():
            is_leap_sheet = True
            lunar_in_sheet = lunar_in_sheet.split('nhuận')[0].strip()

        if lunar_in_sheet == target_lunar and is_leap_sheet == is_leap:
            leap_text = " (nhuận)" if is_leap else ""
            solar_str = target_date.strftime('%d/%m/%Y')
            msg = (
                f"**{name} sinh nhật {'ngày mai' if is_tomorrow else 'hôm nay'}:**\n"
                f"Theo ngày âm: {lunar_in_sheet}{leap_text} - {solar_str} dương lịch"
            )
            birthdays.append((msg, name))

    return birthdays

# ────────────────────────────────────────────────
# Kiểm tra mùng 1, rằm + dọn bàn thờ
# ────────────────────────────────────────────────
async def check_special_and_cleaning_days():
    today = datetime.now(VN_TIMEZONE).date()
    messages = []

    # Mùng 1 / rằm ─ báo trước tối đa 3 ngày
    for i in range(3):
        check_date = today + timedelta(days=i)
        lunar_day, lunar_month, _ = convert_solar_to_lunar(check_date)
        if lunar_day is None:
            continue

        day_word = "Hôm nay" if i == 0 else "Ngày mai" if i == 1 else "Ngày kia"

        if lunar_day in [1, 15]:
            event = "mùng 1" if lunar_day == 1 else "rằm"
            msg = f"*{day_word} là {event} tháng {lunar_month} âm lịch*"
            messages.append(("special", msg))

    # Dọn bàn thờ ─ chỉ hôm nay (ngày 4 hoặc 18 âm)
    lunar_day_today, lunar_month_today, _ = convert_solar_to_lunar(today)
    if lunar_day_today in [4, 18]:
        base = "mùng 1" if lunar_day_today == 4 else "rằm"
        msg = (
            f"**Hôm nay {today.strftime('%d/%m/%Y')} là ngày {lunar_day_today} tháng {lunar_month_today} âm lịch**\n"
            f"→ Nhắc **dọn bàn thờ** (sau {base} 3 ngày)"
        )
        messages.append(("cleaning", msg))

    return messages

# ────────────────────────────────────────────────
# HÀM CHÍNH
# ────────────────────────────────────────────────
async def main():
    now = datetime.now(VN_TIMEZONE)
    print(f"Script started at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Cập nhật ngày dương từ âm (tham khảo)
    update_lunar_solar_dates()

    today = now
    tomorrow = today + timedelta(days=1)

    # Sinh nhật
    today_birthdays = check_birthdays(today, is_tomorrow=False)
    tomorrow_birthdays = check_birthdays(tomorrow, is_tomorrow=True)

    for msg, _ in today_birthdays:
        await send_telegram_message(msg)
    for msg, _ in tomorrow_birthdays:
        await send_telegram_message(msg)

    # Mùng 1/rằm + dọn bàn thờ
    events = await check_special_and_cleaning_days()

    for event_type, msg in events:
        if event_type == "special":
            await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)
        else:
            await send_telegram_message(msg, extra_chat_ids=TELEGRAM_CHAT_ID_SPECIAL)

    if not today_birthdays and not tomorrow_birthdays and not events:
        print("Không có sự kiện nào trong vài ngày tới.")

if __name__ == '__main__':
    asyncio.run(main())

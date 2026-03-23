import os
import asyncio
from datetime import datetime, timedelta
import pytz
from lunarcalendar import Converter, Solar
from telegram import Bot
from telegram.constants import ParseMode

# ────────────────────────────────────────────────
# CẤU HÌNH
# ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')

def get_lunar_date(date_obj):
    """Chuyển đổi ngày Dương sang Âm lịch"""
    solar = Solar(date_obj.year, date_obj.month, date_obj.day)
    lunar = Converter.Solar2Lunar(solar)
    return lunar.day, lunar.month

def check_special_lunar_days(current_date):
    """Kiểm tra xem ngày hiện tại có rơi vào mốc báo hay không"""
    messages = []
    
    # Kiểm tra cho 3 mốc: Hôm nay, 3 ngày trước, 3 ngày sau
    # Để biết hôm nay có phải là "3 ngày trước" của Rằm hay không, 
    # ta phải xem "3 ngày nữa" có phải là Rằm không.
    
    # 1. Kiểm tra mốc "Sắp đến" (3 ngày trước)
    three_days_later = current_date + timedelta(days=3)
    d_l_later, m_l_later = get_lunar_date(three_days_later)
    if d_l_later == 1:
        messages.append(f"⏳ **SẮP ĐẾN MÙNG 1** (Còn 3 ngày nữa)\nHôm nay là cuối tháng cũ, chuẩn bị cho tháng mới {m_l_later} nhé!")
    elif d_l_later == 15:
        messages.append(f"⏳ **SẮP ĐẾN NGÀY RẰM** (Còn 3 ngày nữa)\nChuẩn bị đồ lễ cho ngày rằm tháng {m_l_later} bạn nhé!")

    # 2. Kiểm tra mốc "Chính lễ" (Hôm nay)
    d_l_now, m_l_now = get_lunar_date(current_date)
    if d_l_now == 1:
        messages.append(f"🌙 **HÔM NAY: MÙNG 1 ĐẦU THÁNG {m_l_now}**\nChúc bạn một tháng mới hanh thông, may mắn!")
    elif d_l_now == 15:
        messages.append(f"🌕 **HÔM NAY: NGÀY RẰM THÁNG {m_l_now}**\nNgày trăng tròn, chúc bạn và gia đình bình an!")

    # 3. Kiểm tra mốc "Sau lễ" (3 ngày sau)
    three_days_ago = current_date - timedelta(days=3)
    d_l_ago, m_l_ago = get_lunar_date(three_days_ago)
    if d_l_ago == 1:
        messages.append(f"✅ **ĐÃ QUA MÙNG 1 (3 ngày)**\nHy vọng khởi đầu tháng {m_l_now} của bạn đang tốt đẹp!")
    elif d_l_ago == 15:
        messages.append(f"✅ **ĐÃ QUA NGÀY RẰM (3 ngày)**\nHoàn tất kỳ rằm tháng {m_l_now}!")

    return messages

async def main():
    # Lấy thời gian hiện tại theo giờ VN
    now = datetime.now(VN_TIMEZONE)
    
    # Debug xem hôm nay là ngày mấy âm
    d_l, m_l = get_lunar_date(now)
    print(f"DEBUG: Hôm nay {now.strftime('%d/%m/%Y')} là ngày {d_l}/{m_l} Âm lịch")

    # Kiểm tra các mốc thông báo
    announcements = check_special_lunar_days(now)
    
    if announcements:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        for msg in announcements:
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID, 
                    text=msg, 
                    parse_mode=ParseMode.MARKDOWN
                )
                print(f"➡️ Đã gửi thông báo: {msg[:30]}...")
            except Exception as e:
                print(f"❌ Lỗi gửi Telegram: {e}")
    else:
        print("ℹ️ Hôm nay không phải mốc cần báo (Trước/Trong/Sau Mùng 1 & Rằm).")

if __name__ == '__main__':
    # Kiểm tra biến môi trường trước khi chạy
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Thiếu cấu hình TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong biến môi trường!")
    else:
        asyncio.run(main())

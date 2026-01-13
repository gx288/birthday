import os
import json
import time
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime

# ────────────────────────────────────────────────
#                  CẤU HÌNH
# ────────────────────────────────────────────────
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"

MAX_PAGES = 10          # Giới hạn an toàn, tránh chạy vô hạn
MAX_EMPTY_PAGES = 2     # Dừng nếu liên tục X trang không có item mới

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")

def get_telegram_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID")
    }

def setup_driver():
    log("🌐 Khởi tạo Chrome headless...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def connect_google_sheet():
    log("📂 Kết nối Google Sheets...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS", "{}"))
    if not creds_json:
        raise ValueError("Không tìm thấy biến môi trường GOOGLE_CREDENTIALS")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)

    try:
        worksheet = sh.worksheet(SHEET_NAME)
        log(f"✅ Tìm thấy sheet: {SHEET_NAME}")
    except gspread.WorksheetNotFound:
        log(f"⚠️ Tạo sheet mới: {SHEET_NAME}")
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        headers = ["Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Scraped At"]
        worksheet.append_row(headers)
    
    return worksheet

def send_telegram_alert(item):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return

    message = (
        f"🎸 <b>HÀNG MỚI - CHỢ TỐT</b>\n\n"
        f"<b>{item['title']}</b>\n"
        f"💰 <b>{item['price']}</b>\n"
        f"👤 {item['seller']}\n"
        f"👀 {item['views']} views\n"
        f"📍 {item['location']}\n"
        f"⏰ {item['time']}\n\n"
        f"<a href='{item['link']}'>🔗 Xem chi tiết</a>"
    )

    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            log(f"Telegram lỗi {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Gửi Telegram thất bại: {e}")

def is_end_of_results(driver):
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
        if any(phrase in body.lower() for phrase in ["không có kết quả", "không tìm thấy tin"]):
            return True
    except:
        pass
    return False

def scrape_data():
    log("🚀 BẮT ĐẦU SCRAPE CHỢ TỐT - Nhạc cụ Hà Nội (≤ 2.1tr)")

    worksheet = connect_google_sheet()

    # Lấy tất cả link đã có (cột C - index 3)
    try:
        existing_links = set(worksheet.col_values(3)[1:])  # Bỏ header
        log(f"📊 Đã có {len(existing_links)} tin cũ trong sheet")
    except Exception as e:
        log(f"⚠️ Không đọc được cột link: {e}")
        existing_links = set()

    driver = setup_driver()
    new_items = []               # Giữ nguyên thứ tự scrape
    page = 1
    consecutive_empty_pages = 0

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"\n📄 Trang {page} → {url}")

        try:
            driver.get(url)
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t"))
            )
        except Exception as e:
            log(f"⌛ Timeout hoặc lỗi load trang {page}: {e}")
            if is_end_of_results(driver):
                log("🛑 Phát hiện hết kết quả → dừng")
                break
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                log(f"🚫 {MAX_EMPTY_PAGES} trang liên tiếp không có dữ liệu mới → dừng")
                break
            page += 1
            time.sleep(2.5)
            continue

        if is_end_of_results(driver):
            log("🛑 Hết kết quả tìm kiếm → dừng")
            break

        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"🔍 Tìm thấy {len(items)} item trên trang")

        new_on_this_page = 0

        for idx, item in enumerate(items, 1):
            try:
                a_tag = item.find_element(By.TAG_NAME, "a")
                link = a_tag.get_attribute("href")
                if not link.startswith("http"):
                    link = BASE_URL + link.strip()

                if link in existing_links:
                    continue

                # Đánh dấu đã thấy (ngay cả khi lỗi sau vẫn tránh lặp lại)
                existing_links.add(link)

                title = item.find_element(By.CSS_SELECTOR, "h3").text.strip() or "Không có tiêu đề"

                try:
                    price = item.find_element(By.CSS_SELECTOR, "span.bfe6oav").text.strip()
                except:
                    price = "Thỏa thuận"

                try:
                    time_posted = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text.strip()
                except:
                    time_posted = "N/A"

                try:
                    location = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text.strip()
                except:
                    location = "Hà Nội"

                try:
                    seller = item.find_element(By.CSS_SELECTOR, "div.dteznpi span.brnpcl3").text.strip()
                except:
                    seller = "Ẩn danh"

                try:
                    views = item.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text.strip()
                except:
                    views = "0"

                item_data = {
                    "title": title,
                    "price": price,
                    "link": link,
                    "time": time_posted,
                    "location": location,
                    "seller": seller,
                    "views": views,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                new_items.append(item_data)
                new_on_this_page += 1

                log(f"  {idx:2d} | MỚI | {title[:60]:<60} | {price:>12} | {seller}")

                # Gửi thông báo ngay (tùy chọn – có thể comment nếu muốn gửi hàng loạt)
                send_telegram_alert(item_data)

            except Exception as e:
                # Bỏ qua item lỗi, không làm dừng cả trang
                continue

        if new_on_this_page == 0:
            consecutive_empty_pages += 1
            log("Trang này không có tin mới nào")
        else:
            consecutive_empty_pages = 0

        page += 1
        time.sleep(2.8 + (page % 3))  # Giảm nguy cơ bị chặn

    driver.quit()

    # Lưu tất cả tin mới theo thứ tự đã scrape
    if new_items:
        log(f"\n🎉 Tìm được {len(new_items)} tin mới!")

        rows = [[
            i["title"],
            i["price"],
            i["link"],
            i["time"],
            i["location"],
            i["seller"],
            i["views"],
            i["scraped_at"]
        ] for i in new_items]

        try:
            worksheet.append_rows(rows)
            log("💾 Đã lưu vào sheet thành công (theo thứ tự trên web)")
        except Exception as e:
            log(f"❌ Lỗi khi append vào sheet: {e}")
    else:
        log("💤 Không có tin mới nào.")

if __name__ == "__main__":
    try:
        scrape_data()
    except Exception as e:
        log(f"💥 LỖI CHÍNH: {e}")

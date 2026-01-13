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

MAX_PAGES = 12              # Giới hạn an toàn
MAX_CONSECUTIVE_EMPTY = 3   # Dừng nếu liên tục mấy trang không có tin mới
SLEEP_BETWEEN_PAGES = 3.0   # giây

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")

def get_telegram_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID")
    }

def setup_driver():
    log("Khởi tạo Chrome headless...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def connect_google_sheet():
    log("Kết nối Google Sheets...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json_str:
        raise ValueError("Không tìm thấy biến môi trường GOOGLE_CREDENTIALS")

    creds_json = json.loads(creds_json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)

    try:
        worksheet = sh.worksheet(SHEET_NAME)
        log(f"Tìm thấy sheet: {SHEET_NAME}")
    except gspread.WorksheetNotFound:
        log(f"Tạo sheet mới: {SHEET_NAME}")
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=1200, cols=10)
        headers = [
            "Title", "Price", "Link", "Time Posted", "Location",
            "Seller", "Views", "Scraped At", "Page"
        ]
        worksheet.append_row(headers)
        log("Đã tạo header")

    # Đảm bảo có cột Page (cột thứ 9)
    headers = worksheet.row_values(1)
    if "Page" not in headers:
        col_index = len(headers) + 1
        worksheet.update_cell(1, col_index, "Page")
        log(f"Đã thêm cột Page ở cột {col_index}")

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
        f"⏰ {item['time']}\n"
        f"Trang {item['page']}\n\n"
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
        requests.post(url, json=payload, timeout=12)
    except Exception as e:
        log(f"Telegram lỗi: {e}")

def page_has_no_results(driver):
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(x in text for x in ["không có kết quả", "không tìm thấy", "0 tin đăng"]):
            return True
    except:
        pass
    return False

def scrape_data():
    log("BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1 triệu")

    worksheet = connect_google_sheet()

    # Lấy tất cả link cũ (cột C = 3)
    try:
        existing_links = set(link for link in worksheet.col_values(3)[1:] if link.strip())
        log(f"Đã có {len(existing_links):,} tin cũ trong sheet")
    except Exception as e:
        log(f"Không đọc được cột link: {e}")
        existing_links = set()

    driver = setup_driver()
    total_new = 0
    page = 1
    consecutive_empty = 0

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")

        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t"))
            )
        except Exception as e:
            log(f"Timeout hoặc lỗi load trang {page}: {str(e)[:120]}")
            if page_has_no_results(driver):
                log("Phát hiện hết kết quả → dừng")
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                log(f"{MAX_CONSECUTIVE_EMPTY} trang liên tiếp không có dữ liệu → dừng")
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_PAGES + 0.8)
            continue

        if page_has_no_results(driver):
            log("Hết kết quả tìm kiếm → dừng")
            break

        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"Tìm thấy {len(items)} item trên trang")

        new_items_this_page = []

        for item in items:
            try:
                a = item.find_element(By.TAG_NAME, "a")
                link = a.get_attribute("href")
                if not link.startswith("http"):
                    link = BASE_URL + link.strip()

                if link in existing_links:
                    continue

                existing_links.add(link)

                title = item.find_element(By.CSS_SELECTOR, "h3").text.strip() or "Không có tiêu đề"

                try: price = item.find_element(By.CSS_SELECTOR, "span.bfe6oav").text.strip()
                except: price = "Thỏa thuận"

                try: time_posted = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text.strip()
                except: time_posted = "N/A"

                try: location = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text.strip()
                except: location = "Hà Nội"

                try: seller = item.find_element(By.CSS_SELECTOR, "div.dteznpi span.brnpcl3").text.strip()
                except: seller = "Ẩn danh"

                try: views = item.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text.strip()
                except: views = "0"

                item_data = {
                    "title": title,
                    "price": price,
                    "link": link,
                    "time": time_posted,
                    "location": location,
                    "seller": seller,
                    "views": views,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "page": page
                }

                new_items_this_page.append(item_data)

            except:
                continue

        new_count = len(new_items_this_page)
        total_new += new_count

        if new_count > 0:
            log(f"→ Trang {page}: **{new_count} tin mới**")
            consecutive_empty = 0

            # Gửi Telegram (nếu muốn gửi từng tin)
            for item in new_items_this_page:
                send_telegram_alert(item)

            # Chuẩn bị dữ liệu để append
            rows = [[
                d["title"],
                d["price"],
                d["link"],
                d["time"],
                d["location"],
                d["seller"],
                d["views"],
                d["scraped_at"],
                d["page"]
            ] for d in new_items_this_page]

            try:
                worksheet.append_rows(rows)
                log(f"Đã lưu {new_count} dòng từ trang {page}")
            except Exception as e:
                log(f"Lỗi append trang {page}: {e}")

        else:
            log(f"Trang {page}: không có tin mới")
            consecutive_empty += 1

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES + (page % 4) * 0.4)  # jitter nhẹ

    driver.quit()

    if total_new > 0:
        log(f"\nHoàn thành - Tìm được tổng cộng **{total_new}** tin mới")
    else:
        log("\nKhông tìm thấy tin mới nào trong lần quét này")

if __name__ == "__main__":
    try:
        scrape_data()
    except KeyboardInterrupt:
        log("Dừng bởi người dùng")
    except Exception as e:
        log(f"LỖI CHƯƠNG TRÌNH: {e}")

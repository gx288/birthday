# scrape_chotot.py - Full code with batch update to avoid 429 Quota Exceeded
# Updated: Batch update Views & Hidden using worksheet.batch_update()
# Only append new items, update existing ones (Views + Hidden)

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

MAX_PAGES = 12
MAX_CONSECUTIVE_EMPTY = 3
SLEEP_BETWEEN_PAGES = 4.0  # Tăng để an toàn hơn với quota

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
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=10)
        headers = [
            "Title", "Price", "Link", "Time Posted", "Location",
            "Seller", "Views", "Scraped At", "Hidden"
        ]
        worksheet.append_row(headers)
        log("Đã tạo sheet & header đầy đủ")
        return worksheet

    # Đảm bảo có đủ cột (ít nhất 9)
    if worksheet.col_count < 9:
        log(f"Mở rộng sheet lên 10 cột")
        worksheet.resize(cols=10)

    # Đảm bảo cột cuối là "Hidden"
    headers = worksheet.row_values(1)
    if len(headers) < 9 or headers[8] != "Hidden":
        if "Hidden" in headers:
            col_idx = headers.index("Hidden") + 1
        elif "Page" in headers:
            col_idx = headers.index("Page") + 1
            worksheet.update_cell(1, col_idx, "Hidden")
            log(f"Đổi 'Page' → 'Hidden' ở cột {chr(64 + col_idx)}")
        else:
            col_idx = len(headers) + 1
            worksheet.update_cell(1, col_idx, "Hidden")
            log(f"Thêm cột 'Hidden' ở cột {chr(64 + col_idx)}")

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

    try:
        requests.post(
            f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        log(f"Đã gửi Telegram: {item['title'][:50]}...")
    except Exception as e:
        log(f"Telegram gửi lỗi: {e}")

def page_has_no_results(driver):
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(phrase in text for phrase in ["không có kết quả", "không tìm thấy", "0 tin đăng"]):
            return True
    except:
        pass
    return False

def extract_item_data(item_element, page_num):
    try:
        link_el = item_element.find_element(By.TAG_NAME, "a")
        link = link_el.get_attribute("href")
        if not link.startswith("http"):
            link = BASE_URL + link.strip()

        title = item_element.find_element(By.CSS_SELECTOR, "h3").text.strip() or "Không có tiêu đề"

        price = "Thỏa thuận"
        try:
            price = item_element.find_element(By.CSS_SELECTOR, "span.bfe6oav").text.strip()
        except:
            pass

        time_posted = "N/A"
        try:
            time_posted = item_element.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text.strip()
        except:
            pass

        location = "Hà Nội"
        try:
            location = item_element.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text.strip()
        except:
            pass

        seller = "Ẩn danh"
        try:
            seller = item_element.find_element(By.CSS_SELECTOR, "div.dteznpi span.brnpcl3").text.strip()
        except:
            pass

        views_str = "0"
        try:
            views_str = item_element.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text.strip()
        except:
            pass
        views_clean = ''.join(c for c in views_str if c.isdigit())
        views = int(views_clean) if views_clean else 0

        return {
            "title": title,
            "price": price,
            "link": link,
            "time": time_posted,
            "location": location,
            "seller": seller,
            "views": views,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "page": page_num
        }
    except:
        return None

def scrape_data():
    log("BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1 triệu")

    worksheet = connect_google_sheet()

    # Đọc toàn bộ cột Link để map link → row number
    try:
        link_col = worksheet.col_values(3)  # cột C = Link
        link_to_row = {}
        for row_idx, link_val in enumerate(link_col, start=1):
            cleaned = link_val.strip()
            if cleaned and row_idx > 1:  # bỏ header
                link_to_row[cleaned] = row_idx
        existing_links = set(link_to_row.keys())
        log(f"Đọc được {len(existing_links):,} tin cũ từ sheet")
    except Exception as e:
        log(f"Lỗi khi đọc cột Link: {e}")
        link_to_row = {}
        existing_links = set()

    driver = setup_driver()
    total_new = 0
    total_updated = 0
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
            log(f"Load trang {page} lỗi: {str(e)[:120]}")
            if page_has_no_results(driver):
                log("Hết kết quả → dừng")
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                log(f"{MAX_CONSECUTIVE_EMPTY} trang liên tục không có dữ liệu mới → dừng")
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_PAGES)
            continue

        if page_has_no_results(driver):
            log("Hết kết quả tìm kiếm → dừng")
            break

        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"Tìm thấy {len(items)} mục trên trang")

        new_rows = []
        batch_update_requests = []  # cho batch_update

        for item_el in items:
            data = extract_item_data(item_el, page)
            if not data:
                continue

            link = data["link"]

            if link in link_to_row:
                # Tin cũ → chuẩn bị batch update
                row_num = link_to_row[link]
                # Views (cột G = 7)
                batch_update_requests.append({
                    "range": f"G{row_num}",
                    "values": [[str(data["views"])]]
                })
                # Hidden (cột I = 9)
                batch_update_requests.append({
                    "range": f"I{row_num}",
                    "values": [[str(data["page"])]]
                })
                total_updated += 1
            else:
                # Tin mới → append
                existing_links.add(link)
                link_to_row[link] = -1  # placeholder
                new_rows.append([
                    data["title"],
                    data["price"],
                    data["link"],
                    data["time"],
                    data["location"],
                    data["seller"],
                    str(data["views"]),
                    data["scraped_at"],
                    str(data["page"])
                ])
                total_new += 1
                send_telegram_alert(data)

        # 1. Append tin mới (một request)
        if new_rows:
            try:
                worksheet.append_rows(new_rows)
                log(f"Đã thêm {len(new_rows)} tin mới từ trang {page}")
            except Exception as e:
                log(f"Lỗi append: {e}")

        # 2. Batch update tất cả views + hidden (chỉ 1 request!)
        if batch_update_requests:
            try:
                worksheet.batch_update(batch_update_requests)
                log(f"Batch-update {len(batch_update_requests)} ô (views + hidden) cho {len(batch_update_requests)//2} tin cũ từ trang {page}")
            except Exception as e:
                log(f"Lỗi batch update trang {page}: {e}")

        if not new_rows and not batch_update_requests:
            consecutive_empty += 1
            log(f"Trang {page}: không có thay đổi")
        else:
            consecutive_empty = 0

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()

    log(f"\nHoàn thành:")
    log(f"  - Tin mới thêm: {total_new}")
    log(f"  - Tin cũ cập nhật (views + hidden): {total_updated}")

if __name__ == "__main__":
    try:
        scrape_data()
    except KeyboardInterrupt:
        log("Dừng bởi người dùng")
    except Exception as e:
        log(f"LỖI CHƯƠNG TRÌNH: {e}")

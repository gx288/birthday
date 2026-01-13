import os
import json
import time
import requests
import gspread
import random
import re
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────
# CẤU HÌNH
# ────────────────────────────────────────────────
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"
MAX_PAGES = 12
MAX_CONSECUTIVE_EMPTY = 3
SLEEP_BETWEEN_PAGES = 4.5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

HEADERS = ["STT", "Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Hidden"]

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
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    driver = webdriver.Chrome(options=options)
    return driver

def connect_google_sheet():
    log("Kết nối Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json_str:
        raise ValueError("Không tìm thấy GOOGLE_CREDENTIALS")
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json_str), scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    
    try:
        worksheet = sh.worksheet(SHEET_NAME)
        log(f"Tìm thấy sheet: {SHEET_NAME}")
    except gspread.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=10)
        worksheet.append_row(HEADERS)
        log("Tạo sheet & header mới")

    # Đảm bảo header đúng và đủ cột
    current_headers = worksheet.row_values(1)
    if current_headers != HEADERS:
        worksheet.update("A1:I1", [HEADERS])
        log("Đã cập nhật header chuẩn")

    if worksheet.col_count < len(HEADERS):
        worksheet.resize(cols=len(HEADERS))

    return worksheet

def get_images_from_detail(link):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        resp = requests.get(link, headers=headers, timeout=12)
        if resp.status_code != 200:
            log(f"Detail {link} status {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        images = set()

        # JSON-LD
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
                if isinstance(data, dict) and "image" in data:
                    img_val = data["image"]
                    if isinstance(img_val, str) and "cdn.chotot.com" in img_val:
                        images.add(img_val)
                    elif isinstance(img_val, list):
                        images.update([i for i in img_val if isinstance(i, str) and "cdn.chotot.com" in i])
            except:
                pass

        # Regex trong script
        for script in soup.find_all("script"):
            text = script.string or ""
            if "cdn.chotot.com" in text:
                matches = re.findall(r'(https?://cdn\.chotot\.com/[^"\')\s]+?\.(?:jpg|jpeg|png|webp))', text)
                for m in matches:
                    if re.search(r'-\d{15,}\.(jpg|jpeg|png|webp)$', m):
                        images.add(m)

        real_images = sorted(list(images))[:6]
        log(f"Lấy {len(real_images)} ảnh từ detail {link}")
        return real_images
    except Exception as e:
        log(f"Lỗi lấy ảnh {link}: {e}")
        return []

def send_telegram_with_media(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return
    
    caption = (
        f"🎸 <b>HÀNG MỚI - CHỢ TỐT</b>\n\n"
        f"<b>{item['title']}</b>\n"
        f"💰 <b>{item['price']}</b>\n"
        f"👤 {item['seller']}\n"
        f"👀 {item['views']} views\n"
        f"📍 {item['location']}\n"
        f"⏰ {item['time']}\n\n"
        f"<a href='{item['link']}'>🔗 Xem chi tiết</a>"
    )

    media_group = []
    for idx, img_url in enumerate(images):
        media_group.append({
            "type": "photo",
            "media": img_url,
            "caption": caption if idx == 0 else "",
            "parse_mode": "HTML"
        })

    if media_group:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup"
        payload = {"chat_id": cfg["chat_id"], "media": json.dumps(media_group)}
        try:
            requests.post(url, data=payload, timeout=20)
            log(f"Đã gửi album {len(images)} ảnh cho tin mới: {item['title']}")
        except Exception as e:
            log(f"Lỗi gửi media group: {e}")
    else:
        send_telegram_alert(item)

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
    requests.post(
        f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
        json={"chat_id": cfg["chat_id"], "text": message, "parse_mode": "HTML"},
        timeout=10
    )

def page_has_no_results(driver):
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
        return any(x in text for x in ["không có kết quả", "không tìm thấy", "0 tin đăng"])
    except:
        return False

def extract_item_data(item_element, page_num):
    try:
        a = item_element.find_element(By.TAG_NAME, "a")
        link = a.get_attribute("href")
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
        views = int(''.join(c for c in views_str if c.isdigit())) if ''.join(c for c in views_str if c.isdigit()) else 0

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
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1tr")
    worksheet = connect_google_sheet()

    # Đọc dữ liệu hiện tại
    try:
        all_values = worksheet.get_all_values()
        existing_data = all_values[1:] if len(all_values) > 1 else []
        
        link_info = {}
        for i, row in enumerate(existing_data, start=2):
            if len(row) >= 4 and row[3].strip():  # cột Link (D)
                link = row[3].strip()
                stt = row[0].strip() if len(row) > 0 else ""
                hidden = row[8].strip() if len(row) > 8 else ""
                link_info[link] = {"row": i, "stt": stt, "hidden": hidden}
        
        existing_links = set(link_info.keys())
        log(f"Đọc {len(existing_links)} tin cũ từ sheet")
    except Exception as e:
        log(f"Lỗi đọc sheet: {e}")
        existing_links = set()
        link_info = {}

    driver = setup_driver()
    total_new = 0
    total_updated = 0
    page = 1
    consecutive_empty = 0

    current_run_items = []  # Để sort lại sau

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")

        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t")))
        except Exception as e:
            log(f"Load trang {page} lỗi: {e}")
            if page_has_no_results(driver):
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_PAGES)
            continue

        if page_has_no_results(driver):
            break

        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"Trang {page}: Tìm thấy {len(items)} tin")

        current_page_stt = 1

        batch_updates = []
        page_new_rows = []

        for item_el in items:
            data = extract_item_data(item_el, page)
            if not data:
                continue

            link = data["link"]

            images = []
            if link not in existing_links:
                images = get_images_from_detail(link)
                send_telegram_with_media(data, images)
                total_new += 1

            row_data = [
                "",                    # STT - điền sau
                data["title"],
                data["price"],
                link,
                data["time"],
                data["location"],
                data["seller"],
                str(data["views"]),
                str(page)              # Hidden = page hiện tại nếu còn xuất hiện
            ]

            if link in existing_links:
                row_num = link_info[link]["row"]
                batch_updates.append({
                    "range": f"H{row_num}",  # Views
                    "values": [[str(data["views"])]]
                })
                batch_updates.append({
                    "range": f"I{row_num}",  # Hidden
                    "values": [[str(page)]]
                })
                total_updated += 1
            else:
                page_new_rows.append(row_data)
                existing_links.add(link)

            # Lưu để sort sau
            current_run_items.append({
                "page": page,
                "stt_on_page": current_page_stt,
                "data": row_data,
                "link": link
            })

            current_page_stt += 1

        if batch_updates:
            worksheet.batch_update(batch_updates)
            log(f"Batch update {len(batch_updates)//2} tin cũ trang {page}")

        if not page_new_rows and not batch_updates:
            consecutive_empty += 1
        else:
            consecutive_empty = 0

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()

    # ── SORT LẠI TOÀN BỘ ───────────────────────────────────────────────
    log("Bắt đầu sắp xếp lại toàn bộ sheet theo Page → STT...")

    # Sort: page tăng dần → stt_on_page tăng dần
    current_run_items.sort(key=lambda x: (x["page"], x["stt_on_page"]))

    final_rows = []
    for item in current_run_items:
        stt = len(final_rows) + 1
        row = item["data"].copy()
        row[0] = str(stt)  # Ghi STT toàn cục
        final_rows.append(row)

    # Đánh dấu Hidden cho tin cũ không còn xuất hiện
    current_links = {item["link"] for item in current_run_items}
    hidden_updates = []
    for link, info in link_info.items():
        if link not in current_links and info["hidden"] != "Hidden":
            hidden_updates.append({
                "range": f"I{info['row']}",
                "values": [["Hidden"]]
            })

    if hidden_updates:
        worksheet.batch_update(hidden_updates)
        log(f"Đánh dấu Hidden cho {len(hidden_updates)} tin cũ mất đi")

    # Xóa dữ liệu cũ và ghi lại
    worksheet.clear()
    worksheet.append_row(HEADERS)
    
    if final_rows:
        worksheet.append_rows(final_rows)
        log(f"Đã ghi lại {len(final_rows)} dòng (sort Page tăng dần → STT tăng dần)")

    log(f"Hoàn thành: +{total_new} mới | ↑{total_updated} cập nhật | Tổng tin: {len(final_rows)}")

if __name__ == "__main__":
    try:
        scrape_data()
    except Exception as e:
        log(f"Lỗi chính: {e}")

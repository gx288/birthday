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
]
HEADERS = ["STT", "Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Hidden"]

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")

def clean_url(url):
    """Loại bỏ các tham số tracking sau dấu ? để so sánh link chuẩn xác"""
    return url.split('?')[0].strip()

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
    except gspread.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=10)
        worksheet.append_row(HEADERS)
    
    current_headers = worksheet.row_values(1)
    if not current_headers or current_headers[0] != "STT":
        worksheet.update("A1:I1", [HEADERS])
    return worksheet

def get_images_from_detail(link):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        resp = requests.get(link, headers=headers, timeout=12)
        if resp.status_code != 200: return []
        soup = BeautifulSoup(resp.text, "html.parser")
        images = set()
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
                if isinstance(data, dict) and "image" in data:
                    img_val = data["image"]
                    if isinstance(img_val, str): images.add(img_val)
                    elif isinstance(img_val, list): images.update(img_val)
            except: pass
        return sorted([img for img in images if "cdn.chotot.com" in img])[:6]
    except Exception as e:
        log(f"Lỗi lấy ảnh {link}: {e}")
        return []

def send_telegram_with_media(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]: return
    caption = (
        f"🎸 <b>HÀNG MỚI (TRANG 1)</b>\n\n"
        f"<b>{item['title']}</b>\n"
        f"💰 <b>{item['price']}</b>\n"
        f"👤 {item['seller']} | 👀 {item['views']} views\n"
        f"📍 {item['location']}\n"
        f"⏰ {item['time']}\n\n"
        f"<a href='{item['link']}'>🔗 Xem chi tiết</a>"
    )
    if images:
        media = [{"type": "photo", "media": img, "caption": caption if i==0 else "", "parse_mode": "HTML"} for i, img in enumerate(images)]
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup", data={"chat_id": cfg["chat_id"], "media": json.dumps(media)})
    else:
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", json={"chat_id": cfg["chat_id"], "text": caption, "parse_mode": "HTML"})

def extract_item_data(item_element, page_num):
    try:
        a = item_element.find_element(By.TAG_NAME, "a")
        link = clean_url(a.get_attribute("href"))
        title = item_element.find_element(By.CSS_SELECTOR, "h3").text.strip()
        price = item_element.find_element(By.CSS_SELECTOR, "span.bfe6oav").text.strip()
        
        # Lấy views
        try:
            v_text = item_element.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text
            views = int(''.join(filter(str.isdigit, v_text)))
        except: views = 0

        return {
            "title": title, "price": price, "link": link,
            "time": "N/A", "location": "Hà Nội", "seller": "Ẩn danh",
            "views": views, "page": page_num
        }
    except: return None

def scrape_data():
    log("🚀 BẮT ĐẦU QUÉT (Cơ chế: Chỉ báo Tele tin mới tại Trang 1)")
    worksheet = connect_google_sheet()
    
    # 1. Đọc dữ liệu cũ để so sánh
    all_values = worksheet.get_all_values()
    existing_links = set()
    existing_titles = set()
    link_to_row = {}
    
    if len(all_values) > 1:
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) >= 4:
                existing_titles.add(row[1].strip())
                existing_links.add(clean_url(row[3]))
                link_to_row[clean_url(row[3])] = i

    driver = setup_driver()
    total_new = 0
    total_updated = 0
    global_stt_counter = 1
    batch_updates = []
    new_rows = []

    for page in range(1, MAX_PAGES + 1):
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Đang quét Trang {page}...")
        driver.get(url)
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t")))
            items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        except:
            log(f"Trang {page} không có dữ liệu.")
            break

        for item_el in items:
            data = extract_item_data(item_el, page)
            if not data: continue
            
            link = data["link"]
            title = data["title"]
            current_stt = global_stt_counter
            global_stt_counter += 1

            # KIỂM TRA TRÙNG (Link HOẶC Tiêu đề)
            is_duplicate = (link in existing_links) or (title in existing_titles)

            if is_duplicate:
                # Nếu trùng Link cũ -> Cập nhật Views & STT vào Sheet (Không báo Tele)
                if link in link_to_row:
                    row_num = link_to_row[link]
                    batch_updates.append({"range": f"A{row_num}", "values": [[str(current_stt)]]})
                    batch_updates.append({"range": f"H{row_num}", "values": [[str(data['views'])]]})
                    batch_updates.append({"range": f"I{row_num}", "values": [[str(page)]]})
                total_updated += 1
            else:
                # TIN MỚI HOÀN TOÀN
                # CHỈ BÁO TELEGRAM NẾU TIN NÀY XUẤT HIỆN Ở TRANG 1
                if page == 1:
                    log(f"✨ Phát hiện tin mới tại Trang 1: {title}")
                    images = get_images_from_detail(link)
                    send_telegram_with_media(data, images)
                
                # Lưu vào danh sách để thêm vào Sheet
                new_rows.append([
                    str(current_stt), title, data["price"], link, 
                    data["time"], data["location"], data["seller"], str(data["views"]), str(page)
                ])
                existing_links.add(link)
                existing_titles.add(title)
                total_new += 1

        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()

    # Lưu dữ liệu
    if batch_updates:
        worksheet.batch_update(batch_updates)
    if new_rows:
        worksheet.append_rows(new_rows)

    # Sort lại Sheet
    log("Sắp xếp lại Sheet theo STT...")
    try:
        all_data = worksheet.get_all_values()
        header = all_data[0]
        rows = sorted(all_data[1:], key=lambda x: int(x[0]) if x[0].isdigit() else 999)
        worksheet.clear()
        worksheet.append_row(header)
        worksheet.append_rows(rows)
    except Exception as e: log(f"Lỗi sort: {e}")

    log(f"Hoàn tất! Mới: {total_new} | Cập nhật: {total_updated}")

if __name__ == "__main__":
    scrape_data()

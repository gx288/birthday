import os
import json
import time
import random
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"
MAX_PAGES = 12
SLEEP_BETWEEN_PAGES = random.uniform(6, 12)

HEADERS = ["STT", "Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Hidden", "Scan Time"]

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")

def get_telegram_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID")
    }

def setup_driver():
    log("Khởi tạo Chrome...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def scroll_to_bottom(driver):
    log("🔄 Scroll xuống cuối...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    attempts = 0
    while attempts < 15:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(3, 5))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        attempts += 1
    time.sleep(3)
    log("Hoàn tất scroll.")

def connect_google_sheet():
    log("Kết nối Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    if ws.row_values(1) != HEADERS:
        ws.update(range_name="A1", values=[HEADERS])
    return ws

def get_images_from_detail(driver, link):
    try:
        # Sử dụng Selenium để mở link chi tiết ở tab mới nhằm vượt Cloudflare
        driver.execute_script(f"window.open('{link}', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(4)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        images = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if "image" in data:
                    img = data["image"]
                    if isinstance(img, str) and "cdn.chotot.com" in img:
                        images.append(img)
                    elif isinstance(img, list):
                        images.extend([i for i in img if "cdn.chotot.com" in i])
            except:
                pass
                
        # Fallback tìm img tags nếu không có ld+json
        if not images:
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "cdn.chotot.com" in src and "ad" in src:
                    images.append(src)
                    
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return list(set(images))[:6]
    except Exception as e:
        log(f"Lỗi lấy ảnh bằng Selenium: {e}")
        try:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        return []

def send_telegram_album(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        log("Skip gửi Tele: thiếu config")
        return
        
    caption = f"🎸 <b>{item['title']}</b>\n💰 {item['price']}\n📍 {item['location']}\n🔗 <a href='{item['link']}'>Xem chi tiết</a>"
    
    if not images:
        # Nếu vẫn không có ảnh, gửi tin nhắn text thường
        try:
            requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", json={"chat_id": cfg["chat_id"], "text": caption, "parse_mode": "HTML", "disable_web_page_preview": False})
            log(f"Đã gửi TEXT message cho tin: {item['title']}")
        except Exception as e:
            log(f"Lỗi gửi Tele text: {e}")
        return

    media = [{"type": "photo", "media": url, "caption": caption if idx == 0 else "", "parse_mode": "HTML"} for idx, url in enumerate(images)]
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup", json={"chat_id": cfg["chat_id"], "media": media})
        log(f"Đã gửi album {len(images)} ảnh cho tin mới: {item['title']}")
    except Exception as e:
        log(f"Lỗi gửi Tele: {e}")

def extract_from_card(card_el):
    try:
        try:
            a_el = card_el.find_element(By.XPATH, ".//a[contains(@href, '/mua-ban-') and contains(@href, '.htm')]")
            link = a_el.get_attribute("href")
            if not link or '/tags/' in link:
                return None
        except:
            return None

        lines = card_el.text.strip().split('\n')
        lines = [l.strip() for l in lines if l.strip()]

        data = {
            "title": "Không tiêu đề",
            "price": "Thỏa thuận",
            "link": link,
            "time": "N/A",
            "location": "Hà Nội",
            "seller": "Ẩn danh",
            "views": 0
        }

        for line in lines:
            if ('đ' in line or 'triệu' in line or 'Thỏa thuận' in line) and any(c.isdigit() for c in line):
                if data["price"] == "Thỏa thuận": data["price"] = line
            elif ('trước' in line or 'ngày' in line or 'giờ' in line or 'hôm qua' in line or 'tháng' in line):
                if data["time"] == "N/A": data["time"] = line
            elif ('Quận' in line or 'Huyện' in line or 'Q.' in line or '(P.' in line or 'TP.' in line):
                if data["location"] == "Hà Nội": data["location"] = line
            elif ('đã bán' in line or 'lượt xem' in line):
                data["seller"] = line

        for line in lines:
            if line not in [data["price"], data["time"], data["location"], data["seller"]] and not line.isdigit() and len(line) > 5 and "sử dụng" not in line.lower() and "mới" != line.lower() and line != "Guitar" and line != "Organ":
                data["title"] = line
                break

        # Filter out injected ads (Gợi ý, Tin nổi bật, Tin hết hạn) and wrong categories
        bad_titles = ["tin hết hạn", "tin nổi bật", "gợi ý", "tự động", "không tiêu đề"]
        if any(b in data["title"].lower() for b in bad_titles) or len(data["title"]) < 5:
            log(f"DEBUG Filter Title: {data['title']} (lines: {lines})")
            return None
            
        if not data["link"]:
            log("DEBUG Filter: No link")
            return None
            
        # Filter domains and locations
        link_lower = data["link"].lower()
        if "nhatot.com" in link_lower or "xe.chotot.com" in link_lower:
            log(f"DEBUG Filter Domain: {link_lower}")
            return None
        if "ha-noi" not in link_lower:
            log(f"DEBUG Filter Location: {link_lower}")
            return None
            
        # Filter obvious wrong categories that might appear in suggestions
        bad_categories = ["-dien-thoai-", "-may-tinh-", "-laptop-", "-tivi-", "-tu-lanh-", "-may-giat-", "-dieu-hoa-", "-oto-", "-xe-may-", "-xe-dap-", "-thu-cung-", "-thoi-trang-", "-viec-lam-", "-dong-ho-"]
        if any(c in link_lower for c in bad_categories):
            log(f"DEBUG Filter Category: {link_lower}")
            return None

        return data
    except Exception as e:
        log(f"Lỗi trích xuất card: {e}")
        return None

def calculate_post_time(relative_time):
    now = datetime.now()
    try:
        if "phút trước" in relative_time:
            val = int(''.join(filter(str.isdigit, relative_time)))
            return (now - timedelta(minutes=val)).strftime("%Y-%m-%d %H:%M")
        elif "giờ trước" in relative_time:
            val = int(''.join(filter(str.isdigit, relative_time)))
            return (now - timedelta(hours=val)).strftime("%Y-%m-%d %H:%M")
        elif "ngày trước" in relative_time:
            val = int(''.join(filter(str.isdigit, relative_time)))
            return (now - timedelta(days=val)).strftime("%Y-%m-%d %H:%M")
        elif "hôm qua" in relative_time.lower():
            return (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        elif "tuần trước" in relative_time:
            val = int(''.join(filter(str.isdigit, relative_time)))
            return (now - timedelta(days=val*7)).strftime("%Y-%m-%d %H:%M")
        elif "tháng trước" in relative_time:
            val = int(''.join(filter(str.isdigit, relative_time)))
            return (now - timedelta(days=val*30)).strftime("%Y-%m-%d %H:%M")
        else:
            return relative_time
    except:
        return relative_time

import re

def get_item_id(link):
    match = re.search(r'/(\d+)\.htm', link)
    if match:
        return match.group(1)
    return link

def scrape():
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1tr")
    ws = connect_google_sheet()

    existing_ids = set()
    try:
        data_old = ws.get_all_values()[1:]
        existing_ids = {get_item_id(row[3].strip()) for row in data_old if len(row) > 3 and row[3].strip()}
        log(f"Đọc {len(existing_ids)} ID cũ từ sheet")
    except:
        pass

    driver = setup_driver()
    new_count = 0
    page = 1
    new_rows = []

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        scroll_to_bottom(driver)

        # Lấy trực tiếp các thẻ a, rồi từ đó truy ngược ra thẻ cha li/div bọc ngoài
        a_tags = driver.find_elements(By.XPATH, "//a[contains(@href, '/mua-ban-') and contains(@href, '.htm') and not(contains(@href, '/tags/'))]")
        log(f"Trang {page}: Tìm thấy {len(a_tags)} cards (có link ad thật)")

        processed = 0
        for a_tag in a_tags:
            try:
                card = a_tag.find_element(By.XPATH, "..")
                raw_href = a_tag.get_attribute("href")
            except:
                continue
                
            text = card.text.strip()
            if len(text) < 50:
                # log(f"Skip card rác (quá ngắn): {raw_href}")
                continue  # skip card rác

            data = extract_from_card(card)
            if not data:
                log(f"Trích xuất thất bại (Bị filter): {raw_href}")
                continue

            link = data["link"]
            item_id = get_item_id(link)
            if item_id in existing_ids:
                log(f"Bỏ qua tin cũ (Đã có trong Sheet): {link}")
                continue

            # Sử dụng Selenium lấy ảnh để chống block
            images = get_images_from_detail(driver, link)
            
            # Gửi Tele (dù có ảnh hay không có ảnh vẫn gửi text)
            send_telegram_album(data, images)

            scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            abs_time = calculate_post_time(data["time"])
            
            stt = len(existing_ids) + new_count + 1
            row = [str(stt), data["title"], data["price"], link, abs_time, data["location"], data["seller"], str(data["views"]), "", scan_time]
            new_rows.append(row)
            existing_ids.add(item_id)
            new_count += 1
            processed += 1
            log(f"TIN MỚI → {data['title']} | {data['price']} | {link}")

        log(f"Trang {page}: Xử lý thành công {processed} tin mới")

        if processed == 0:
            log("Không có tin mới trên trang này. Tạm dừng để tiết kiệm thời gian.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    
    if new_rows:
        try:
            ws.insert_rows(new_rows, 2)
            log(f"Đã ghi {len(new_rows)} dòng mới lên đầu file Google Sheet.")
        except Exception as e:
            log(f"Lỗi khi ghi vào Google Sheet: {e}")
            
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    scrape()

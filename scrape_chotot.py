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
from datetime import datetime
from bs4 import BeautifulSoup
import re

# CẤU HÌNH
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"
MAX_PAGES = 12
SLEEP_BETWEEN_PAGES = random.uniform(8, 15)

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
    log("Khởi tạo Chrome...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def scroll_to_bottom(driver):
    log("Scroll xuống cuối...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(12):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(3, 5))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
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
    except:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    if ws.row_values(1) != HEADERS:
        ws.update("A1", [HEADERS])
    return ws

def get_images_from_detail(link):
    try:
        r = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        images = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
                if "image" in data:
                    img = data["image"]
                    if isinstance(img, str) and "cdn.chotot.com" in img:
                        images.append(img)
                    elif isinstance(img, list):
                        images.extend([i for i in img if "cdn.chotot.com" in i])
            except:
                pass
        return list(set(images))[:6]
    except:
        return []

def send_telegram_album(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"] or not images:
        return
    caption = f"<b>{item['title']}</b>\n{item['price']}\n{item['location']}\n{item['link']}"
    media = [{"type": "photo", "media": url, "caption": caption if i == 0 else "", "parse_mode": "HTML"} for i, url in enumerate(images)]
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup", json={"chat_id": cfg["chat_id"], "media": media})
        log(f"Đã gửi album cho tin mới: {item['title']}")
    except Exception as e:
        log(f"Lỗi gửi: {e}")

def extract_from_card(card_el):
    try:
        text = card_el.text.strip()
        if not text or len(text) < 20:
            return None

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        # Title: dòng đầu hoặc dòng có từ "Đàn", "Organ", "Guitar"...
        title = lines[0] if lines else "Không tiêu đề"
        if "đ" in title or "trước" in title:
            title = lines[1] if len(lines) > 1 else title

        # Price: dòng chứa ₫, triệu, đ, Thỏa thuận
        price = "Thỏa thuận"
        for line in lines:
            if any(k in line for k in ['₫', 'triệu', 'đ', 'Thỏa thuận']):
                price = line
                break

        # Link: tìm a trong card
        link = ""
        try:
            a = card_el.find_element(By.TAG_NAME, "a")
            link = a.get_attribute("href")
            if not link.startswith("http"):
                link = BASE_URL + link
        except:
            pass

        if not link or '/tags/' in link:
            return None

        # Location: dòng chứa Quận, Huyện
        location = "Hà Nội"
        for line in lines:
            if any(k in line for k in ['Quận', 'Huyện', '(P.', 'TP.']):
                location = line
                break

        # Time: dòng chứa trước, ngày, giờ, hôm qua
        time_posted = "N/A"
        for line in lines:
            if any(k in line for k in ['trước', 'ngày', 'giờ', 'hôm qua', 'tháng']):
                time_posted = line
                break

        return {
            "title": title,
            "price": price,
            "link": link,
            "time": time_posted,
            "location": location,
            "seller": "Ẩn danh",
            "views": 0
        }
    except Exception as e:
        log(f"Lỗi extract card: {e}")
        return None

def scrape():
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT Nhạc cụ HN ≤ 2.1tr")
    ws = connect_google_sheet()

    existing_links = set()
    try:
        data_old = ws.get_all_values()[1:]
        existing_links = {row[3].strip() for row in data_old if len(row) > 3 and row[3].strip()}
        log(f"Đọc {len(existing_links)} link cũ")
    except:
        pass

    driver = setup_driver()
    new_count = 0
    page = 1

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")
        driver.get(url)

        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        scroll_to_bottom(driver)

        # Fallback cards như log của bạn
        card_elements = driver.find_elements(By.CSS_SELECTOR, 'div[class*="AdCard"], div[class*="item"], div[class*="card"], div[class*="list-item"], li, div[data-testid*="ad"], div[class*="wrapper"]')
        log(f"Fallback cards: {len(card_elements)}")

        if len(card_elements) > 0:
            # Debug text của card đầu
            try:
                log("DEBUG text card đầu tiên:")
                print(card_elements[0].text[:500])
            except:
                pass

        processed = 0
        for card in card_elements:
            data = extract_from_card(card)
            if not data or not data['link'] or data['title'] == "Không tiêu đề":
                continue
            link = data["link"]
            if link in existing_links:
                continue

            images = get_images_from_detail(link)
            if images:
                send_telegram_album(data, images)

            stt = len(existing_links) + new_count + 1
            row = [stt, data["title"], data["price"], link, data["time"], data["location"], data["seller"], data["views"], ""]
            ws.append_row(row)
            existing_links.add(link)
            new_count += 1
            processed += 1
            log(f"TIN MỚI → {data['title']} | {data['price']}")

        log(f"Trang {page}: Xử lý thành công {processed} tin")

        if processed == 0 and len(card_elements) == 0:
            log("Không có tin → dừng.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    scrape()

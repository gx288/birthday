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

# CẤU HÌNH
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"
MAX_PAGES = 12
SLEEP_BETWEEN_PAGES = random.uniform(6, 12)  # tăng để tránh anti-bot

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
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def scroll_to_bottom(driver):
    log("🔄 Scroll xuống cuối...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(12):  # tăng số lần scroll
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2.5, 4.5))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    time.sleep(2)
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
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        images = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
                if "image" in data:
                    img = data["image"]
                    if isinstance(img, str):
                        images.append(img)
                    elif isinstance(img, list):
                        images.extend(img)
            except:
                pass
        return [i for i in set(images) if "cdn.chotot.com" in i][:6]
    except:
        return []

def send_telegram_album(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"] or not images:
        return
    media = [{"type": "photo", "media": url, "caption": f"<b>{item['title']}</b>\n{item['price']}\n{item['link']}", "parse_mode": "HTML"} if i == 0 else {"type": "photo", "media": url} for i, url in enumerate(images)]
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup", json={"chat_id": cfg["chat_id"], "media": media})
        log(f"Gửi album cho: {item['title']}")
    except Exception as e:
        log(f"Lỗi gửi Tele: {e}")

def extract_from_link_element(a_el):
    try:
        link = a_el.get_attribute("href")
        if not link.startswith("http"):
            link = BASE_URL + link
        if '/tags/' in link or not link.endswith('.htm'):
            return None

        parent = a_el.find_element(By.XPATH, "./ancestor::li | ./ancestor::div[contains(@class,'item') or contains(@class,'card') or contains(@class,'ad')]")
        title = a_el.text.strip() or parent.text.split('\n')[0].strip()

        price = "Thỏa thuận"
        try:
            price_el = parent.find_element(By.XPATH, ".//span[contains(.,'₫') or contains(.,'triệu') or contains(.,'đ')]")
            price = price_el.text.strip()
        except:
            pass

        time_posted = "N/A"
        try:
            time_el = parent.find_element(By.XPATH, ".//span[contains(.,'trước') or contains(.,'ngày') or contains(.,'giờ')]")
            time_posted = time_el.text.strip()
        except:
            pass

        location = "Hà Nội"
        try:
            loc_el = parent.find_element(By.XPATH, ".//span[contains(.,'Quận') or contains(.,'Huyện')]")
            location = loc_el.text.strip()
        except:
            pass

        return {
            "title": title or "Không tiêu đề",
            "price": price,
            "link": link,
            "time": time_posted,
            "location": location,
            "seller": "Ẩn danh",
            "views": 0
        }
    except:
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
        WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        scroll_to_bottom(driver)

        # Cách 1: Tìm tất cả <a> có href ad thật
        potential_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/mua-ban-nhac-cu/"][href$=".htm"]')
        log(f"Potential ad links found: {len(potential_links)}")

        items_data = []
        for a in potential_links:
            data = extract_from_link_element(a)
            if data:
                items_data.append((a, data))  # giữ a để extract từ parent

        log(f"Trang {page}: Extract thành công {len(items_data)} tin")

        if len(items_data) == 0:
            log("DEBUG: KHÔNG TÌM THẤY TIN → IN SNIPPET HTML")
            try:
                html_snippet = driver.find_element(By.TAG_NAME, "body").get_attribute("outerHTML")[:2000]
                print("HTML snippet đầu page (tìm class list hoặc a href):")
                print(html_snippet)
            except:
                pass

        for _, data in items_data:
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
            log(f"TIN MỚI → {data['title']} | {data['price']}")

        if len(items_data) < 3:
            log("Có vẻ hết hoặc lỗi load → dừng.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    scrape()

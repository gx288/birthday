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

def setup_driver(headless=True):
    log("Khởi tạo Chrome...")
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"user-agent={random.choice(['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'])}")
    driver = webdriver.Chrome(options=options)
    return driver

def scroll_to_bottom(driver):
    log("Scroll xuống cuối...")
    try:
        for _ in range(15):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(3, 5))
        time.sleep(3)
    except:
        pass
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
        log(f"Lỗi gửi album: {e}")

def extract_from_parent(parent_el):
    try:
        a_el = parent_el.find_element(By.TAG_NAME, "a")
        link = a_el.get_attribute("href")
        if '/tags/' in link or not link.endswith('.htm'):
            return None

        title = "Không tiêu đề"
        try:
            title = parent_el.find_element(By.CSS_SELECTOR, 'h3, h4, [class*="title"], [class*="name"]').text.strip()
        except:
            title = a_el.text.strip().splitlines()[0].strip()

        price = "Thỏa thuận"
        try:
            price = parent_el.find_element(By.CSS_SELECTOR, '[class*="price"], span:has-text("₫"), span:has-text("triệu")').text.strip()
        except:
            pass

        return {
            "title": title,
            "price": price,
            "link": link,
            "time": "N/A",
            "location": "Hà Nội",
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

    driver = setup_driver(headless=True)  # Thử False nếu vẫn 0 để test
    new_count = 0
    page = 1

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")
        driver.get(url)

        try:
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            # Chờ thêm cho listings (nếu có class chung)
            WebDriverWait(driver, 20).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'a[href*="/mua-ban-nhac-cu/"][href$=".htm"]')) > 0 or "không có kết quả" in d.page_source.lower())
        except:
            log("Timeout chờ listings hoặc có thể không có tin.")

        scroll_to_bottom(driver)

        # Check nếu trang "No results"
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(x in body_text for x in ["không có kết quả", "không tìm thấy", "0 tin đăng"]):
            log("Trang báo KHÔNG CÓ KẾT QUẢ → dừng.")
            break

        # Tìm tất cả link tin thật
        ad_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/mua-ban-nhac-cu/"][href$=".htm"]')
        log(f"Potential ad links found: {len(ad_links)}")

        if len(ad_links) == 0:
            log("DEBUG: Không tìm thấy link ad → in body text đầu để check")
            print(driver.find_element(By.TAG_NAME, "body").text[:2000])
            log("Thử fallback tìm div card...")
            card_elements = driver.find_elements(By.CSS_SELECTOR, '[class*="AdCard"], [class*="item"], [class*="list-item"], [data-testid*="ad"]')
            log(f"Fallback cards: {len(card_elements)}")

        processed = 0
        for a in ad_links:
            try:
                parent = a.find_element(By.XPATH, "./ancestor::li | ./ancestor::div[contains(@class,'card') or contains(@class,'item') or contains(@class,'ad') or contains(@class,'list')]")
                data = extract_from_parent(parent)
                if data:
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
            except:
                continue

        log(f"Trang {page}: Xử lý thành công {processed} tin mới")

        if processed == 0 and len(ad_links) == 0:
            log("Không có tin nào → dừng loop.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    scrape()

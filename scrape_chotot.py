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

# ────────────────────────────────────────────────
# CẤU HÌNH
# ────────────────────────────────────────────────
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"  # Thay nếu khác
SHEET_NAME = "Chợ tốt"
MAX_PAGES = 12
SLEEP_BETWEEN_PAGES = random.uniform(4, 8)
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
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    driver = webdriver.Chrome(options=options)
    return driver

def scroll_to_bottom(driver):
    log("🔄 Scroll xuống cuối để load hết tin...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    attempts = 0
    max_attempts = 10
    while attempts < max_attempts:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.5 + random.uniform(0.5, 1.5))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            log("Đạt đáy trang hoặc không còn load thêm.")
            break
        last_height = new_height
        attempts += 1
    time.sleep(1.2)
    log(f"Hoàn tất scroll ({attempts} lần).")

def connect_google_sheet():
    log("Kết nối Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise ValueError("Thiếu GOOGLE_CREDENTIALS env var")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    # Đảm bảo header đúng
    if ws.row_values(1) != HEADERS:
        ws.update("A1", [HEADERS])
    return ws

def get_images_from_detail(link):
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        r = requests.get(link, headers=headers, timeout=12)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
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
        return list(set(images))[:6]  # max 6 ảnh
    except Exception as e:
        log(f"Lỗi lấy ảnh: {e}")
        return []

def send_telegram_album(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"] or not images:
        return
    media = []
    caption = f"🎹 <b>MỚI - {item['title']}</b>\n💰 {item['price']}\n📍 {item['location']}\n👤 {item['seller']}\n👀 {item['views']} views\n⏰ {item['time']}\n🔗 {item['link']}"
    for i, url in enumerate(images):
        media.append({
            "type": "photo",
            "media": url,
            "caption": caption if i == 0 else "",
            "parse_mode": "HTML"
        })
    try:
        requests.post(
            f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup",
            json={"chat_id": cfg["chat_id"], "media": media}
        )
        log(f"Đã gửi album {len(images)} ảnh: {item['title']}")
    except Exception as e:
        log(f"Lỗi gửi album: {e}")

def extract_item_data(item_el):
    try:
        link_el = item_el.find_element(By.TAG_NAME, "a")
        link = link_el.get_attribute("href")
        if not link.startswith("http"):
            link = BASE_URL + link

        title = item_el.find_element(By.XPATH, './/h3 | .//h2 | .//div[contains(@class,"title")]').text.strip() or "Không tiêu đề"

        price = "Thỏa thuận"
        try:
            price_el = item_el.find_element(By.XPATH, './/span[contains(text(),"₫") or contains(text(),"triệu") or contains(text(),"đ")]')
            price = price_el.text.strip()
        except:
            pass

        time_posted = "N/A"
        try:
            time_el = item_el.find_element(By.XPATH, './/span[contains(text(),"trước") or contains(text(),"ngày") or contains(text(),"tháng")]')
            time_posted = time_el.text.strip()
        except:
            pass

        location = "Hà Nội"
        try:
            loc_el = item_el.find_element(By.XPATH, './/span[contains(@class,"location") or text()[contains(.,"Quận") or contains(.,"Huyện")]]')
            location = loc_el.text.strip()
        except:
            pass

        seller = "Ẩn danh"
        try:
            seller_el = item_el.find_element(By.XPATH, './/span[contains(@class,"seller") or contains(@class,"name")]')
            seller = seller_el.text.strip()
        except:
            pass

        views = 0
        try:
            views_text = item_el.find_element(By.XPATH, './/span[contains(text(),"lượt xem")]').text
            views = int(''.join(filter(str.isdigit, views_text)))
        except:
            pass

        return {
            "title": title,
            "price": price,
            "link": link,
            "time": time_posted,
            "location": location,
            "seller": seller,
            "views": views
        }
    except Exception as e:
        log(f"Lỗi extract item: {e}")
        return None

def scrape():
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT Nhạc cụ HN ≤ 2.1tr")
    ws = connect_google_sheet()

    # Đọc tin cũ (đơn giản hóa, bạn có thể mở rộng)
    try:
        data_old = ws.get_all_values()[1:]
        existing_links = {row[3] for row in data_old if len(row) > 3 and row[3].strip()}
        log(f"Đọc {len(existing_links)} link cũ từ sheet")
    except:
        existing_links = set()

    driver = setup_driver()
    new_count = 0
    page = 1

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")

        driver.get(url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        scroll_to_bottom(driver)

        # Tìm tất cả items (XPath linh hoạt)
        items = driver.find_elements(By.XPATH, '//li[.//a[contains(@href, "/mua-ban-nhac-cu/")]] | //div[contains(@class,"AdItem") or contains(@class,"ListItem") or @data-testid="list-item"]')
        log(f"Trang {page}: Tìm thấy {len(items)} tin")

        for item_el in items:
            data = extract_item_data(item_el)
            if not data:
                continue
            link = data["link"]
            if link in existing_links:
                continue  # skip tin cũ

            images = get_images_from_detail(link)
            if images:
                send_telegram_album(data, images)
            else:
                # Nếu không có ảnh, gửi text thôi (tùy bạn)
                pass

            # Thêm vào sheet (bạn có thể batch update sau)
            stt = len(existing_links) + new_count + 1
            row = [stt, data["title"], data["price"], link, data["time"], data["location"], data["seller"], data["views"], ""]
            ws.append_row(row)
            existing_links.add(link)
            new_count += 1
            log(f"TIN MỚI → {data['title']} | {data['price']}")

        if len(items) < 5:  # Có thể hết trang
            log("Có vẻ hết tin → dừng.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    try:
        scrape()
    except Exception as e:
        log(f"Lỗi tổng: {e}")

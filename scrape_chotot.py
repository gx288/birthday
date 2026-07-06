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
SLEEP_BETWEEN_PAGES = random.uniform(6, 12)

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
        ws.update("A1", [HEADERS])
    return ws

def get_images_from_detail(link):
    try:
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
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
        return list(set(images))[:6]
    except Exception as e:
        log(f"Lỗi lấy ảnh: {e}")
        return []

def send_telegram_album(item, images):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"] or not images:
        log("Skip gửi Tele: thiếu config hoặc ảnh")
        return
    caption = f"🎸 <b>HÀNG MỚI - CHỢ TỐT</b>\n\n<b>{item['title']}</b>\n💰 <b>{item['price']}</b>\n👤 {item['seller']}\n👀 {item['views']} views\n📍 {item['location']}\n⏰ {item['time']}\n\n<a href='{item['link']}'>🔗 Xem chi tiết</a>"
    media = [{"type": "photo", "media": url, "caption": caption if idx == 0 else "", "parse_mode": "HTML"} for idx, url in enumerate(images)]
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup", json={"chat_id": cfg["chat_id"], "media": media})
        log(f"Đã gửi album {len(images)} ảnh cho tin mới: {item['title']}")
    except Exception as e:
        log(f"Lỗi gửi Tele: {e}")

def extract_from_card(card_el):
    try:
        link = card_el.get_attribute("href")
        if not link or '/tags/' in link:
            return None
    except:
        return None

        data = {
            "title": "Không tiêu đề",
            "price": "Thỏa thuận",
            "link": link,
            "time": "N/A",
            "location": "Hà Nội",
            "seller": "Ẩn danh",
            "views": 0
        }

        # Title: ưu tiên h3/h4/strong/a text
        try:
            title_el = card_el.find_element(By.CSS_SELECTOR, 'h3, h4, strong, [class*="title"], [class*="name"], a')
            data["title"] = title_el.text.strip()
        except:
            pass

        # Price
        try:
            price_el = card_el.find_element(By.XPATH, ".//span | .//div | .//strong[contains(., '₫') or contains(., 'triệu') or contains(., 'đ') or contains(., 'Thỏa thuận')]")
            data["price"] = price_el.text.strip()
        except:
            pass

        # Time
        try:
            time_el = card_el.find_element(By.XPATH, ".//span[contains(., 'trước') or contains(., 'ngày') or contains(., 'giờ') or contains(., 'hôm qua') or contains(., 'tháng')]")
            data["time"] = time_el.text.strip()
        except:
            pass

        # Location
        try:
            loc_el = card_el.find_element(By.XPATH, ".//span[contains(., 'Quận') or contains(., 'Huyện') or contains(., '(P.') or contains(., 'TP.') or contains(@class, 'location')]")
            data["location"] = loc_el.text.strip()
        except:
            pass

        # Seller
        try:
            seller_el = card_el.find_element(By.XPATH, ".//span[contains(., 'đã bán') or contains(., 'lượt xem') or contains(@class, 'seller') or contains(@class, 'name')]")
            data["seller"] = seller_el.text.strip()
        except:
            pass

        # Views (nếu có)
        try:
            views_text = card_el.find_element(By.XPATH, ".//span[contains(., 'lượt xem')]").text
            data["views"] = int(''.join(c for c in views_text if c.isdigit()))
        except:
            pass

        if len(data["title"]) < 5 or not data["link"]:
            return None

        return data
    except:
        return None

def scrape():
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1tr")
    ws = connect_google_sheet()

    existing_links = set()
    try:
        data_old = ws.get_all_values()[1:]
        existing_links = {row[3].strip() for row in data_old if len(row) > 3 and row[3].strip()}
        log(f"Đọc {len(existing_links)} link cũ từ sheet")
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

        # Tìm trực tiếp thẻ <a> chứa link ad thật
        card_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/mua-ban-') and contains(@href, '.htm') and not(contains(@href, '/tags/'))]")
        log(f"Trang {page}: Tìm thấy {len(card_elements)} cards (có link ad thật)")

        debug_printed = False
        processed = 0
        for card in card_elements:
            text = card.text.strip()
            if len(text) < 50:
                continue  # skip card rác

            # Debug: in text của 2-3 card đầu có nội dung
            if not debug_printed and processed < 3:
                log(f"DEBUG text card {processed+1} (cấu trúc thực tế):")
                print(text[:800])  # in 800 ký tự đầu
                debug_printed = True

            data = extract_from_card(card)
            if not data:
                continue

            link = data["link"]
            if link in existing_links:
                continue

            images = get_images_from_detail(link)
            if images:
                send_telegram_album(data, images)
            else:
                log(f"Tin mới không có ảnh: {data['title']}")

            stt = len(existing_links) + new_count + 1
            row = [str(stt), data["title"], data["price"], link, data["time"], data["location"], data["seller"], str(data["views"]), ""]
            ws.append_row(row)
            existing_links.add(link)
            new_count += 1
            processed += 1
            log(f"TIN MỚI → {data['title']} | {data['price']} | {link}")

        log(f"Trang {page}: Xử lý thành công {processed} tin mới")

        if processed == 0:
            log("Không extract được tin nào → kiểm tra DEBUG text ở trên để fix XPath/CSS.")
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()
    log(f"Hoàn thành: +{new_count} tin mới")

if __name__ == "__main__":
    scrape()

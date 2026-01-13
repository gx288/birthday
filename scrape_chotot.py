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
        headers = ["Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Scraped At", "Hidden"]
        worksheet.append_row(headers)
        log("Tạo sheet & header mới")
    if worksheet.col_count < 9:
        worksheet.resize(cols=10)
    headers = worksheet.row_values(1)
    if len(headers) < 9 or headers[8] != "Hidden":
        worksheet.update_cell(1, 9, "Hidden")
        log("Đảm bảo cột Hidden ở I")
    return worksheet

def get_images_from_detail(link):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        resp = requests.get(link, headers=headers, timeout=12)
        if resp.status_code != 200:
            log(f"Detail {link} status {resp.status_code}")
            return [], []
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        videos = []
        # JSON-LD
        json_ld_tags = soup.find_all("script", type="application/ld+json")
        for tag in json_ld_tags:
            try:
                data = json.loads(tag.string or "{}")
                if isinstance(data, dict) and "image" in data:
                    img_list = data["image"]
                    if isinstance(img_list, str):
                        img_list = [img_list]
                    if isinstance(img_list, list):
                        for img in img_list:
                            if isinstance(img, str) and "cdn.chotot.com" in img:
                                if "preset:view/plain" in img or "preset:listing" in img:
                                    images.append(img)
            except:
                pass
        # Regex lọc ảnh thật
        matches = re.findall(r'(https?://cdn\.chotot\.com/[^"\')\s<]+?\.(jpg|jpeg|png|webp))', resp.text)
        for m in matches:
            url = m[0]
            if (re.search(r'-\d{15,}\.(jpg|jpeg|png|webp)$', url) and
                "avatar" not in url and "logo" not in url and "admincentre" not in url and
                "reward" not in url):
                if url not in images:
                    images.append(url)
        # Video thumbnail
        thumb_videos = soup.find_all("img", src=re.compile(r'videodelivery\.net.*thumbnail'))
        for thumb in thumb_videos:
            src = thumb.get("src") or ""
            if src:
                videos.append(src)
        # Giới hạn & unique
        images = list(dict.fromkeys(images))[:6]
        videos = list(dict.fromkeys(videos))[:2]
        log(f"Detail {link}: {len(images)} ảnh + {len(videos)} video")
        return images, videos
    except Exception as e:
        log(f"Lỗi lấy media {link}: {e}")
        return [], []

def send_telegram_with_media(item, images, videos):
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

    valid_images = [img for img in images if is_valid_media_url(img)]
    valid_videos = [vid for vid in videos if is_valid_media_url(vid)]

    log(f"Sau lọc tồn tại: {len(valid_images)} ảnh + {len(valid_videos)} video")

    media_group = []

    for idx, img_url in enumerate(valid_images):
        media_group.append({
            "type": "photo",
            "media": img_url,
            "caption": caption if idx == 0 and not valid_videos else "",
            "parse_mode": "HTML"
        })

    for vid_url in valid_videos:
        media_group.append({
            "type": "video",
            "media": vid_url,
            "caption": caption if not media_group else ""
        })

    if media_group:
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMediaGroup"
        payload = {"chat_id": cfg["chat_id"], "media": json.dumps(media_group)}
        try:
            resp = requests.post(url, data=payload, timeout=30)
            if resp.status_code == 200:
                log(f"✅ Gửi media group thành công")
            else:
                log(f"Media group lỗi {resp.status_code}: {resp.text[:200]} → gửi text")
                send_telegram_alert(item)
        except Exception as e:
            log(f"Lỗi gửi media group: {e} → gửi text")
            send_telegram_alert(item)
    else:
        send_telegram_alert(item)

def is_valid_media_url(url):
    try:
        resp = requests.head(url, timeout=6, allow_redirects=True)
        return resp.status_code == 200
    except:
        return False

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
    except Exception as e:
        log(f"Lỗi gửi text Telegram: {e}")

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
        try: price = item_element.find_element(By.CSS_SELECTOR, "span.bfe6oav").text.strip()
        except: pass
        time_posted = "N/A"
        try: time_posted = item_element.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text.strip()
        except: pass
        location = "Hà Nội"
        try: location = item_element.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text.strip()
        except: pass
        seller = "Ẩn danh"
        try: seller = item_element.find_element(By.CSS_SELECTOR, "div.dteznpi span.brnpcl3").text.strip()
        except: pass
        views_str = "0"
        try: views_str = item_element.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text.strip()
        except: pass
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
    # Map link → row
    try:
        link_col = worksheet.col_values(3)
        link_to_row = {link.strip(): idx + 1 for idx, link in enumerate(link_col[1:], 1) if link.strip()}
        existing_links = set(link_to_row.keys())
        log(f"Đọc {len(existing_links)} tin cũ từ sheet")
    except Exception as e:
        log(f"Lỗi đọc sheet: {e}")
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
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t")))
        except Exception as e:
            log(f"Load trang {page} lỗi: {e}")
            if page_has_no_results(driver):
                log("Hết kết quả → dừng")
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                log("Dừng do nhiều trang rỗng")
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_PAGES)
            continue
        if page_has_no_results(driver):
            break
        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"Tìm thấy {len(items)} item")
        new_rows = []
        batch_requests = []
        item_order = 0  # thứ tự trong page
        for item_el in items:
            data = extract_item_data(item_el, page)
            if not data:
                continue
            link = data["link"]
            item_order += 1  # tăng thứ tự quét (tin đầu page = 1)
            if link in link_to_row:
                row = link_to_row[link]
                batch_requests.append({
                    "range": f"G{row}",
                    "values": [[str(data["views"])]]
                })
                batch_requests.append({
                    "range": f"I{row}",
                    "values": [[str(page)]]
                })
                total_updated += 1
            else:
                existing_links.add(link)
                # Thêm cột tạm "Order" (cột 10) để sort ổn định trong page
                new_rows.append([
                    data["title"], data["price"], link, data["time"], data["location"],
                    data["seller"], str(data["views"]), data["scraped_at"], str(page),
                    str(item_order)  # cột tạm Order
                ])
                images, videos = get_images_from_detail(link)
                send_telegram_with_media(data, images, videos)
                total_new += 1
        if new_rows:
            log(f"Thêm {len(new_rows)} tin mới từ trang {page}")
            # Append
            worksheet.append_rows(new_rows)
            # Sort lại toàn bộ sheet
            try:
                all_data = worksheet.get_all_values()[1:]  # từ dòng 2
                if all_data:
                    # Sort: page tăng dần (cột 9 index 8), rồi Order tăng dần (cột 10 index 9)
                    sorted_data = sorted(
                        all_data,
                        key=lambda row: (
                            int(row[8]) if len(row) > 8 and row[8].isdigit() else 999,
                            int(row[9]) if len(row) > 9 and row[9].isdigit() else 999
                        ),
                        reverse=False
                    )
                    worksheet.clear()
                    # Header có thêm cột Order tạm (cột J)
                    worksheet.append_row(["Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Scraped At", "Hidden", "Order"])
                    worksheet.append_rows(sorted_data)
                    # Xóa cột Order tạm (cột J)
                    worksheet.delete_columns(10)
                    log(f"Đã sort sheet theo page tăng dần + thứ tự trong page ({len(sorted_data)} dòng)")
            except Exception as e:
                log(f"Lỗi sort sheet: {e}")
        if batch_requests:
            worksheet.batch_update(batch_requests)
            log(f"Batch update {len(batch_requests)//2} tin cũ trang {page}")
        if not new_rows and not batch_requests:
            consecutive_empty += 1
        else:
            consecutive_empty = 0
        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)
    driver.quit()
    log(f"Hoàn thành: +{total_new} mới | ↑{total_updated} cập nhật")

if __name__ == "__main__":
    try:
        scrape_data()
    except Exception as e:
        log(f"Lỗi chính: {e}")

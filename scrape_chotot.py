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

# --- CẤU HÌNH ---
BASE_URL = "https://www.chotot.com"
START_URL = "https://www.chotot.com/mua-ban-nhac-cu-ha-noi?price=0-2100000&f=p&limit=20"
SHEET_ID = "14tqKftTqlesnb0NqJZU-_f1EsWWywYqO36NiuDdmaTo"
SHEET_NAME = "Chợ tốt"

def log(message):
    """Hàm in log có thời gian để dễ theo dõi"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")

def get_telegram_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID")
    }

def setup_driver():
    log("🌐 Đang khởi tạo trình duyệt Chrome (Headless)...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    log("✅ Khởi tạo trình duyệt thành công.")
    return driver

def connect_google_sheet():
    log("📂 Đang kết nối Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    
    sh = client.open_by_key(SHEET_ID)
    try:
        worksheet = sh.worksheet(SHEET_NAME)
        log(f"✅ Đã tìm thấy sheet '{SHEET_NAME}'.")
    except gspread.WorksheetNotFound:
        log(f"⚠️ Chưa có sheet '{SHEET_NAME}', đang tạo mới...")
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows="1000", cols="6")
        worksheet.append_row(["Title", "Price", "Link", "Time Posted", "Location", "Scraped At"])
        log("✅ Đã tạo sheet mới thành công.")
    
    return worksheet

def send_telegram_alert(item):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        log("❌ Thiếu cấu hình Telegram (Token/ChatID). Bỏ qua gửi tin.")
        return

    log(f"📲 Đang gửi tin Telegram: {item['title']}...")
    
    message = (
        f"🎸 <b>HÀNG MỚI TRÊN CHỢ TỐT!</b>\n\n"
        f"🏷 <b>Tên:</b> {item['title']}\n"
        f"💰 <b>Giá:</b> {item['price']}\n"
        f"📍 <b>Khu vực:</b> {item['location']}\n"
        f"⏰ <b>Đăng:</b> {item['time']}\n\n"
        f"🔗 <a href='{item['link']}'>Xem chi tiết ngay</a>"
    )
    
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            log("   -> Gửi thành công.")
        else:
            log(f"   -> Gửi thất bại: {response.text}")
        time.sleep(1) 
    except Exception as e:
        log(f"   -> Lỗi khi gửi Telegram: {e}")

def scrape_data():
    log("🚀 BẮT ĐẦU QUÁ TRÌNH SCRAPE...")
    
    # 1. Kết nối Sheet trước để lấy dữ liệu cũ
    worksheet = connect_google_sheet()
    try:
        existing_links = worksheet.col_values(3)[1:] # Cột 3 là Link, bỏ header
        existing_items_check = set(existing_links)
        log(f"ℹ️ Đã có {len(existing_items_check)} sản phẩm trong kho dữ liệu cũ.")
    except Exception as e:
        log(f"⚠️ Lỗi khi đọc dữ liệu cũ (có thể sheet rỗng): {e}")
        existing_items_check = set()

    # 2. Khởi động trình duyệt
    driver = setup_driver()
    
    new_items = []
    page = 1
    has_items = True

    while has_items:
        current_url = f"{START_URL}&page={page}" if page > 1 else START_URL
        log(f"\n--- ĐANG XỬ LÝ TRANG {page} ---")
        log(f"🔗 URL: {current_url}")
        
        driver.get(current_url)
        
        try:
            # Đợi load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t"))
            )
            
            items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
            if not items:
                log("🛑 Không tìm thấy thẻ <li> nào. Có thể đã hết hàng.")
                has_items = False
                break
            
            log(f"🔎 Tìm thấy {len(items)} items trên trang này.")

            items_found_on_page = 0
            duplicates_on_page = 0
            
            for index, item in enumerate(items):
                try:
                    link_el = item.find_element(By.TAG_NAME, "a")
                    link = link_el.get_attribute("href")
                    if not link.startswith("http"):
                        link = BASE_URL + link
                    
                    # Log ngắn gọn để biết đang chạy
                    # print(f"   Check item {index+1}: {link[-20:]}...", end="\r")

                    if link in existing_items_check:
                        duplicates_on_page += 1
                        continue
                        
                    existing_items_check.add(link)
                    
                    # Lấy thông tin chi tiết
                    try:
                        title = item.find_element(By.CSS_SELECTOR, "h3").text
                    except:
                        title = link_el.get_attribute("title") or "No Title"

                    try:
                        price = item.find_element(By.CSS_SELECTOR, "span.bfe6oav").text
                    except:
                        price = "Thỏa thuận"
                        
                    try:
                        time_posted = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text
                    except:
                        time_posted = "N/A"

                    try:
                        loc = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text
                    except:
                        loc = "Hà Nội"

                    item_data = {
                        "title": title,
                        "price": price,
                        "link": link,
                        "time": time_posted,
                        "location": loc,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    new_items.append(item_data)
                    items_found_on_page += 1
                    log(f"   ✅ Phát hiện món mới: {title} - {price}")

                except Exception as e:
                    log(f"   ⚠️ Lỗi parse item {index}: {e}")
                    continue
            
            log(f"📊 Tổng kết trang {page}: {items_found_on_page} món mới | {duplicates_on_page} món trùng.")

            # Logic dừng thông minh: Nếu trang này toàn món trùng (không có món mới nào)
            # thì khả năng cao các trang sau cũng toàn đồ cũ -> DỪNG
            if items_found_on_page == 0 and duplicates_on_page > 0:
                log("🛑 Trang này toàn bộ là hàng cũ. Dừng cào để tiết kiệm thời gian.")
                has_items = False
                break

            page += 1
            time.sleep(2)

        except Exception as e:
            log(f"🛑 Lỗi hoặc hết trang tại page {page}. ({e})")
            has_items = False

    driver.quit()
    log("\n--- KẾT THÚC CÀO DỮ LIỆU ---")
    
    if new_items:
        log(f"🎉 Tổng cộng tìm thấy {len(new_items)} món hàng mới.")
        
        # Đảo ngược để lưu món cũ nhất lên trước
        new_items.reverse()
        
        rows_to_add = []
        for item in new_items:
            send_telegram_alert(item)
            rows_to_add.append([
                item["title"],
                item["price"],
                item["link"],
                item["time"],
                item["location"],
                item["scraped_at"]
            ])
        
        log("💾 Đang lưu vào Google Sheets...")
        try:
            worksheet.append_rows(rows_to_add)
            log("✅ Đã lưu xong.")
        except Exception as e:
            log(f"❌ Lỗi khi lưu sheet: {e}")
            
    else:
        log("💤 Không có món hàng nào mới trong lần chạy này.")

    log("🏁 Hoàn tất script.")

if __name__ == "__main__":
    scrape_data()

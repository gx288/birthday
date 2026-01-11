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
    """In log kèm thời gian"""
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
    # User Agent giả lập để không bị chặn
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
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
        # Tạo thêm cột Seller và Views
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows="1000", cols="8")
        worksheet.append_row(["Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Scraped At"])
        log("✅ Đã tạo sheet mới thành công.")
    
    return worksheet

def send_telegram_alert(item):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return

    log(f"📲 Đang gửi tin Telegram: {item['title']}...")
    
    message = (
        f"🎸 <b>HÀNG MỚI TRÊN CHỢ TỐT!</b>\n\n"
        f"🏷 <b>{item['title']}</b>\n"
        f"💰 Giá: <b>{item['price']}</b>\n"
        f"👤 Người bán: {item['seller']}\n"
        f"👀 Lượt xem: {item['views']}\n"
        f"📍 Khu vực: {item['location']}\n"
        f"⏰ Đăng: {item['time']}\n\n"
        f"🔗 <a href='{item['link']}'>👉 Xem chi tiết tại đây</a>"
    )
    
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload)
        time.sleep(1) # Tránh spam API
    except Exception as e:
        log(f"❌ Lỗi gửi Telegram: {e}")

def scrape_data():
    log("🚀 BẮT ĐẦU QUÁ TRÌNH SCRAPE...")
    
    # 1. Lấy dữ liệu cũ từ Sheet để so sánh
    worksheet = connect_google_sheet()
    try:
        existing_links = worksheet.col_values(3)[1:] # Cột 3 là Link
        existing_items_check = set(existing_links)
        log(f"ℹ️ Đã có {len(existing_items_check)} sản phẩm trong dữ liệu cũ.")
    except:
        existing_items_check = set()

    driver = setup_driver()
    new_items = []
    page = 1
    has_items = True

    while has_items:
        current_url = f"{START_URL}&page={page}" if page > 1 else START_URL
        log(f"\n--- ĐANG XỬ LÝ TRANG {page} ---")
        driver.get(current_url)
        
        try:
            # CHECK QUAN TRỌNG: Kiểm tra xem có thông báo hết kết quả không
            # Tìm text "Không có kết quả" trong body
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if "Không có kết quả cho bộ lọc đã chọn" in body_text:
                    log("🛑 Phát hiện thông báo: 'Không có kết quả cho bộ lọc đã chọn'.")
                    log("🛑 Dừng cào dữ liệu tại đây (bỏ qua quảng cáo).")
                    has_items = False
                    break
            except:
                pass

            # Đợi item list load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t"))
            )
            
            items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
            if not items:
                log("🛑 Không tìm thấy danh sách sản phẩm.")
                break
            
            log(f"🔎 Quét thấy {len(items)} items trên trang này.")
            items_found_on_page = 0
            
            for item in items:
                try:
                    # Lấy Link trước để check trùng
                    link_el = item.find_element(By.TAG_NAME, "a")
                    link = link_el.get_attribute("href")
                    if not link.startswith("http"):
                        link = BASE_URL + link
                    
                    if link in existing_items_check:
                        continue # Bỏ qua nếu đã có
                    
                    existing_items_check.add(link)

                    # --- TRÍCH XUẤT DỮ LIỆU ---
                    # 1. Tiêu đề
                    try:
                        title = item.find_element(By.CSS_SELECTOR, "h3").text
                    except: title = "No Title"

                    # 2. Giá
                    try:
                        price = item.find_element(By.CSS_SELECTOR, "span.bfe6oav").text
                    except: price = "Thỏa thuận"
                        
                    # 3. Thời gian đăng (cập nhật selector chính xác hơn từ HTML bạn cung cấp)
                    try:
                        time_posted = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text
                    except: time_posted = "N/A"

                    # 4. Khu vực
                    try:
                        loc = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh:not(.tx5yyjc)").text
                    except: loc = "Hà Nội"

                    # 5. Người bán (Mới) - Class lấy từ HTML: div.dteznpi span.brnpcl3
                    try:
                        seller = item.find_element(By.CSS_SELECTOR, "div.dteznpi span.brnpcl3").text
                    except: seller = "Người bán ẩn danh"

                    # 6. Lượt xem (Mới) - Class lấy từ HTML: div.vglk6qt span
                    try:
                        views = item.find_element(By.CSS_SELECTOR, "div.vglk6qt span").text
                    except: views = "0"

                    item_data = {
                        "title": title,
                        "price": price,
                        "link": link,
                        "time": time_posted,
                        "location": loc,
                        "seller": seller,
                        "views": views,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    new_items.append(item_data)
                    items_found_on_page += 1
                    log(f"   ✅ Mới: {title} | {price} | {seller}")

                except Exception as e:
                    continue
            
            if items_found_on_page == 0:
                log("⚠️ Trang này không có món nào mới (toàn trùng lặp).")
                # Vẫn tiếp tục chạy sang trang sau đề phòng có tin mới bị trôi, 
                # trừ khi gặp thông báo "Không có kết quả" ở trên.

            page += 1
            time.sleep(2)

        except Exception as e:
            log(f"🛑 Lỗi hoặc hết trang: {e}")
            has_items = False

    driver.quit()
    
    # --- LƯU VÀ THÔNG BÁO ---
    if new_items:
        log(f"🎉 Tổng cộng tìm thấy {len(new_items)} món hàng MỚI.")
        new_items.reverse() # Đảo ngược để tin cũ hơn trong đám mới được lưu trước
        
        rows_to_add = []
        for item in new_items:
            # Gửi Tele tin mới
            send_telegram_alert(item)
            
            # Chuẩn bị dòng cho Sheet
            rows_to_add.append([
                item["title"],
                item["price"],
                item["link"],
                item["time"],
                item["location"],
                item["seller"],
                item["views"],
                item["scraped_at"]
            ])
        
        log("💾 Đang lưu dữ liệu vào Sheet...")
        try:
            worksheet.append_rows(rows_to_add)
            log("✅ Lưu thành công.")
        except Exception as e:
            log(f"❌ Lỗi lưu Sheet: {e}")
    else:
        log("💤 Không có tin mới nào để thông báo.")

if __name__ == "__main__":
    scrape_data()

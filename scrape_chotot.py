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

def get_telegram_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID")
    }

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Chạy ngầm
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Fake User-Agent để tránh bị chặn
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def connect_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    
    sh = client.open_by_key(SHEET_ID)
    try:
        worksheet = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        # Tạo sheet mới nếu chưa có
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows="1000", cols="6")
        worksheet.append_row(["Title", "Price", "Link", "Time Posted", "Location", "Scraped At"])
    
    return worksheet

def send_telegram_alert(item):
    cfg = get_telegram_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return

    # Format tin nhắn HTML
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
        requests.post(url, json=payload)
        time.sleep(1) # Tránh spam
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def scrape_data():
    driver = setup_driver()
    worksheet = connect_google_sheet()
    
    # Lấy danh sách link đã tồn tại để tránh trùng lặp
    existing_links = set(worksheet.col_values(3)[1:]) # Cột 3 là Link, bỏ header
    
    new_items = []
    page = 1
    has_items = True

    while has_items:
        current_url = f"{START_URL}&page={page}" if page > 1 else START_URL
        print(f"Dang cào trang: {page} - {current_url}")
        driver.get(current_url)
        
        try:
            # Đợi list items load. Dựa vào class 'a14axl8t' trong HTML bạn cung cấp
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t"))
            )
            
            # Lấy tất cả các thẻ li là item
            items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
            
            if not items:
                print("Không tìm thấy items nào nữa.")
                has_items = False
                break

            items_found_on_page = 0
            
            for item in items:
                try:
                    # Link
                    link_el = item.find_element(By.TAG_NAME, "a")
                    link = link_el.get_attribute("href")
                    if not link.startswith("http"):
                        link = BASE_URL + link
                    
                    # Nếu link đã có trong sheet thì bỏ qua (cũ)
                    if link in existing_items_check: # Dùng set check cho nhanh
                        continue
                        
                    existing_items_check.add(link) # Add vào để loop sau ko trùng
                    
                    # Title (trong h3)
                    try:
                        title = item.find_element(By.CSS_SELECTOR, "h3").text
                    except:
                        title = link_el.get_attribute("title") or "No Title"

                    # Price
                    try:
                        price = item.find_element(By.CSS_SELECTOR, "span.bfe6oav").text # Class chứa giá
                    except:
                        price = "Thỏa thuận"
                        
                    # Time
                    try:
                        time_posted = item.find_element(By.CSS_SELECTOR, "span.c1u6gyxh.tx5yyjc").text
                    except:
                        time_posted = "N/A"

                    # Location
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

                except Exception as e:
                    print(f"Lỗi parse 1 item: {e}")
                    continue
            
            if items_found_on_page == 0 and page > 1:
                # Nếu trang này ko có item mới nào (toàn trùng), có thể dừng sớm
                # Nhưng để chắc chắn, ta chỉ dừng khi không tìm thấy element li
                pass

            page += 1
            time.sleep(2) # Nghỉ nhẹ

        except Exception as e:
            print(f"Dừng lại tại trang {page}. Lý do: Không thấy list hàng hoặc hết trang. ({e})")
            has_items = False

    driver.quit()
    
    # Xử lý dữ liệu mới
    if new_items:
        print(f"Tìm thấy {len(new_items)} món mới.")
        # Đảo ngược để món cũ nhất trong đám mới lên trước (giữ thứ tự thời gian)
        new_items.reverse()
        
        rows_to_add = []
        for item in new_items:
            # Gửi Tele
            send_telegram_alert(item)
            # Chuẩn bị data ghi sheet
            rows_to_add.append([
                item["title"],
                item["price"],
                item["link"],
                item["time"],
                item["location"],
                item["scraped_at"]
            ])
        
        # Ghi vào sheet (batch update cho nhanh)
        worksheet.append_rows(rows_to_add)
    else:
        print("Không có món hàng nào mới.")

# Biến tạm để check duplicate trong runtime
existing_items_check = set()

if __name__ == "__main__":
    # Load lại existing links từ sheet vào set trước khi chạy
    try:
        ws = connect_google_sheet()
        existing_items_check = set(ws.col_values(3)[1:])
    except:
        pass
        
    scrape_data()

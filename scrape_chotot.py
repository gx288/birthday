# Thêm vào phần đầu (CẤU HÌNH)
HEADERS = ["STT", "Title", "Price", "Link", "Time Posted", "Location", "Seller", "Views", "Hidden"]

# Sửa lại connect_google_sheet
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
        worksheet.append_row(HEADERS)
        log("Tạo sheet & header mới")

    # Đảm bảo đúng header và đủ cột
    current_headers = worksheet.row_values(1)
    if current_headers != HEADERS:
        worksheet.update("A1:I1", [HEADERS])
        log("Đã cập nhật header chuẩn")

    if worksheet.col_count < 9:
        worksheet.resize(cols=9)

    return worksheet


# Trong scrape_data(), thay phần xử lý dữ liệu và sort như sau:

def scrape_data():
    log("🚀 BẮT ĐẦU QUÉT CHỢ TỐT - Nhạc cụ Hà Nội ≤ 2.1tr")
    worksheet = connect_google_sheet()

    # Đọc dữ liệu hiện tại (từ dòng 2 trở đi)
    try:
        all_values = worksheet.get_all_values()
        if len(all_values) <= 1:
            existing_data = []
        else:
            existing_data = all_values[1:]  # bỏ header

        # Tạo map link -> (row_index, stt, hidden)
        link_info = {}
        for i, row in enumerate(existing_data, start=2):
            if len(row) >= 4 and row[3].strip():  # cột Link (D)
                link = row[3].strip()
                stt = row[0].strip() if len(row) > 0 else ""
                hidden = row[8].strip() if len(row) > 8 else ""
                link_info[link] = {"row": i, "stt": stt, "hidden": hidden}
        existing_links = set(link_info.keys())
        log(f"Đọc {len(existing_links)} tin cũ từ sheet")
    except Exception as e:
        log(f"Lỗi đọc sheet: {e}")
        existing_links = set()
        link_info = {}

    driver = setup_driver()
    total_new = 0
    total_updated = 0
    page = 1
    consecutive_empty = 0

    new_items_this_run = []  # Lưu các item mới + tin cũ còn xuất hiện để sort lại

    while page <= MAX_PAGES:
        url = START_URL if page == 1 else f"{START_URL}&page={page}"
        log(f"Trang {page} → {url}")

        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.a14axl8t")))
        except Exception as e:
            log(f"Load trang {page} lỗi: {e}")
            if page_has_no_results(driver):
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_PAGES)
            continue

        if page_has_no_results(driver):
            break

        items = driver.find_elements(By.CSS_SELECTOR, "li.a14axl8t")
        log(f"Trang {page}: Tìm thấy {len(items)} tin")

        current_page_stt = 1  # Đánh STT lại từ 1 cho mỗi page mới

        batch_updates = []
        page_new_rows = []

        for item_el in items:
            data = extract_item_data(item_el, page)
            if not data:
                continue

            link = data["link"]

            images = []
            if link not in existing_links:
                images = get_images_from_detail(link)
                send_telegram_with_media(data, images)
                total_new += 1

            # Chuẩn bị dòng dữ liệu
            row_data = [
                "",                    # STT - sẽ điền sau khi sort
                data["title"],
                data["price"],
                link,
                data["time"],
                data["location"],
                data["seller"],
                str(data["views"]),
                str(page)              # Hidden = page hiện tại nếu còn xuất hiện
            ]

            if link in existing_links:
                # Tin cũ còn xuất hiện → cập nhật views & hidden
                row_num = link_info[link]["row"]
                batch_updates.append({
                    "range": f"H{row_num}",  # Views
                    "values": [[str(data["views"])]]
                })
                batch_updates.append({
                    "range": f"I{row_num}",  # Hidden
                    "values": [[str(page)]]
                })
                total_updated += 1
            else:
                page_new_rows.append(row_data)
                existing_links.add(link)

            # Lưu lại để sort sau (cả mới lẫn cũ còn xuất hiện)
            new_items_this_run.append({
                "page": page,
                "stt_on_page": current_page_stt,
                "data": row_data,
                "link": link
            })

            current_page_stt += 1

        # Batch update views + hidden cho tin cũ
        if batch_updates:
            worksheet.batch_update(batch_updates)
            log(f"Batch update {len(batch_updates)//2} tin cũ trang {page}")

        if not page_new_rows and not batch_updates:
            consecutive_empty += 1
        else:
            consecutive_empty = 0

        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    driver.quit()

    # ── SORT LẠI TOÀN BỘ SHEET ──────────────────────────────────────────────
    log("Bắt đầu sắp xếp lại toàn bộ sheet...")

    # Đánh STT và chuẩn bị danh sách cuối
    final_rows = []
    for item in sorted(new_items_this_run, key=lambda x: (x["page"], x["stt_on_page"])):
        # Đánh STT theo thứ tự sau khi sort
        stt = len(final_rows) + 1
        row = item["data"].copy()
        row[0] = str(stt)  # cột STT
        final_rows.append(row)

    # Đánh dấu Hidden cho các tin cũ không còn xuất hiện
    current_links = {item["link"] for item in new_items_this_run}
    for link, info in link_info.items():
        if link not in current_links:
            # Tin cũ không còn → đánh Hidden
            batch_updates.append({
                "range": f"I{info['row']}",
                "values": [["Hidden"]]
            })

    # Thực hiện batch update các tin hidden trước
    if batch_updates:
        worksheet.batch_update(batch_updates)

    # Xóa toàn bộ dữ liệu cũ (giữ header)
    worksheet.clear()

    # Viết lại header
    worksheet.append_row(HEADERS)

    # Viết toàn bộ dữ liệu đã sort
    if final_rows:
        worksheet.append_rows(final_rows)
        log(f"Đã ghi lại {len(final_rows)} dòng đã sort (page tăng dần → STT tăng dần)")

    log(f"Hoàn thành: +{total_new} mới | ↑{total_updated} cập nhật | Tổng tin: {len(final_rows)}")

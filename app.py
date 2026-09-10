import streamlit as st
import os
import json
import datetime
import re
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread

# =========================================================
# 專屬 ID 設定
# =========================================================
DRIVE_FOLDER_ID = "1-ewRQNshKqfYx5dXv6JGqKOp1zaWcxOl"
SHEET_ID = "1NWUmwzsJGGAyVQ1vPXG-pKNvJvbR01vuL32OrZOqnrw"
# =========================================================

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

def authenticate_google():
    """從 Streamlit Cloud Secrets 讀取 Google 憑證"""
    try:
        # 從雲端 Secrets 讀取憑證資訊
        token_info = dict(st.secrets["google_oauth"])
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        return creds
    except Exception as e:
        st.error(f"❌ Google 驗證失敗，請檢查 Streamlit Secrets 設定。錯誤: {e}")
        return None

def extract_file_id(url):
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None

def check_file_exists(drive_service, file_id):
    try:
        file = drive_service.files().get(fileId=file_id, fields='trashed').execute()
        return not file.get('trashed', False)
    except Exception:
        return False

def main():
    st.set_page_config(page_title="商品攝影建檔系統", page_icon="📸", layout="centered")
    st.title("📦 商品攝影自動建檔系統")

    creds = authenticate_google()
    if not creds:
        return

    try:
        drive_service = build('drive', 'v3', credentials=creds)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        st.error(f"❌ 連線 Google API 失敗: {e}")
        return

    tab1, tab2 = st.tabs(["📸 新增商品建檔", "🔄 雲端狀態同步/清理"])

    # ---------------- 頁籤 1: 新增商品建檔 ----------------
    with tab1:
        color_options = {
            "🔴 紅點 (RED)": "RED", 
            "🔵 藍點 (BLU)": "BLU", 
            "🟢 綠點 (GRN)": "GRN"
        }
        selected_color = st.selectbox("1️⃣ 選擇現場圓點標籤顏色", list(color_options.keys()))
        prefix = color_options[selected_color]

        uploaded_files = st.file_uploader(
            "2️⃣ 拍攝或上傳商品照片 (點擊可開啟相機或選擇多張照片)", 
            type=['jpg', 'jpeg', 'png'], 
            accept_multiple_files=True
        )

        if uploaded_files:
            st.info(f"📸 已選取 {len(uploaded_files)} 張照片")
            if st.button("💾 產生編號並上傳雲端", type="primary"):
                with st.spinner("🚀 處理中，請稍候... (上傳雲端與寫入試算表)"):
                    try:
                        date_str = datetime.datetime.now().strftime("%Y%m%d")
                        
                        all_records = sheet.get_all_values()
                        today_count = sum(1 for row in all_records if len(row) > 0 and row[0] == date_str)
                        serial_number = str(today_count + 1).zfill(3)
                        sku = f"{prefix}-{date_str}-{serial_number}"
                        
                        uploaded_links = []
                        for i, file in enumerate(uploaded_files, start=1):
                            file_ext = file.name.split('.')[-1]
                            new_filename = f"{sku}_{i}.{file_ext}"
                            
                            file_metadata = {
                                'name': new_filename,
                                'parents': [DRIVE_FOLDER_ID]
                            }
                            media = MediaIoBaseUpload(file, mimetype=file.type, resumable=True)
                            uploaded_file = drive_service.files().create(
                                body=file_metadata, 
                                media_body=media, 
                                fields='id, webViewLink'
                            ).execute()
                            
                            uploaded_links.append(uploaded_file.get('webViewLink'))
                        
                        row_data = [date_str, sku, prefix, len(uploaded_files)] + uploaded_links
                        sheet.append_row(row_data)
                        
                        st.success(f"🎉 建檔成功！商品編號：**{sku}**")
                        st.balloons()
                        
                    except Exception as e:
                        st.error(f"❌ 發生錯誤: {e}")

    # ---------------- 頁籤 2: 雲端狀態同步/清理 ----------------
    with tab2:
        st.markdown("### 🧹 雲端照片精密同步")
        st.write("系統會逐張比對該商品的所有圖片狀態。")
        
        if st.button("🔄 開始逐張檢查與同步"):
            with st.spinner("🔍 正在檢查所有圖片狀態..."):
                try:
                    rows = sheet.get_all_values()
                    if len(rows) <= 1:
                        st.info("目前試算表中沒有商品資料。")
                    else:
                        changed_count = 0
                        deleted_rows_count = 0
                        
                        for index in range(len(rows), 1, -1):
                            row = rows[index - 1]
                            if len(row) >= 5:
                                date_str = row[0]
                                sku = row[1]
                                prefix = row[2]
                                raw_links = row[4:]
                                
                                valid_links = []
                                for url in raw_links:
                                    if url.strip():
                                        file_id = extract_file_id(url)
                                        if file_id and check_file_exists(drive_service, file_id):
                                            valid_links.append(url)
                                
                                original_valid_count = len([u for u in raw_links if u.strip()])
                                
                                if len(valid_links) != original_valid_count:
                                    changed_count += 1
                                    if len(valid_links) == 0:
                                        sheet.delete_rows(index)
                                        deleted_rows_count += 1
                                        st.warning(f"🗑️ 商品 **{sku}** 照片已全數被刪除，已移除整筆紀錄。")
                                    else:
                                        sheet.batch_clear([f"A{index}:Z{index}"])
                                        new_row = [date_str, sku, prefix, len(valid_links)] + valid_links
                                        sheet.update(range_name=f"A{index}", values=[new_row])
                                        st.info(f"✏️ 商品 **{sku}** 照片已更新剩餘 {len(valid_links)} 張。")
                        
                        if changed_count == 0:
                            st.success("✅ 檢查完畢！所有商品的照片連結皆完整存在。")
                        else:
                            st.success(f"🎉 同步完成！共修正 {changed_count} 筆紀錄。")
                except Exception as e:
                    st.error(f"檢查時發生錯誤: {e}")

if __name__ == "__main__":
    main()

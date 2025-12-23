from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "service_account.json"

# Your sheet + tab
SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"
VIDEOS_SHEET_NAME = "videos"


def main():
    print("Authorizing Google Sheets...")
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    ws = sh.worksheet(VIDEOS_SHEET_NAME)

    now = datetime.utcnow().isoformat()
    row = [now, "TEST_NICHE", "test_video_id", "https://example.com", "@creator", "Test title", "Test desc", "#test", 123, 45, 6]

    print("Appending test row:", row)
    ws.append_row(row, value_input_option="RAW")
    print("✅ Done. Check the 'videos' tab for a new row.")


if __name__ == "__main__":
    main()


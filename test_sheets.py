# test_sheets.py

from datetime import datetime
from sheets_client import get_videos_sheet

def main():
    ws = get_videos_sheet()

    row = [
        datetime.utcnow().isoformat(),
        "test-niche",
        "test-video-id",
        "https://www.tiktok.com/@test/video/123",
        "test_creator",
        "This is a test title",
        "This is a test description",
        "#test,#example",
        1234,   # views
        100,    # likes
        5,      # comments
        2,      # shares
    ]

    ws.append_row(row, value_input_option="RAW")
    print("✅ Row appended to 'videos' tab.")

if __name__ == "__main__":
    main()


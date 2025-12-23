# sheets_client.py

import gspread
from google.oauth2.service_account import Credentials
from trends_config import SHEET_ID, SERVICE_ACCOUNT_FILE

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_client():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    return client


def get_workbook():
    client = get_client()
    return client.open_by_key(SHEET_ID)


def get_videos_sheet():
    return get_workbook().worksheet("videos")


def get_hashtags_sheet():
    return get_workbook().worksheet("hashtags")


def get_niches_sheet():
    return get_workbook().worksheet("niches")


import asyncio
from playwright.async_api import async_playwright

TIKTOK_EMAIL = "YOUR_EMAIL_HERE"
TIKTOK_PASSWORD = "YOUR_PASSWORD_HERE"

async def main():
    async with async_playwright() as p:
        # Run headful so you can see what’s happening
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        
        # New clean context (no cookies yet)
        context = await browser.new_context()
        page = await context.new_page()

        # Go to TikTok login page
        await page.goto("https://www.tiktok.com/login", wait_until="networkidle")

        # ⚠️ TikTok shows different login flows.
        # If email/password form is visible, try to fill it.
        try:
            # This selector may change; adjust if needed
            await page.click("text=Use phone / email / username", timeout=5000)
        except:
            pass

        try:
            await page.click("text=Log in with email or username", timeout=5000)
        except:
            pass

        # Try filling email + password
        try:
            await page.fill('input[type="text"], input[name="username"], input[name="email"]', TIKTOK_EMAIL)
            await page.fill('input[type="password"]', TIKTOK_PASSWORD)
            await page.click('button:has-text("Log in")')
        except Exception as e:
            print("Could not auto-fill login form, do it manually in the window.")
            print("Error:", e)

        # ⏳ Give you time to solve captchas / 2FA / whatever
        print(">>> Log in manually if needed. You have 90 seconds...")
        await page.wait_for_timeout(90_000)

        # Save logged-in cookies + localStorage to a file
        await context.storage_state(path="tiktok_state.json")
        print("✅ Saved TikTok login state to tiktok_state.json")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())


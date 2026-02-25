import asyncio
import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

EMAIL                   = os.getenv("EMAIL")
PASSWORD                = os.getenv("PASSWORD")
LOGIN_URL               = os.getenv("LOGIN_URL")
TIMELINE_URL            = os.getenv("TIMELINE_URL")
SELECTOR_TIMELINE       = os.getenv("SELECTOR_TIMELINE")
SELECTOR_EMAIL          = os.getenv("SELECTOR_LOGIN_EMAIL")
SELECTOR_PASSWORD       = os.getenv("SELECTOR_LOGIN_PASSWORD")
SELECTOR_SUBMIT         = os.getenv("SELECTOR_LOGIN_BUTTON")
SELECTOR_CHAPTER        = os.getenv("SELECTOR_CHAPTER", "section")
SELECTOR_CHAPTER_TITLE  = os.getenv("SELECTOR_CHAPTER_TITLE", "h3")
SELECTOR_LESSON_CARD    = os.getenv("SELECTOR_LESSON_CARD")
SELECTOR_LESSON_TITLE   = os.getenv("SELECTOR_LESSON_TITLE")
SELECTOR_BTN_CHECKPOINT = os.getenv("SELECTOR_BTN_CHECKPOINT")
SELECTOR_BTN_LESSON     = os.getenv("SELECTOR_BTN_LESSON")
API_RESPONSE_PATTERN    = os.getenv("API_RESPONSE_PATTERN")
LOGIN_URL_FRAGMENT      = os.getenv("LOGIN_URL_FRAGMENT", "/login")
OUTPUT_DIR              = Path(os.getenv("OUTPUT_DIR", "../lessons"))
SESSION_FILE            = Path(os.getenv("SESSION_FILE", "../session.json"))
SKIP_TYPES              = [s.strip().upper() for s in os.getenv("SKIP_TYPES", "").split(",") if s.strip()]

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        context = await browser.new_context()

        # ── LOAD SAVED SESSION ─────────────────────────────────────────
        if SESSION_FILE.exists():
            print("🍪 Loading saved session...")
            cookies = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)

        page = await context.new_page()
        await page.goto(TIMELINE_URL)

        # ── CHECK AUTH ────────────────────────────────────────────────
        print("⏳ Checking session...")
        try:
            await page.wait_for_selector(SELECTOR_TIMELINE, timeout=10000)
            print("✅ Session valid, already logged in!\n")

        except:
            print("🔐 Session invalid, logging in...")
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
                print("🗑️  Deleted stale session file")

            await page.goto(LOGIN_URL)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            await page.fill(SELECTOR_EMAIL, EMAIL)
            await page.fill(SELECTOR_PASSWORD, PASSWORD)
            await page.click(SELECTOR_SUBMIT)
            print("✅ Submitted - solve CAPTCHA manually...")

            await page.wait_for_url(lambda url: LOGIN_URL_FRAGMENT not in url, timeout=600000)
            print("✅ Logged in!")

            cookies = await context.cookies()
            SESSION_FILE.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
            print("🍪 New session saved\n")

            await page.goto(TIMELINE_URL)
            await page.wait_for_selector(SELECTOR_TIMELINE)

        print("✅ Timeline loaded\n")

        chapters      = page.locator(f"{SELECTOR_TIMELINE} {SELECTOR_CHAPTER}")
        chapter_count = await chapters.count()
        print(f"📚 {chapter_count} chapters\n")

        for chap_idx in range(chapter_count):
            chapter    = chapters.nth(chap_idx)
            chap_title = await chapter.locator(SELECTOR_CHAPTER_TITLE).first.inner_text()

            safe_chap  = chap_title.replace(' ', '_').replace('/', '-').replace(':', '')
            chap_dir   = OUTPUT_DIR / f"ch{chap_idx+1:02}_{safe_chap}"
            # chap_dir.mkdir(exist_ok=True)
            chap_dir.mkdir(parents=True, exist_ok=True)
            print(f"── Chapter {chap_idx+1}: {chap_title} → ./{chap_dir}/")

            lesson_cards = chapter.locator(SELECTOR_LESSON_CARD)
            lesson_count = await lesson_cards.count()
            print(f"   {lesson_count} lessons")

            for lesson_idx in range(lesson_count):
                card      = lesson_cards.nth(lesson_idx)
                title     = await card.locator(SELECTOR_LESSON_TITLE).inner_text()
                card_text = (await card.inner_text()).upper()

                # ── Skip unwanted lesson types ─────────────────────────
                if any(skip in card_text for skip in SKIP_TYPES):
                    matched = next(s for s in SKIP_TYPES if s in card_text)
                    print(f"   ⏭️  [{lesson_idx+1}] {title} ({matched}) — skipped")
                    continue

                is_checkpoint = "CHECKPOINT" in card_text
                print(f"   {'🏁' if is_checkpoint else '→'} [{lesson_idx+1}] {title}...", end=" ", flush=True)

                # 1. Click card
                await card.click()

                # 2. Wait for correct popup button
                popup_btn = page.locator(SELECTOR_BTN_CHECKPOINT if is_checkpoint else SELECTOR_BTN_LESSON)
                await popup_btn.first.wait_for(state="visible")
                btn_text = await popup_btn.first.inner_text()

                # 3. Capture JSON + click
                async with page.expect_response(
                    lambda r: API_RESPONSE_PATTERN in r.url and r.status == 200
                ) as response_info:
                    await popup_btn.first.click()

                # 4. Save JSON
                try:
                    response   = await response_info.value
                    data       = await response.json()
                    safe_title = sanitize_filename(title[:40].replace(' ', '_').replace('/', '-'))
                    prefix     = "checkpoint" if is_checkpoint else f"l{lesson_idx+1:02}"
                    filename   = chap_dir / f"{prefix}_{safe_title}.json"
                    filename.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"({btn_text} ✅) saved {filename.name}")
                except Exception as e:
                    print(f"({btn_text} ✅) ❌ {e}")

                # 5. Back to timeline
                await page.goto(TIMELINE_URL)
                await page.wait_for_selector(SELECTOR_TIMELINE)

        total = sum(1 for _ in OUTPUT_DIR.rglob("*.json"))
        print(f"\n🎉 Done! {total} files saved in ./{OUTPUT_DIR}/")
        input("Press Enter to close...")
        await browser.close()

asyncio.run(scrape())

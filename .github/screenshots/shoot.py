# Temporary (UI refresh review): signs in and screenshots the main pages in some colour themes.
import json
import os
import subprocess

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = "shots"
URLS = json.load(open("shot-urls.json"))
ALL = ["home", "diary-subjects", "my-settings", "fees-dashboard", "fees-memos", "fees-memo-new", "fees-outstanding", "inv-overview",
       "inv-holdings", "inv-investment"]
SOME = ["home", "fees-dashboard", "inv-overview", "diary-subjects"]
os.makedirs(OUT, exist_ok=True)


def set_theme(theme):
    subprocess.run(["python", "manage.py", "shell", "-c",
                    f"from accounts.models import User; User.objects.filter(username='shots').update(colour_theme='{theme}')"], check=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1360, "height": 900})
    page.goto(BASE + URLS["login"])
    page.fill("input[name=username]", "shots")
    page.fill("input[name=password]", "shots-pass-123")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    for theme in ("oxblood", "navy", "teal"):
        set_theme(theme)
        for name in (ALL if theme == "oxblood" else SOME):
            try:
                page.goto(BASE + URLS[name], wait_until="networkidle")
                page.screenshot(path=f"{OUT}/{theme}-{name}.png", full_page=True)
                print("ok", theme, name, page.url)
                if name == "diary-subjects" and theme == "oxblood":
                    link = page.locator("main a:has-text('TEST SAMPLE')").first
                    if link.count():
                        link.click()
                        page.wait_for_load_state("networkidle")
                        page.screenshot(path=f"{OUT}/{theme}-diary-reading.png", full_page=True)
                        print("ok", theme, "diary-reading", page.url)
            except Exception as exc:  # keep going: one broken page must not hide the rest
                print("FAILED", theme, name, exc)
    browser.close()

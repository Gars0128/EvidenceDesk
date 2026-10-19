"""Browser smoke check against a disposable UI instance, never a personal corpus."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--channel", default="msedge", help="Installed browser channel, or chromium")
    args = parser.parse_args()
    screenshots = ROOT / "docs" / "images"
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url)
        page.get_by_role("heading", name="Documents", exact=True).wait_for()
        page.locator("#files").set_input_files([
            str(ROOT / "evaluation/corpus/aurora_hotel.txt"),
            str(ROOT / "evaluation/corpus/borealis_hotel.txt"),
        ])
        page.get_by_role("button", name="Upload documents", exact=True).click()
        page.wait_for_function("!document.querySelector('#upload-button').disabled", timeout=180_000)
        assert page.locator(".document").filter(has_text="aurora_hotel.txt").count() == 1
        assert page.locator(".document .badge").filter(has_text="Search ready").count() >= 2
        page.get_by_text("Search options", exact=True).click()
        page.locator("#mode").select_option("lexical")
        page.get_by_label("Your question", exact=True).fill("Aurora free cancellation")
        page.get_by_role("button", name="Inspect search results", exact=True).click()
        page.locator("#retrieved-fragments .fragment").first.wait_for(timeout=30_000)
        assert "aurora_hotel.txt" in page.locator("#retrieved-fragments").inner_text()
        page.get_by_role("button", name="Ask documents").click()
        page.get_by_text("Sources attached", exact=True).wait_for(timeout=240_000)
        page.locator(".citation summary").first.click()
        assert page.locator(".citation blockquote").first.inner_text().strip()
        page.screenshot(path=str(screenshots / "ui-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "ui-mobile.png"), full_page=True)
        print("PASS: real upload, indexing, retrieval, answer, citation expansion, and responsive layout", flush=True)

        page.locator("#files").set_input_files({"name": "broken.pdf", "mimeType": "application/pdf", "buffer": b"not a valid pdf"})
        page.get_by_role("button", name="Upload documents", exact=True).click()
        page.wait_for_function("!document.querySelector('#upload-button').disabled", timeout=30_000)
        assert "broken.pdf" in page.locator("#upload-status").inner_text()
        assert page.locator(".document").filter(has_text="broken.pdf").locator(".badge.failed").count() == 1

        malicious = "<img src=x onerror=alert('xss')>"
        response = {
            "answer": malicious, "abstained": False, "model": "test model", "elapsed_ms": 1,
            "warnings": [], "claims": [{"text": malicious, "citations": [{"filename": malicious, "page_number": 1, "quote": malicious}]}],
            "retrieval": {"mode": "lexical", "reranked": False, "elapsed_ms": 1, "results": [], "warnings": []},
        }
        page.route("**/api/ask", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(response)))
        page.get_by_role("button", name="Ask documents").click()
        page.wait_for_function("!document.querySelector('#ask-button').disabled")
        assert malicious in page.locator("#answer").inner_text()
        assert page.locator("#answer img").count() == 0
        assert not errors, errors
        print("PASS: corrupt upload feedback and model/document text rendered without HTML execution", flush=True)
        browser.close()


if __name__ == "__main__":
    main()

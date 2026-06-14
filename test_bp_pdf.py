"""HTML 商业计划书转 PDF。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright

HTML = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/frontend/business-plan.html")
PDF = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/docs/report/business-plan.pdf")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(f"file://{HTML}")
        await page.wait_for_load_state("networkidle")
        await page.pdf(
            path=str(PDF),
            width="1280px",
            height="905px",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        await browser.close()
    print(f"✅ PDF: {PDF} ({PDF.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())

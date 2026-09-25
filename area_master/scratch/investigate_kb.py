import asyncio
import json
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        api_list = []

        async def handle_response(response):
            url = response.url
            if any(k in url for k in ["api", "land", "search", "complex", "price", "hscm"]):
                try:
                    ctype = response.headers.get("content-type", "")
                    if "json" in ctype:
                        body = await response.text()
                        api_list.append({
                            "url": url,
                            "method": response.request.method,
                            "status": response.status,
                            "body_sample": body[:300]
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        print("Navigating to https://kbland.kr/map ...")
        await page.goto("https://kbland.kr/map", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        print("Current URL:", page.url)

        # 검색창 찾기
        inputs = await page.query_selector_all("input")
        print(f"Found {len(inputs)} inputs on page.")
        for idx, inp in enumerate(inputs):
            ph = await inp.get_attribute("placeholder")
            typ = await inp.get_attribute("type")
            cls = await inp.get_attribute("class")
            print(f"Input [{idx}]: type={typ}, placeholder={ph}, class={cls}")

        # '대연SK뷰힐스' 검색 시도
        search_box = None
        for inp in inputs:
            ph = (await inp.get_attribute("placeholder")) or ""
            if "검색" in ph or "지역" in ph or "단지" in ph:
                search_box = inp
                break

        if not search_box and inputs:
            search_box = inputs[0]

        if search_box:
            print("Typing search query...")
            await search_box.click()
            await search_box.fill("대연SK뷰힐스")
            await asyncio.sleep(1)
            await search_box.press("Enter")
            await asyncio.sleep(3)

        print(f"Total API responses captured: {len(api_list)}")
        with open("scratch/kb_api_captured.json", "w", encoding="utf-8") as f:
            json.dump(api_list, f, ensure_ascii=False, indent=2)

        for item in api_list:
            print(f"[{item['status']}] {item['method']} {item['url']}")
            print(f"   Sample: {item['body_sample'][:150]}...")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

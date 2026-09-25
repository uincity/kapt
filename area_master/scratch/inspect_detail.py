import asyncio
import json
from playwright.async_api import async_playwright

async def inspect_complex_detail():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        api_calls = []
        async def on_resp(resp):
            url = resp.url
            if "api.kbland.kr" in url and any(k in url for k in ["complex", "price", "hscm", "pyeong", "type", "area", "detail", "info"]):
                try:
                    ctype = resp.headers.get("content-type", "")
                    if "json" in ctype:
                        body = await resp.text()
                        api_calls.append({
                            "url": url,
                            "method": resp.request.method,
                            "data": json.loads(body)
                        })
                except Exception:
                    pass

        page.on("response", on_resp)

        # 31369 단지 상세로 접근 시도
        # kbland.kr에서 아파트 상세는 어떻게 URL이 구성되는지 확인
        # 테스트 1: https://kbland.kr/map?xy=35.1368486,129.0938609,17&complex=31369
        # 또는 search 페이지에서 대연SK뷰힐스를 직접 클릭
        print("Navigating to search page...")
        await page.goto("https://kbland.kr/search?tabIdx=0", wait_until="networkidle")
        await asyncio.sleep(2)

        inp = await page.query_selector("input.form-control")
        if inp:
            await inp.fill("대연SK뷰힐스")
            await asyncio.sleep(1)
            await inp.press("Enter")
            await asyncio.sleep(2)

            # 검색 결과에서 '대연SK뷰힐스' 클릭
            # 첫 번째 아파트 항목 클릭
            print("Clicking complex item...")
            item = await page.query_selector("text=대연SK뷰힐스")
            if item:
                await item.click()
                await asyncio.sleep(5)

        print("Final URL:", page.url)
        print(f"Captured {len(api_calls)} complex detail APIs")
        with open("scratch/kb_detail_calls.json", "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)

        for item in api_calls:
            print(f"[{item['method']}] {item['url']}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_complex_detail())

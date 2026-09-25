import asyncio
import json
from playwright.async_api import async_playwright

async def search_complex():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        api_calls = []
        async def on_resp(resp):
            url = resp.url
            if "api.kbland.kr" in url:
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

        await page.goto("https://kbland.kr/search?tabIdx=0", wait_until="networkidle")
        await asyncio.sleep(2)

        inp = await page.query_selector("input.form-control")
        print("Input found:", bool(inp))
        if inp:
            await inp.fill("대연SK뷰힐스")
            await asyncio.sleep(1)
            await inp.press("Enter")
            await asyncio.sleep(3)

        print(f"Captured {len(api_calls)} API calls")
        with open("scratch/kb_search_calls.json", "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)

        for item in api_calls:
            print(f"[{item['method']}] {item['url']}")
            preview = json.dumps(item["data"], ensure_ascii=False)[:200]
            print(f"  Body preview: {preview}")

        # DOM 결과 요소 확인
        results = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('.search-result, .list-group-item, li, div'))
                .filter(el => (el.innerText || '').includes('대연SK뷰힐스'))
                .slice(0, 5)
                .map(el => ({
                    tag: el.tagName,
                    cls: el.className,
                    text: (el.innerText || '').slice(0, 100)
                }));
        }''')
        print("DOM search result elements:", results)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(search_complex())

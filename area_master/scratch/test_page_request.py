import asyncio
import urllib.parse
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        await page.goto('https://kbland.kr', wait_until='domcontentloaded')
        
        url = 'https://api.kbland.kr/land-complex/serch/intgraSerch?' + urllib.parse.urlencode({
            '검색설정명': 'SRC_NTOTAL',
            '검색키워드': '대연동 대연SK뷰힐스',
            '출력갯수': '10',
            '페이지설정값': '1'
        })
        resp = await page.request.get(url, headers={'Referer': 'https://kbland.kr/'})
        print('Status:', resp.status)
        data = await resp.json()
        hscm = data.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
        print(f'HSCM candidates: {len(hscm)}')
        for h in hscm:
            print(f"ID: {h.get('COMPLEX_NO')}, Name: {h.get('HSCM_NM')}, Addr: {h.get('BUBADDR')}, Households: {h.get('THS_NUM')}")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test())

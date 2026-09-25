"""
Playwright persistent browser context 관리 모듈.

왜 persistent context인가:
- KB부동산 로그인 세션을 유지하여 재로그인 없이 수집 가능.
- 사용자가 직접 로그인 → 쿠키/세션이 프로필 디렉터리에 저장.
- 이후 실행에서 기존 프로필 재사용.
- ID/PW를 코드에 저장하지 않음.
"""
from __future__ import annotations

import logging
import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from .config import BROWSER_PROFILE_DIR, KB_PAGE_LOAD_TIMEOUT_MS

logger = logging.getLogger(__name__)

# KB부동산 주요 URL
KB_MAIN_URL = "https://kbland.kr"
KB_SEARCH_URL = "https://kbland.kr"
KB_LOGIN_CHECK_INDICATOR = "마이페이지"  # 로그인 상태에서 보이는 텍스트


class KBBrowser:
    """
    KB부동산 Playwright 브라우저 세션 관리.

    - launch(): persistent context로 Chromium 실행
    - ensure_logged_in(): 로그인 상태 확인/대기
    - close(): 브라우저 종료
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def launch(self) -> Page:
        """
        Playwright persistent context를 시작한다.
        기존 프로필이 있으면 세션 재사용, 없으면 새로 생성.
        """
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        profile_path = str(BROWSER_PROFILE_DIR)

        self._playwright = await async_playwright().start()

        # persistent context: 쿠키/세션이 프로필 디렉터리에 자동 저장됨
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=self.headless,
            viewport={"width": 1400, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            # 자동화 감지 방지를 위한 최소한의 설정
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        # 기존 탭 사용 또는 새 탭 생성
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        self._page.set_default_timeout(KB_PAGE_LOAD_TIMEOUT_MS)
        logger.info("KB 브라우저 시작 (headless=%s, profile=%s)", self.headless, profile_path)

        return self._page

    async def ensure_logged_in(self) -> bool:
        """
        KB부동산 로그인 상태를 확인한다.

        - 로그인 되어 있으면 True 반환.
        - 로그인 안 되어 있으면 KB 메인으로 이동 후 사용자 로그인을 대기.
        """
        if not self._page:
            raise RuntimeError("브라우저가 시작되지 않았습니다. launch()를 먼저 호출하세요.")

        page = self._page

        # KB 메인 페이지로 이동
        try:
            await page.goto(KB_MAIN_URL, wait_until="domcontentloaded", timeout=KB_PAGE_LOAD_TIMEOUT_MS)
        except Exception as e:
            logger.warning("KB 메인 페이지 로드 실패: %s", e)

        # 잠시 대기 후 로그인 상태 확인
        await asyncio.sleep(2)

        # 로그인 상태 확인: 페이지에 '마이페이지' 또는 '로그아웃' 텍스트 존재 여부
        is_logged_in = await self._check_login_status(page)

        if is_logged_in:
            logger.info("KB부동산 로그인 상태 확인됨")
            return True

        # 로그인 안 됨 → 사용자 로그인 대기
        logger.warning("=" * 50)
        logger.warning("[LOGIN REQUIRED] KB부동산 로그인이 필요합니다.")
        logger.warning("브라우저에서 직접 KB부동산에 로그인해 주세요.")
        logger.warning("로그인 완료 후 자동으로 감지합니다.")
        logger.warning("=" * 50)

        print("\n" + "=" * 50)
        print("[LOGIN REQUIRED] KB부동산 로그인이 필요합니다.")
        print("브라우저에서 직접 로그인해 주세요.")
        print("로그인 완료 후 자동으로 감지합니다...")
        print("=" * 50 + "\n")

        # 최대 10초 대기하며 로그인 확인 (필수 아님: 비로그인 상태에서도 API 제공됨)
        max_wait = 10
        interval = 2
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval

            is_logged_in = await self._check_login_status(page)
            if is_logged_in:
                logger.info("KB부동산 로그인 성공 감지! (대기 %d초)", elapsed)
                print(f"\n[OK] KB부동산 로그인 성공! ({elapsed}초 대기)")
                return True

        logger.info("비로그인 상태 확인: KB부동산 공개 API 세션으로 수집을 계속 진행합니다.")
        print("\n[INFO] 비로그인 세션으로 수집을 계속 진행합니다 (KB Land 공개 데이터 모드)")
        return True

    async def _check_login_status(self, page: Page) -> bool:
        """페이지에서 로그인 상태를 확인한다."""
        try:
            # KB Land에서 로그인 후 보이는 요소 확인
            # 방법 1: '로그아웃' 텍스트 존재
            content = await page.content()
            if "로그아웃" in content or "마이페이지" in content:
                return True

            # 방법 2: 로그인 버튼이 없으면 로그인 상태
            login_btn = await page.query_selector('text="로그인"')
            if login_btn is None:
                # 로그인 버튼이 없으면 이미 로그인된 것일 수 있음
                # 하지만 페이지가 아직 로드되지 않았을 수도 있으므로 추가 확인
                return False

            return False
        except Exception:
            return False

    async def navigate_to_complex(self, kb_complex_id: str) -> Page:
        """
        KB 단지 상세 페이지로 이동한다.

        KB Land URL 패턴: https://kbland.kr/map?xy=...
        또는 단지 상세: https://kbland.kr/complexDetail?complexId=...
        """
        if not self._page:
            raise RuntimeError("브라우저가 시작되지 않았습니다.")

        # KB Land 단지 상세 URL 패턴 (실제 URL은 파일럿에서 확인 후 조정)
        url = f"https://kbland.kr/map?xy=&complex={kb_complex_id}"
        await self._page.goto(url, wait_until="domcontentloaded", timeout=KB_PAGE_LOAD_TIMEOUT_MS)
        await asyncio.sleep(2)  # 페이지 동적 로딩 대기

        return self._page

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("브라우저가 시작되지 않았습니다.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("브라우저가 시작되지 않았습니다.")
        return self._context

    async def close(self) -> None:
        """브라우저를 종료한다. 프로필은 보존됨."""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("KB 브라우저 종료")

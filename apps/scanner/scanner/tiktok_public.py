import json, os, time, sys
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None
from .provider import Provider, PublicAccessLimitedError
from packages.shared.models import CreatorSnapshot, PostMetric

KNOWN_SCRIPT_IDS={"__UNIVERSAL_DATA_FOR_REHYDRATION__","SIGI_STATE","__NEXT_DATA__"}


def _walk(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj,list):
        for v in obj:
            yield from _walk(v)


def _int(v):
    try:
        if v is None or v == "":
            return 0
        return int(float(str(v).replace(",", "")))
    except Exception:
        return 0


def _iso(v):
    try:
        return datetime.fromtimestamp(int(v),tz=timezone.utc).isoformat()
    except Exception:
        return None


class TikTokPublicProvider(Provider):
    """Best-effort reader of JSON embedded in public TikTok pages.

    It does not log in, solve CAPTCHAs, rotate identities, or bypass 403/429.
    """

    def __init__(self):
        self.delay=float(os.getenv('REQUEST_DELAY_SECONDS','2.5'))
        self.timeout=float(os.getenv('REQUEST_TIMEOUT_SECONDS','25'))
        self.max_requests=int(os.getenv('MAX_REQUESTS_PER_RUN','250'))
        self.requests=0
        self.client=httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language':'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
                'Cache-Control':'no-cache',
                'Pragma':'no-cache',
                'Sec-Fetch-Dest':'document',
                'Sec-Fetch-Mode':'navigate',
                'Sec-Fetch-Site':'none',
                'Sec-Fetch-User':'?1',
                'Upgrade-Insecure-Requests':'1',
            },
        )

    def close(self):
        self.client.close()

    def _get(self,url):
        if self.requests>=self.max_requests:
            raise PublicAccessLimitedError('MAX_REQUESTS_PER_RUN reached')
        if self.requests:
            time.sleep(self.delay)
        self.requests+=1
        r=self.client.get(url)
        if r.status_code in (403,429):
            raise PublicAccessLimitedError(
                f'TikTok returned HTTP {r.status_code}; scanner stops instead of bypassing the restriction.'
            )
        r.raise_for_status()
        html=r.text
        # TikTok can return an HTTP 200 WAF/interstitial page instead of profile data.
        low=html.lower()
        # Do not treat the harmless `slardarwaf` string inside normal TikTok
        # JavaScript as a block. Stop only when the returned page actually looks
        # like an interstitial and profile data is absent.
        if (
            ('please wait' in low or 'verify to continue' in low)
            and '__universal_data_for_rehydration__' not in low
        ):
            raise PublicAccessLimitedError('TikTok returned a visible/interstitial access page (HTTP 200).')
        return html

    @staticmethod
    def _json_blobs(html):
        soup=BeautifulSoup(html,'html.parser')
        for script in soup.find_all('script'):
            txt=(script.string or script.get_text() or '').strip()
            sid=script.get('id') or ''
            if not txt or not (txt.startswith('{') or txt.startswith('[')):
                continue
            if sid not in KNOWN_SCRIPT_IDS and len(txt)<100:
                continue
            try:
                yield json.loads(txt)
            except Exception:
                continue

    @staticmethod
    def _universal_detail(blobs):
        """Return TikTok's current SSR profile detail block when present.

        Current public pages normally expose:
        __DEFAULT_SCOPE__["webapp.user-detail"].userInfo.user
        __DEFAULT_SCOPE__["webapp.user-detail"].userInfo.stats / statsV2
        """
        for blob in blobs:
            if not isinstance(blob,dict):
                continue
            scope=blob.get('__DEFAULT_SCOPE__')
            if not isinstance(scope,dict):
                continue
            detail=scope.get('webapp.user-detail')
            if isinstance(detail,dict):
                return detail
        return None

    @staticmethod
    def _creator_candidates(blobs):
        # Fallback for older/alternate TikTok payload shapes.
        found={}
        for blob in blobs:
            for d in _walk(blob):
                h=d.get('uniqueId') or d.get('unique_id')
                if not h or not isinstance(h,str):
                    continue
                stats=d.get('stats') if isinstance(d.get('stats'),dict) else {}
                score=len(d)+len(stats)
                if h not in found or score>found[h][0]:
                    found[h]=(score,d)
        return {k:v[1] for k,v in found.items()}

    @staticmethod
    def _post_from_dict(d, handle=''):
        if not isinstance(d,dict):
            return None
        pid=d.get('id')
        stats=d.get('stats') if isinstance(d.get('stats'),dict) else None
        if not pid or not stats or ('playCount' not in stats and 'play_count' not in stats):
            return None
        author=d.get('author')
        ah=''
        if isinstance(author,dict):
            ah=str(author.get('uniqueId') or author.get('unique_id') or '')
        elif isinstance(author,str):
            ah=author
        if handle and ah and ah.lower()!=handle.lower():
            return None
        return PostMetric(
            str(pid),
            _iso(d.get('createTime') or d.get('create_time')),
            str(d.get('desc') or d.get('description') or ''),
            _int(stats.get('playCount') or stats.get('play_count')),
            _int(stats.get('diggCount') or stats.get('likeCount') or stats.get('digg_count')),
            _int(stats.get('commentCount') or stats.get('comment_count')),
            _int(stats.get('shareCount') or stats.get('share_count')),
        )

    @classmethod
    def _posts(cls,blobs,handle,limit,detail=None):
        posts={}

        # Current SSR payload may expose itemList directly in/near user detail.
        if isinstance(detail,dict):
            for key in ('itemList','item_list','items'):
                seq=detail.get(key)
                if isinstance(seq,list):
                    for d in seq:
                        p=cls._post_from_dict(d,handle)
                        if p:
                            posts[p.post_id]=p

        # Fallback: search all embedded JSON for itemStruct-like objects.
        for blob in blobs:
            for d in _walk(blob):
                p=cls._post_from_dict(d,handle)
                if p:
                    posts[p.post_id]=p

        return sorted(posts.values(),key=lambda p:p.created_at or '',reverse=True)[:limit]

    def _fetch_posts_api(self, user, handle, limit):
        """Best-effort call to TikTok's public web post-list endpoint.

        No login, signing, CAPTCHA solving, token forging or restriction bypassing.
        If the public endpoint refuses the request, return an empty list and keep
        profile metrics usable.
        """
        sec_uid=str(user.get('secUid') or user.get('sec_uid') or '')
        if not sec_uid or limit <= 0:
            return []
        count=max(1,min(int(limit),35))
        url='https://www.tiktok.com/api/post/item_list/'
        params={
            'aid':'1988',
            'app_language':'pl-PL',
            'app_name':'tiktok_web',
            'browser_language':'pl-PL',
            'browser_name':'Mozilla',
            'browser_online':'true',
            'browser_platform':'Win32',
            'channel':'tiktok_web',
            'count':str(count),
            'cursor':'0',
            'device_platform':'web_pc',
            'focus_state':'true',
            'from_page':'user',
            'history_len':'2',
            'is_fullscreen':'false',
            'is_page_visible':'true',
            'os':'windows',
            'priority_region':'PL',
            'referer':'',
            'region':'PL',
            'screen_height':'1080',
            'screen_width':'1920',
            'secUid':sec_uid,
            'tz_name':'Europe/Warsaw',
            'webcast_language':'pl-PL',
        }
        if self.requests>=self.max_requests:
            raise PublicAccessLimitedError('MAX_REQUESTS_PER_RUN reached')
        if self.requests:
            time.sleep(self.delay)
        self.requests+=1
        try:
            r=self.client.get(
                url,
                params=params,
                headers={
                    'Accept':'application/json, text/plain, */*',
                    'Referer':f'https://www.tiktok.com/@{quote(handle)}',
                    'Sec-Fetch-Dest':'empty',
                    'Sec-Fetch-Mode':'cors',
                    'Sec-Fetch-Site':'same-origin',
                },
            )
        except Exception as e:
            print(f'POSTS API WARN @{handle}: request error: {e}',file=sys.stderr)
            return []
        if r.status_code in (403,429):
            print(f'POSTS API LIMITED @{handle}: HTTP {r.status_code}; not bypassing restriction.',file=sys.stderr)
            return []
        if r.status_code != 200:
            print(f'POSTS API WARN @{handle}: HTTP {r.status_code}',file=sys.stderr)
            return []
        try:
            data=r.json()
        except Exception:
            print(f'POSTS API WARN @{handle}: response was not JSON ({len(r.text)} bytes)',file=sys.stderr)
            return []
        status=data.get('status_code')
        if status not in (None,0):
            print(f'POSTS API WARN @{handle}: TikTok status_code={status}',file=sys.stderr)
            return []
        items=data.get('itemList') or data.get('item_list') or []
        out={}
        if isinstance(items,list):
            for d in items:
                p=self._post_from_dict(d,handle)
                if p:
                    out[p.post_id]=p
        print(f'POSTS API @{handle}: HTTP 200, items={len(items) if isinstance(items,list) else 0}, parsed={len(out)}',file=sys.stderr)
        return sorted(out.values(),key=lambda p:p.created_at or '',reverse=True)[:limit]


    def _fetch_posts_browser(self, handle, limit):
        """Fallback using a normal headless Chromium session.

        This does not solve CAPTCHAs, spoof tokens, rotate identities, or bypass
        access restrictions. It simply lets TikTok's public web page run its own
        JavaScript and captures public responses / visible video links.
        """
        if os.getenv('ENABLE_BROWSER_FALLBACK', '0') != '1' or limit <= 0:
            return []
        if sync_playwright is None:
            print(f'BROWSER POSTS WARN @{handle}: Playwright is not installed', file=sys.stderr)
            return []

        count=max(1,min(int(limit),10))
        captured={}
        video_links=[]
        diag_dir=os.getenv('DIAGNOSTICS_DIR','').strip()

        try:
            with sync_playwright() as p:
                headless=os.getenv('BROWSER_HEADLESS','1').strip().lower() not in ('0','false','no')
                browser=p.chromium.launch(headless=headless)
                context=browser.new_context(
                    locale='pl-PL',
                    timezone_id='Europe/Warsaw',
                    viewport={'width': 1440, 'height': 1000},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                )
                page=context.new_page()

                def on_response(resp):
                    try:
                        if '/api/post/item_list/' not in resp.url or resp.status != 200:
                            return
                        body=resp.body()
                        if not body:
                            return
                        data=json.loads(body.decode('utf-8','replace'))
                        items=data.get('itemList') or data.get('item_list') or []
                        if isinstance(items,list):
                            for d in items:
                                pm=self._post_from_dict(d,handle)
                                if pm:
                                    captured[pm.post_id]=pm
                    except Exception:
                        return

                page.on('response', on_response)
                url=f'https://www.tiktok.com/@{quote(handle)}'
                page.goto(url, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(3500)

                content=(page.content() or '')
                try:
                    visible_text=(page.locator('body').inner_text(timeout=5000) or '').lower()
                except Exception:
                    visible_text=''
                current_url=(page.url or '').lower()

                # Only stop on an actually visible verification/challenge page.
                # v0.4 incorrectly treated the harmless "slardarwaf" string in normal
                # TikTok HTML/JS as proof of a block, causing a false positive.
                challenge_phrases=(
                    'verify to continue',
                    'verification required',
                    'complete the captcha',
                    'security verification',
                    'przeciągnij suwak',
                    'potwierdź, że jesteś człowiekiem',
                    'zweryfikuj, aby kontynuować',
                )
                challenge_visible=any(x in visible_text for x in challenge_phrases)
                challenge_url=('captcha' in current_url or '/verify' in current_url)
                if challenge_visible or challenge_url:
                    print(f'BROWSER POSTS LIMITED @{handle}: TikTok showed a visible verification/challenge page; not bypassing it.', file=sys.stderr)
                    if diag_dir:
                        Path(diag_dir).mkdir(parents=True, exist_ok=True)
                        try:
                            page.screenshot(path=str(Path(diag_dir)/'tiktok-profile.png'), full_page=False)
                        except Exception:
                            pass
                    browser.close()
                    return []

                # Give the public profile a chance to issue its normal item-list request.
                for _ in range(2):
                    page.mouse.wheel(0, 1300)
                    page.wait_for_timeout(1800)

                # Collect visible public video links as a second fallback.
                try:
                    hrefs=page.locator('a[href*="/video/"]').evaluate_all(
                        "(els) => els.map(e => e.href)"
                    )
                    for href in hrefs:
                        if href and href not in video_links:
                            video_links.append(href)
                except Exception:
                    pass

                if diag_dir:
                    Path(diag_dir).mkdir(parents=True, exist_ok=True)
                    try:
                        page.screenshot(path=str(Path(diag_dir)/'tiktok-profile.png'), full_page=False)
                    except Exception:
                        pass
                    try:
                        (Path(diag_dir)/'browser-summary.txt').write_text(
                            f'handle=@{handle}\n'
                            f'headless={headless}\n'
                            f'intercepted_posts={len(captured)}\n'
                            f'video_links={len(video_links)}\n'
                            f'page_url={page.url}\n'
                            f'title={page.title()}\n'
                            f'visible_text_sample={(visible_text[:1200] if visible_text else "")}\n',
                            encoding='utf-8'
                        )
                    except Exception:
                        pass

                # If TikTok's own browser request gave us posts, use those.
                if captured:
                    print(
                        f'BROWSER POSTS @{handle}: intercepted={len(captured)}, video_links={len(video_links)}',
                        file=sys.stderr
                    )
                    browser.close()
                    return sorted(
                        captured.values(),
                        key=lambda x:x.created_at or '',
                        reverse=True
                    )[:count]

                # Otherwise open a few public video pages and read their embedded JSON.
                out={}
                for href in video_links[:count]:
                    try:
                        page.goto(href, wait_until='domcontentloaded', timeout=35000)
                        page.wait_for_timeout(1200)
                        html=page.content() or ''
                        if 'captcha' in html.lower() or 'verify to continue' in html.lower():
                            print(f'BROWSER POSTS LIMITED @{handle}: verification page while reading videos; stopping.', file=sys.stderr)
                            break
                        blobs=list(self._json_blobs(html))
                        for blob in blobs:
                            for d in _walk(blob):
                                pm=self._post_from_dict(d,handle)
                                if pm:
                                    out[pm.post_id]=pm
                        if len(out) >= count:
                            break
                    except Exception as e:
                        print(f'BROWSER POSTS WARN @{handle}: video page error: {e}', file=sys.stderr)

                print(
                    f'BROWSER POSTS @{handle}: intercepted=0, video_links={len(video_links)}, parsed_video_pages={len(out)}',
                    file=sys.stderr
                )
                browser.close()
                return sorted(
                    out.values(),
                    key=lambda x:x.created_at or '',
                    reverse=True
                )[:count]

        except Exception as e:
            print(f'BROWSER POSTS WARN @{handle}: {e}', file=sys.stderr)
            return []


    def discover_from_hashtag(self,hashtag):
        tag=hashtag.lstrip('#').strip()
        html=self._get(f'https://www.tiktok.com/tag/{quote(tag)}')
        blobs=list(self._json_blobs(html))
        return sorted(self._creator_candidates(blobs).keys())

    def get_creator(self,handle,posts_limit=10):
        h=handle.lstrip('@').strip()
        html=self._get(f'https://www.tiktok.com/@{quote(h)}')
        blobs=list(self._json_blobs(html))

        # Preferred current TikTok SSR path.
        detail=self._universal_detail(blobs)
        if isinstance(detail,dict):
            status=detail.get('statusCode')
            if status == 10221:
                return None
            user_info=detail.get('userInfo') if isinstance(detail.get('userInfo'),dict) else {}
            user=user_info.get('user') if isinstance(user_info.get('user'),dict) else {}
            if user:
                real_handle=str(user.get('uniqueId') or h)
                # statsV2 carries exact counts on current TikTok pages; fallback to stats.
                stats_v2=user_info.get('statsV2') if isinstance(user_info.get('statsV2'),dict) else {}
                stats=user_info.get('stats') if isinstance(user_info.get('stats'),dict) else {}
                s=stats_v2 or stats
                avatar=user.get('avatarLarger') or user.get('avatarMedium') or user.get('avatarThumb') or ''
                posts=self._posts(blobs,real_handle,posts_limit,detail=detail)
                if not posts and posts_limit:
                    posts=self._fetch_posts_api(user,real_handle,posts_limit)
                if not posts and posts_limit:
                    posts=self._fetch_posts_browser(real_handle,posts_limit)
                return CreatorSnapshot(
                    handle=real_handle,
                    display_name=str(user.get('nickname') or real_handle),
                    bio=str(user.get('signature') or ''),
                    avatar_url=str(avatar),
                    verified=bool(user.get('verified',False)),
                    followers=_int(s.get('followerCount')),
                    following=_int(s.get('followingCount')),
                    total_likes=_int(s.get('heartCount') or s.get('heart')),
                    video_count=_int(s.get('videoCount')),
                    collected_at=datetime.now(timezone.utc).isoformat(),
                    posts=posts,
                )

        # Fallback for older/alternate payload shapes.
        creators=self._creator_candidates(blobs)
        d=creators.get(h) or next((v for k,v in creators.items() if k.lower()==h.lower()),None)
        if d is None:
            return None
        stats=d.get('stats') if isinstance(d.get('stats'),dict) else {}
        avatar=d.get('avatarLarger') or d.get('avatarMedium') or d.get('avatarThumb') or ''
        return CreatorSnapshot(
            handle=h,
            display_name=str(d.get('nickname') or h),
            bio=str(d.get('signature') or ''),
            avatar_url=str(avatar),
            verified=bool(d.get('verified',False)),
            followers=_int(stats.get('followerCount') or d.get('followerCount')),
            following=_int(stats.get('followingCount') or d.get('followingCount')),
            total_likes=_int(stats.get('heartCount') or stats.get('heart') or d.get('heartCount')),
            video_count=_int(stats.get('videoCount') or d.get('videoCount')),
            collected_at=datetime.now(timezone.utc).isoformat(),
            posts=self._posts(blobs,h,posts_limit,detail=detail),
        )

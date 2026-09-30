import json, os, time
from datetime import datetime, timezone
from urllib.parse import quote
import httpx
from bs4 import BeautifulSoup
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
        if 'slardarwaf' in low or ('please wait' in low and '__universal_data_for_rehydration__' not in low):
            raise PublicAccessLimitedError('TikTok returned a WAF/interstitial page (HTTP 200).')
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

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
        for v in obj.values(): yield from _walk(v)
    elif isinstance(obj,list):
        for v in obj: yield from _walk(v)

def _int(v):
    try: return int(v or 0)
    except Exception: return 0

def _iso(v):
    try: return datetime.fromtimestamp(int(v),tz=timezone.utc).isoformat()
    except Exception: return None

class TikTokPublicProvider(Provider):
    # Best-effort reader of JSON already embedded in public TikTok pages.
    # It does not log in, solve CAPTCHAs, rotate identities, or bypass 403/429.
    def __init__(self):
        self.delay=float(os.getenv('REQUEST_DELAY_SECONDS','2.5'))
        self.timeout=float(os.getenv('REQUEST_TIMEOUT_SECONDS','25'))
        self.max_requests=int(os.getenv('MAX_REQUESTS_PER_RUN','250'))
        self.requests=0
        self.client=httpx.Client(timeout=self.timeout,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0 (compatible; InfluRankResearch/0.1; public-data MVP)','Accept-Language':'pl-PL,pl;q=0.9,en;q=0.7'})
    def close(self): self.client.close()
    def _get(self,url):
        if self.requests>=self.max_requests: raise PublicAccessLimitedError('MAX_REQUESTS_PER_RUN reached')
        if self.requests: time.sleep(self.delay)
        self.requests+=1; r=self.client.get(url)
        if r.status_code in (403,429): raise PublicAccessLimitedError(f'TikTok returned HTTP {r.status_code}; scanner stops instead of bypassing the restriction.')
        r.raise_for_status(); return r.text
    @staticmethod
    def _json_blobs(html):
        soup=BeautifulSoup(html,'html.parser')
        for script in soup.find_all('script'):
            txt=(script.string or script.get_text() or '').strip(); sid=script.get('id') or ''
            if not txt or not (txt.startswith('{') or txt.startswith('[')): continue
            if sid not in KNOWN_SCRIPT_IDS and len(txt)<100: continue
            try: yield json.loads(txt)
            except Exception: continue
    @staticmethod
    def _creator_candidates(blobs):
        found={}
        for blob in blobs:
            for d in _walk(blob):
                h=d.get('uniqueId') or d.get('unique_id')
                if not h or not isinstance(h,str): continue
                stats=d.get('stats') if isinstance(d.get('stats'),dict) else {}
                score=len(d)+len(stats)
                if h not in found or score>found[h][0]: found[h]=(score,d)
        return {k:v[1] for k,v in found.items()}
    @staticmethod
    def _posts(blobs,handle,limit):
        posts={}
        for blob in blobs:
            for d in _walk(blob):
                pid=d.get('id'); stats=d.get('stats') if isinstance(d.get('stats'),dict) else None
                if not pid or not stats or 'playCount' not in stats: continue
                author=d.get('author'); ah=''
                if isinstance(author,dict): ah=str(author.get('uniqueId') or '')
                elif isinstance(author,str): ah=author
                if ah and ah.lower()!=handle.lower(): continue
                posts[str(pid)]=PostMetric(str(pid),_iso(d.get('createTime')),str(d.get('desc') or ''),_int(stats.get('playCount')),_int(stats.get('diggCount')),_int(stats.get('commentCount')),_int(stats.get('shareCount')))
        return sorted(posts.values(),key=lambda p:p.created_at or '',reverse=True)[:limit]
    def discover_from_hashtag(self,hashtag):
        tag=hashtag.lstrip('#').strip(); html=self._get(f'https://www.tiktok.com/tag/{quote(tag)}'); blobs=list(self._json_blobs(html)); return sorted(self._creator_candidates(blobs).keys())
    def get_creator(self,handle,posts_limit=10):
        h=handle.lstrip('@').strip(); html=self._get(f'https://www.tiktok.com/@{quote(h)}'); blobs=list(self._json_blobs(html)); creators=self._creator_candidates(blobs)
        d=creators.get(h) or next((v for k,v in creators.items() if k.lower()==h.lower()),None)
        if d is None: return None
        stats=d.get('stats') if isinstance(d.get('stats'),dict) else {}
        avatar=d.get('avatarLarger') or d.get('avatarMedium') or d.get('avatarThumb') or ''
        return CreatorSnapshot(handle=h,display_name=str(d.get('nickname') or h),bio=str(d.get('signature') or ''),avatar_url=str(avatar),verified=bool(d.get('verified',False)),followers=_int(stats.get('followerCount') or d.get('followerCount')),following=_int(stats.get('followingCount') or d.get('followingCount')),total_likes=_int(stats.get('heartCount') or stats.get('heart') or d.get('heartCount')),video_count=_int(stats.get('videoCount') or d.get('videoCount')),collected_at=datetime.now(timezone.utc).isoformat(),posts=self._posts(blobs,h,posts_limit))

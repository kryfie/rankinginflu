import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup


KNOWN_SCRIPT_IDS = {
    "__UNIVERSAL_DATA_FOR_REHYDRATION__",
    "SIGI_STATE",
    "__NEXT_DATA__",
}


class PublicAccessLimitedError(RuntimeError):
    pass


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _as_int(value):
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


class TikTokPublicProfileReader:
    """Read light public TikTok profile metrics from profile HTML only.

    One profile = one public page request.
    No login, no CAPTCHA solving, no proxy rotation, no token forging,
    no post scraping and no Apify.
    """

    def __init__(self, delay_seconds=None, timeout_seconds=None, max_requests=None):
        self.delay = float(
            delay_seconds
            if delay_seconds is not None
            else os.getenv("SNAPSHOT_REQUEST_DELAY_SECONDS", "2.5")
        )
        self.timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("SNAPSHOT_REQUEST_TIMEOUT_SECONDS", "25")
        )
        self.max_requests = int(
            max_requests
            if max_requests is not None
            else os.getenv("SNAPSHOT_MAX_REQUESTS_PER_RUN", "2000")
        )
        self.requests = 0
        self.client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

    def close(self):
        self.client.close()

    def _get(self, url):
        if self.requests >= self.max_requests:
            raise PublicAccessLimitedError("SNAPSHOT_MAX_REQUESTS_PER_RUN reached")

        if self.requests:
            time.sleep(self.delay)

        self.requests += 1
        response = self.client.get(url)

        if response.status_code in (403, 429):
            raise PublicAccessLimitedError(
                f"TikTok returned HTTP {response.status_code}; "
                "snapshot stops instead of bypassing the restriction."
            )

        response.raise_for_status()
        html = response.text
        low = html.lower()

        if (
            "slardarwaf" in low
            and "__universal_data_for_rehydration__" not in low
        ) or (
            "please wait" in low
            and "__universal_data_for_rehydration__" not in low
        ):
            raise PublicAccessLimitedError(
                "TikTok returned a WAF/interstitial page."
            )

        return html

    @staticmethod
    def _json_blobs(html):
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            text = (script.string or script.get_text() or "").strip()
            script_id = script.get("id") or ""

            if not text or not (text.startswith("{") or text.startswith("[")):
                continue
            if script_id not in KNOWN_SCRIPT_IDS and len(text) < 100:
                continue

            try:
                yield json.loads(text)
            except Exception:
                continue

    @staticmethod
    def _universal_detail(blobs):
        for blob in blobs:
            if not isinstance(blob, dict):
                continue
            scope = blob.get("__DEFAULT_SCOPE__")
            if not isinstance(scope, dict):
                continue
            detail = scope.get("webapp.user-detail")
            if isinstance(detail, dict):
                return detail
        return None

    @staticmethod
    def _fallback_creator(blobs, handle):
        found = {}
        for blob in blobs:
            for row in _walk(blob):
                unique_id = row.get("uniqueId") or row.get("unique_id")
                if not unique_id or not isinstance(unique_id, str):
                    continue
                stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
                score = len(row) + len(stats)
                key = unique_id.lower()
                if key not in found or score > found[key][0]:
                    found[key] = (score, row)

        item = found.get(handle.lower())
        return item[1] if item else None

    def get_profile(self, handle):
        handle = str(handle or "").lstrip("@").strip()
        if not handle:
            return None

        html = self._get(f"https://www.tiktok.com/@{quote(handle)}")
        blobs = list(self._json_blobs(html))

        detail = self._universal_detail(blobs)
        if isinstance(detail, dict):
            if detail.get("statusCode") == 10221:
                return None

            user_info = (
                detail.get("userInfo")
                if isinstance(detail.get("userInfo"), dict)
                else {}
            )
            user = (
                user_info.get("user")
                if isinstance(user_info.get("user"), dict)
                else {}
            )

            if user:
                stats_v2 = (
                    user_info.get("statsV2")
                    if isinstance(user_info.get("statsV2"), dict)
                    else {}
                )
                stats = (
                    user_info.get("stats")
                    if isinstance(user_info.get("stats"), dict)
                    else {}
                )
                values = stats_v2 or stats

                return {
                    "handle": str(user.get("uniqueId") or handle),
                    "display_name": str(user.get("nickname") or handle),
                    "verified": bool(user.get("verified", False)),
                    "followers": _as_int(values.get("followerCount")),
                    "following": _as_int(values.get("followingCount")),
                    "total_likes": _as_int(
                        values.get("heartCount") or values.get("heart")
                    ),
                    "video_count": _as_int(values.get("videoCount")),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }

        fallback = self._fallback_creator(blobs, handle)
        if fallback is None:
            return None

        stats = (
            fallback.get("stats")
            if isinstance(fallback.get("stats"), dict)
            else {}
        )

        return {
            "handle": str(
                fallback.get("uniqueId")
                or fallback.get("unique_id")
                or handle
            ),
            "display_name": str(fallback.get("nickname") or handle),
            "verified": bool(fallback.get("verified", False)),
            "followers": _as_int(
                stats.get("followerCount") or fallback.get("followerCount")
            ),
            "following": _as_int(
                stats.get("followingCount") or fallback.get("followingCount")
            ),
            "total_likes": _as_int(
                stats.get("heartCount")
                or stats.get("heart")
                or fallback.get("heartCount")
            ),
            "video_count": _as_int(
                stats.get("videoCount") or fallback.get("videoCount")
            ),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

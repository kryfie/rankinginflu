from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PostMetric:
    post_id: str
    created_at: Optional[str] = None
    description: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0

@dataclass
class CreatorSnapshot:
    handle: str
    display_name: str = ""
    bio: str = ""
    avatar_url: str = ""
    verified: bool = False
    followers: int = 0
    following: int = 0
    total_likes: int = 0
    video_count: int = 0
    collected_at: str = ""
    posts: list[PostMetric] = field(default_factory=list)

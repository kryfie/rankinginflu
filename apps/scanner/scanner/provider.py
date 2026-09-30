from abc import ABC, abstractmethod
from packages.shared.models import CreatorSnapshot

class PublicAccessLimitedError(RuntimeError): pass

class Provider(ABC):
    @abstractmethod
    def discover_from_hashtag(self, hashtag: str) -> list[str]: ...
    @abstractmethod
    def get_creator(self, handle: str, posts_limit: int = 10) -> CreatorSnapshot | None: ...

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class DiscoveredProvider:
    provider_name: str
    domain: str
    website_url: str
    catalog_source: str
    catalog_page_url: str
    catalog_rating: Optional[float] = None
    catalog_reviews_count: Optional[int] = None


class SourceAdapter(ABC):
    source_id: str

    @abstractmethod
    def crawl(self) -> List[DiscoveredProvider]:
        """Fetch catalog page(s) and return list of discovered providers."""
        pass

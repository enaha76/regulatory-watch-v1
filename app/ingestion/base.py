"""
T2.1 — IngestorBase abstract class.

Every connector must inherit from IngestorBase and implement fetch().
The return type List[RawDocument] uses the SQLModel table class so
instances can be directly handed to the storage layer for upsert.
"""

from abc import ABC, abstractmethod
from typing import List

from app.models import RawDocument


class IngestorBase(ABC):
    """
    Abstract base for all data-source connectors.

    Subclasses implement :meth:`fetch`, which asynchronously retrieves
    documents from a specific source and returns them as a list of
    unsaved :class:`~app.models.RawDocument` instances.

    The caller (Celery task / storage layer) is responsible for
    persisting the returned documents via upsert.
    """

    @abstractmethod
    async def fetch(self) -> List[RawDocument]:
        """
        Pull content from the source.

        Returns
        -------
        List[RawDocument]
            Unsaved RawDocument instances.  content_hash must be
            populated (SHA-256 of raw_text) before returning so the
            storage layer can de-duplicate without extra DB reads.
        """
        ...

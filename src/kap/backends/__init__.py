"""Optional integrations kept outside the core KAP HTTP/scraping path."""

from .optional import (
    AttachmentDownloadResult,
    AttachmentDownloader,
    CheckpointStore,
    HttpAttachmentDownloader,
    IncrementalDisclosurePoller,
    JsonCheckpointStore,
    MkkProvider,
)

__all__ = [
    "AttachmentDownloadResult",
    "AttachmentDownloader",
    "CheckpointStore",
    "HttpAttachmentDownloader",
    "IncrementalDisclosurePoller",
    "JsonCheckpointStore",
    "MkkProvider",
]

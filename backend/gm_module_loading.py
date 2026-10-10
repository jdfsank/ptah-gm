"""Serialize temporary bare-import aliases across the two pinned GM adapters."""

import threading

PINNED_MODULE_LOCK = threading.RLock()

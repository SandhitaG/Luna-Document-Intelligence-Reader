"""
Minimal in-memory placeholder so imports don't fail.
"""
from typing import Any, Dict, List

class MemoryStore:
    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def add(self, item: Dict[str, Any]) -> None:
        self._items.append(item)

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items)

memory = MemoryStore()

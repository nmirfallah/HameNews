"""The knowledge base: who is connected to whom, with sources, and what each source said about each topic.

Facts and judgments are kept apart. A *claim* records who asserted a connection, with a source, a date and a
status (documented, reported, alleged, denied...). Nothing here merges claims into a verdict: disputes sit side
by side. JSONL files in data/kb/ are the source of truth; SQLite is only a query index built from them.
"""
from .index import KBIndex
from .schema import KBError
from .store import KBStore

__all__ = ["KBStore", "KBIndex", "KBError"]

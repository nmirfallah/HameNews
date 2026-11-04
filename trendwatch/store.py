import json
import os


class Store:
    """Tiny JSON-file store. Everything lives under data/ so GitHub Actions can commit it."""

    def __init__(self, root):
        self.root = root

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel, default=None):
        try:
            with open(self.path(rel), "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def write(self, rel, obj):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

    def write_text(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def list_dir(self, rel):
        try:
            return sorted(os.listdir(self.path(rel)))
        except FileNotFoundError:
            return []

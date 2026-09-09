import json
import time
from pathlib import Path


class AuditLogger:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, who: str, sql: str, note: str = "") -> None:
        row = {"ts": time.time(), "tool": tool, "who": who, "sql": sql, "note": note}
        with open(self.path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
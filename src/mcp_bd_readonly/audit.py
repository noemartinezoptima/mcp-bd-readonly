import json
import time
from pathlib import Path

from mcp_bd_readonly.request_ctx import get_api_key


class AuditLogger:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, who: str, sql: str, note: str = "") -> None:
        # Todos los call sites pasan el literal "mcp" como `who` (no identifican
        # a la API key que hizo la llamada). Si hay una request HTTP autenticada
        # en curso, su api_key_id prevalece sobre ese literal; en stdio (sin
        # middleware, sin contextvar fijado) se mantiene el comportamiento de
        # siempre.
        api_key_id = get_api_key()
        if who == "mcp" and api_key_id:
            who = api_key_id
        row = {"ts": time.time(), "tool": tool, "who": who, "sql": sql, "note": note}
        with open(self.path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

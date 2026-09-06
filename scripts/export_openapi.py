import json
from pathlib import Path

from apps.api.main import app

Path("packages/contracts/openapi.json").write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
)

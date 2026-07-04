import sys
from pathlib import Path

# make `import llm_gateway` / `import yandex_client` work regardless of CWD
SHARED = Path(__file__).resolve().parent.parent
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

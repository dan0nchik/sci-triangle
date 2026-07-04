import os
import sys

# добавляем pipeline/extract в путь, чтобы `import rules` работал при запуске
# pytest из корня репозитория без переменной PYTHONPATH.
_EXTRACT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _EXTRACT_DIR not in sys.path:
    sys.path.insert(0, _EXTRACT_DIR)

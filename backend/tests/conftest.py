"""pytest 全局配置：把 backend 目录加入 sys.path，保证 `import app.*` 可用。"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

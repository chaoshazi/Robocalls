'''日志：统一格式，级别由 WAHU_LOG_LEVEL 决定。'''

from __future__ import annotations

import logging
import sys

_FORMAT = '%(asctime)s %(levelname)s %(name)s %(message)s'


def setup_logging(level: str = 'INFO') -> None:
    resolved = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(resolved)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    # uvicorn 自带的访问日志太吵，交给上层按需开
    logging.getLogger('uvicorn.access').setLevel(max(resolved, logging.WARNING))
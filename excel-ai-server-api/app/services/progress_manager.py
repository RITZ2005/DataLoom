from dataclasses import dataclass
import time
from typing import Callable, Dict, Optional


@dataclass
class UploadProgress:
    file_uuid: str
    stage: str
    current: int
    total: int
    message: str
    error: Optional[str] = None
    timestamp: float = 0

    def __post_init__(self):
        self.timestamp = time.time()


_progress_store: Dict[str, UploadProgress] = {}


def set_progress(file_uuid: str, stage: str, current: int, total: int, message: str, error: str = None):
    _progress_store[file_uuid] = UploadProgress(
        file_uuid=file_uuid,
        stage=stage,
        current=current,
        total=total,
        message=message,
        error=error,
    )


def get_progress(file_uuid: str) -> Optional[UploadProgress]:
    return _progress_store.get(file_uuid)


def clear_progress(file_uuid: str):
    if file_uuid in _progress_store:
        del _progress_store[file_uuid]


def create_progress_callback(file_uuid: str) -> Callable:
    def callback(stage: str, current: int, total: int, message: str):
        set_progress(file_uuid, stage, current, total, message)

    return callback

from __future__ import annotations

from pydantic import BaseModel


class GeneratedFile(BaseModel):
    file_id: str
    task_id: str
    file_name: str
    file_type: str
    path: str
    size: int
    created_at: str

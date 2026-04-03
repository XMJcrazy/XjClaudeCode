"""文件操作工具模块"""
import os
from pathlib import Path

from base_comp.session import SessionData
from base_comp.tool_base import ToolBase, ToolResp, TOOL_SUCCESS, TOOL_ERROR_AI


FILE_SIZE_LIMIT = 50000

def safe_path(file_path: str, white_list: set[str]) -> Path:
    """路径安全性验证，只允许在工作路径下或白名单路径下操作文件"""
    path_file = Path(file_path).resolve()
    # 只要在白名单的子路径下就允许操作
    flag = False
    for white in white_list:
        white_work = Path(white).resolve()
        if path_file.is_relative_to(white_work):
            flag = True
    if not flag:
        raise ValueError(f"error path: {file_path}")
    return path_file


# ===============================================================================
# 本地文件操作工具包
# ===============================================================================

class ToolReadFile(ToolBase):
    def __init__(self):
        self.name = "tool_read"
        self.description = "read local file info"

    def execute(self, sd: SessionData, file_path: str, limit: int = None) -> ToolResp:
        text = safe_path(file_path, sd.session.white_path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return ToolResp(TOOL_SUCCESS, "\n".join(lines)[:50000])

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "full path to the file"},
                "limit": {"type": "integer", "description": "read size limit"},
            },
            "required": ["file_path", "limit"],
        }

class ToolWriteFile(ToolBase):
    def __init__(self):
        self.name = "tool_write"
        self.description = "写本地文件"

    def execute(self, sd: SessionData, file_path: str, content: str) -> ToolResp:
        fp = safe_path(file_path, sd.session.white_path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return ToolResp(TOOL_SUCCESS, f"Wrote {len(content)} bytes to {file_path}")

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "full path to the file"},
                "content": {"type": "integer", "description": "write content"},
            },
            "required": ["file_path", "content"],
        }

class ToolEditFile(ToolBase):
    def __init__(self):
        self.name = "tool_edit"
        self.description = "修改本地文件"

    def execute(self, sd: SessionData, file_path: str, old_text: str, new_text: str) -> ToolResp:
        fp = safe_path(file_path, sd.session.white_path)
        content = fp.read_text()
        if old_text not in content:
            return ToolResp(TOOL_ERROR_AI, f"Text not found in {file_path}")
        fp.write_text(content.replace(old_text, new_text, 1))
        return ToolResp(TOOL_SUCCESS, f"Edited {file_path}")

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "full path to the file"},
                "old_text": {"type": "integer", "description": "old text in file"},
                "new_text": {"type": "integer", "description": "new text need to write"},
            },
            "required": ["file_path", "old_text", "new_text"],
        }

"""脚本工具模块"""
import os
import subprocess
from datetime import datetime

from base_comp.session import SessionCtx
from base_comp.tool_base import ToolBase, ToolResp, TOOL_ERROR_AI, TOOL_SUCCESS
from base_comp.validate import init_validate, CommandContext


class ToolBaseScript(ToolBase):
    def __init__(self, sys: str):
        self.name = "tool_script"
        if sys:
            self.sys = sys
        else:
            self.sys = "linux"
        self.description = """
            Run a execute command in """ + self.sys + """.
            example:  
            {
                "command": "python",
                "work_dir": "/project",
                "args": ["main.py", "--config", "config.yaml"],
                "files": []
            },
            {
                "command": "docker",
                "work_dir": "/",
                "args": ["build", "-t", "myapp:latest", "."],
                "files": ["Dockerfile"]
            }
        """

    async def execute(self, session_data: SessionCtx, command: str, work_dir: str, args: list[str], files: list[str]) -> ToolResp:
        """基础脚本执行工具"""
        if session_data is None or session_data.session is None:
            return ToolResp(TOOL_ERROR_AI, "Error: param session illegal")
        session = session_data.session
        white_dir = session.white_path
        task_id = f"{session.id}:{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 进行指令权限验证，如果不通过返回对应的错误信息
        result = init_validate().validate(CommandContext(command, args, work_dir, white_dir=white_dir,task_id=task_id))
        if not result.allowed:
            return ToolResp(TOOL_ERROR_AI, f"error: {result.message}\n{result.suggestions}")
        try:
            cmd_str = f"{command}  {" ".join(args)}  {" ".join(files)}"
            r = subprocess.run(cmd_str, shell=True, cwd=work_dir,
                               capture_output=True, text=True, timeout=600)
            out = (r.stdout + r.stderr).strip()
            return ToolResp(TOOL_SUCCESS, out[:50000] if out else "no output")
        except subprocess.TimeoutExpired:
            return ToolResp(TOOL_ERROR_AI, "Error: Timeout")

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "command script"
                },
                "work_dir": {
                    "type": "string",
                    "description": "command execute dir"
                },
                "args": {
                    "type": "array",
                    "items": {
                        "type": "str",
                    },
                    "description": "command arguments"
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "str",
                    },
                    "description": "command execute file"
                }
            },
            "required": ["command", "work_dir", "args", "files"],
        }



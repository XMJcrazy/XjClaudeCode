"""脚本工具模块"""
import os
import subprocess

from base_comp.tool_base import ToolBase, ToolResp, TOOL_ERROR, TOOL_SUCCESS
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

    async def execute(self, command: str, work_dir: str, args: list[str], files: list[str], **kwargs) -> ToolResp:
        """基础脚本执行工具"""

        white_dir = kwargs["white_dir"] if "white_dir" in kwargs else os.getcwd()
        task_id = kwargs["task_id"] if "task_id" in kwargs else "default_task"

        # 进行指令权限验证，如果不通过返回对应的错误信息
        result = await init_validate().validate(CommandContext(command, args, work_dir, white_dir=white_dir,task_id=task_id))
        if not result.allowed:
            return ToolResp(TOOL_ERROR, f"error: {result.message}\n{result.suggestions}")
        try:
            cmd_str = f"{command}  {" ".join(args)}  {" ".join(files)}"
            r = subprocess.run(cmd_str, shell=True, cwd=work_dir,
                               capture_output=True, text=True, timeout=60)
            out = (r.stdout + r.stderr).strip()
            return ToolResp(TOOL_SUCCESS, out[:50000] if out else "no output")
        except subprocess.TimeoutExpired:
            return ToolResp(TOOL_ERROR, "Error: Timeout")

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

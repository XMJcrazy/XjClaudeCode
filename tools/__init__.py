"""
agent 工具包，包含所有工具的底层实现
"""
from manager.tools_manager import register_tool
from tools.tool_file import ToolReadFile, ToolWriteFile, ToolEditFile
from tools.tool_schedule import ToolTaskAnalysis, ToolTaskScheduler, ToolTaskSync
from tools.tool_bash import ToolBash
from tools.tool_web import WebFetchToolBase, CodeSearchToolBase


# ============================================================================
# 注册agent tools的具体实现
# ============================================================================
def register_tools():
    # 任务规划工具
    register_tool(ToolTaskAnalysis())
    register_tool(ToolTaskScheduler())
    register_tool(ToolTaskSync())

    # 网络查询工具
    register_tool(WebFetchToolBase())
    register_tool(CodeSearchToolBase())

    # 脚本工具
    register_tool(ToolBash("macos"))

    # 简单文件操作工具
    register_tool(ToolReadFile())
    register_tool(ToolWriteFile())
    register_tool(ToolEditFile())

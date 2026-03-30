"""
agent 工具包，包含所有工具的底层实现
"""
from manager.tools_manager import register_tool
from tools.tool_script import ToolBaseScript
from tools.tool_web import WebFetchToolBase, CodeSearchToolBase


# ============================================================================
# 注册agent tools的具体实现
# ============================================================================
def register_func():
    register_tool(WebFetchToolBase())
    register_tool(CodeSearchToolBase())
    register_tool(ToolBaseScript("macos"))


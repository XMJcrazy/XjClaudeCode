"""
工具调用通用包
包含了工具的调用逻辑和所有工具的实现
"""
import asyncio
import threading

from base_comp.session import Session
from base_comp.tool_base import ToolBase, TOOL_SUCCESS, TOOL_ERROR, TOOL_TIMEOUT

# my_tools本地的工具集, mutex互斥锁，保证工具集的并发安全
my_tools: dict[str, ToolBase] = {}
mutex = threading.Lock()


def register_tool(tool: ToolBase):
    """注册agent的tool实现类"""
    global my_tools, mutex
    mutex.acquire()
    my_tools[tool.name] = tool
    mutex.release()

def remove_tool(tool: ToolBase):
    """注销agent的tool实现类"""
    global my_tools, mutex
    mutex.acquire()
    del my_tools[tool.name]
    mutex.release()

async def route_tool_use(tool_name: str, session: Session, **kwargs):
    """
    接收大模型的工具调用请求并路由到具体的方法
    :param session: 会话信息，有些工具要调用会话中的内容
    :param tool_name: 大模型要调用的工具信息
    :param kwargs: 大模型返回的字典参数（工具方法的参数）
    :return:
    """
    tool = my_tools[tool_name]
    if tool is None:
        return f"tool not found:{tool_name}"
    else:
        try:
            # 脚本工具需要额外的参数，具体规则后面再完善
            if tool.name == "tool_script":
                kwargs["white_dir"] = session.white_path
                kwargs["task_id"]= session.id
            print(f"prepare use tool:{tool_name} with args:{kwargs}")
            resp = await asyncio.wait_for(tool.execute(**kwargs), timeout=120)
        except asyncio.TimeoutError:
            # TODO超时要做指数退阶的重试，这里先简单处理
            return f"Error:timeout with tool:{tool_name}"
        if resp.status_code == TOOL_SUCCESS:
            return resp.content

        return f"tool:{tool_name}\nError:{resp.content}"


def get_tools_for_anthropic() -> list[dict]:
    """获取符合 Anthropic 格式的工具定义列表"""
    return [tool.get_anthropic_schema() for tool in my_tools.values()]



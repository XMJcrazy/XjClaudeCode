"""
工具调用通用包
包含了工具的调用逻辑和所有工具的实现
"""
import asyncio
import threading

from base_comp.prompt import ANALYSIS_NAME, SCHEDULER_NAME
from base_comp.session import SessionCtx
from base_comp.tool_base import ToolBase, TOOL_SUCCESS

# 分析类工具，这个需要单独使用
scheduler_names = [ANALYSIS_NAME, SCHEDULER_NAME]

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

def route_tool_use(tool_name: str, ctx: SessionCtx, **kwargs):
    """
    接收大模型的工具调用请求并路由到具体的方法
    :param ctx: 会话上下文，有些工具要调用会话中的内容
    :param tool_name: 大模型要调用的工具信息
    :param kwargs: 大模型返回的字典参数（工具方法的参数）
    :return:
    """
    tool = my_tools[tool_name]
    if tool is None:
        return False, f"tool not found:{tool_name}"
    else:
        try:
            print(f"PREPARE USE TOOL:{tool_name} with args:{kwargs}")
            resp = tool.execute(ctx, **kwargs)
        except asyncio.TimeoutError:
            # TODO超时要做指数退阶的重试，这里先简单处理
            return False, f"Error:timeout with tool:{tool_name}"
        except TypeError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

        if resp.status_code == TOOL_SUCCESS:
            return True, resp.content
        return False, f"tool:{tool_name}\nError:{resp.content}"


def get_tools_for_anthropic() -> list[dict]:
    """获取符合 Anthropic 格式的工具定义列表"""
    # 排除任务分析和规划工具，这些工具会单独使用，不在主任务循环之中
    return [tool.get_anthropic_schema() for tool in my_tools.values() if tool.name not in scheduler_names]

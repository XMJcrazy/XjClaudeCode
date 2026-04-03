import asyncio
import os

import dotenv
from anthropic import Anthropic, Stream

from base_comp.session import SessionData, TODO_NAME, TOOL_LIMIT_TIMES
from .common import StopReason
from manager.tools_manager import route_tool_use, get_tools_for_anthropic
import tools

# 获取相关配置信息
dotenv.load_dotenv()
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL")

# 初始化项目的若干组件
# 注册tools方法
tools.register_func()

# 定义系统级别的提示词，用来约束agent的大方向
SYSTEM = f"你是一个编程智能体，要帮助用户解决编程方面的问题。请确保你的回答精简且有条理，所有回答都必须用中文。"
# 包含todolist版本的系统提示词
SYSTEM_TODO = f"你是一个编程智能体，要帮助用户解决编程方面的问题。在解决问题之前需要进行任务规划，任务规划和执行状态用tool:{TODO_NAME}同步给我.请确保你的回答精简且有条理，所有回答都必须用中文。"
# anthropic标准的工具信息
ANTHROPIC_TOOLS = get_tools_for_anthropic()

# 构建anthropic模型访问客户端
model_client = Anthropic(base_url=BASE_URL, api_key=API_KEY)


def handle_resp_content(sd: SessionData, content: list) -> list:
    """统一处理AI模型返回信息的方法"""
    # results存放本轮次返回信息的用户端的处理情况
    user_content = []
    # 拆分消息块，并根据消息类型来分别处理
    # 注意：thinking_result 类型只能由模型输出，不能作为输入发回给 API
    for block in content:
        match block.type:
            case "text":
                print(f"TEXT ====> {block.text}")
            case "thinking":
                # thinking 内容不需要发回给 API(前面已经全量存了)，仅打印即可
                print(f"thinking...  {block.thinking[:1000]}..." if len(block.thinking) > 1000 else f"thinking... {block.thinking}")
            case "tool_use":
                # 获取模型端返回的工具调用信息
                is_success, tool_resp = route_tool_use(block.name, sd, **block.input)
                # 工具调用信息
                user_content.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_resp})
                print(f"TOOL RESP：{tool_resp[:1000] if len(tool_resp) > 1000 else tool_resp}")

                # 调用过任务规划工具就把other_times清零
                if block.name == TODO_NAME:
                    sd.todo_manager.other_times = 0
                elif is_success:
                    # 工具调用成功才计数，避免频繁提醒
                    sd.todo_manager.other_times += 1
                # 子任务执行期间，调用其他工具超出一定次数就进行提醒
                if sd.todo_manager.other_times >= TOOL_LIMIT_TIMES:
                        user_content.append({"type": "text", "text": f"<reminder>Update your todos with tool:{TODO_NAME}</reminder>"})
            case "redacted_thinking":
                # 思考内容被隐藏，仅提示
                print("thinking... [内容已隐藏]")
            case _:
                # 忽略其他未知类型
                pass
    return user_content

# 后续再完善这个部分的内容
# def handle_stop_reason(stop_reason: str, messages: Message | Stream[RawMessageStreamEvent]):
#     """
#     接收LLM的停止原因并进行对应的处理
#     :param stop_reason: 大模型返回的stop原因
#     :return: 返回agent的处理结果
#     """
#     # 这里简单定义一下，直接返回停止原因，实际的业务应该是每种stop_reason都对应单独的func
#     handlers = {
#         StopReason.END_TURN.value: lambda: "任务结束",
#         StopReason.STOP_SEQUENCE.value: lambda: "触发用户定义的停止信号",
#         StopReason.TOOL_USE.value: route_tool_use(),
#         StopReason.PAUSE_TURN.value: lambda: "需要人工介入的停止",
#         StopReason.REFUSAL.value: lambda: "存在违规内容",
#         StopReason.MAX_TOKENS.value: lambda: "超出token限制",
#     }
#     handler = handlers.get(stop_reason)
#     return handler() if handler else f"未知的错误类型{stop_reason}"


# ============================================================================
# agent会话入口，异步设计支持多会话并行
# ============================================================================
# 每一个会话都是一个单独的agent_loop，多个会话同时开启就是异步调用，但是会话内部逻辑都是基于同步的

async def agent_loop(client: Anthropic, session_data: SessionData, messages: list):
    """
    agent的单次任务的主进程循环，从用户的初始消息开始，完成任务退出循环
    使用异步方法，支持多任务并行
    :param session_data: agent会话信息，会话的生命周期内保持唯一
    :param client: Anthropic模型访问对象
    :param messages: 初始的用户信息列表
    """
    # 循环执行，收到LLM的停止消息再跳出循环
    while True:
        resp_msgs = client.messages.create(max_tokens=10*1024, messages=messages, model=MODEL, system=SYSTEM_TODO, tools=ANTHROPIC_TOOLS)
        # messages要保存所有的历史信息
        messages.append({"role": "assistant", "content": resp_msgs.content})

        # 如果模型端有stop_reason信息，则进行对应的逻辑处理
        # 不是调用工具，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
        if resp_msgs.stop_reason != StopReason.TOOL_USE.value:
            print(f"task stop!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
            return
        # if resp_msgs.stop_reason:
        #     handle_stop_reason(resp_msgs.stop_reason, resp_msgs.content)

        # 调用统一的AI模型返回信息处理方法
        user_content = handle_resp_content(session_data, resp_msgs.content)

        # len > 0 说明本轮次有用户端信息，包装到发送给AI端的信息中
        if len(user_content) > 0:
            messages.append({"role": "user", "content": user_content})

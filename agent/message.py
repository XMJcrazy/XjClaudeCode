"""AI对象，信息处理模块"""
import json
from dataclasses import dataclass, field

from anthropic import AsyncStream

from .common import StopReason
from base_comp.context import MSG_THINK, MSG_TOOL, MSG_TEXT
from base_comp.session import SessionCtx
from manager.tools_manager import route_tool_use
from utils.log import LOGGER


@dataclass
class AgentMessages:
    is_stop: bool = False                   # 轮次是否结束
    stop_reason: str = None                 # 结束的原因
    stop_detail: str = None                 # 结束的具体细节
    ai_msg: dict = field(default_factory=dict)           # 模型端单轮次调用返回信息
    user_content:list = field(default_factory=list)      # 用户端额外信息，主要是工具调用信息
    tool_objs: dict = field(default_factory=dict)        # 工具调用的额外参数信息，适用于部分状态控制，任务调度的tool


async def process_stream(stream: AsyncStream, ctx: SessionCtx, **kwargs) -> AgentMessages:
    """
    处理流式响应（anthropic规范）
    :param stream: 流式调用信息
    :param ctx: 上下问信息，单个会话的上下文是独立的，会话基础信息，状态数据、任务执行信息等都在这里
    """
    # 解析额外字典参数，hide_thinking-隐藏思考信息
    hide_thinking = kwargs.get("hide_thinking", False)
    task_info = kwargs.get("task_info", "TASK")

    agent_msg, ai_msg = AgentMessages(), {}

    # 读取异步数据流
    async for event in stream:
        # 事件类型: message_start, message_delta, message_stop, content_block_start, content_block_delta, content_block_stop
        # 一轮对话有一个message，包含若干个block，每个block由若干个delta消息组成
        match event.type:
            case "message_start":
                # 消息开始事件，一个message_start对应一轮完整的对话信息
                ai_msg = event.message
                if ai_msg.stop_reason:
                    if ai_msg.stop_reason != StopReason.TOOL_USE.value:
                        agent_msg.is_stop = True
                        agent_msg.stop_reason = ai_msg.stop_reason
                        agent_msg.stop_details = ai_msg.stop_details
                        print(f"{task_info} finished! STOP REASON: {event.message.stop_reason}", flush=True)

            case "message_delta":
                # 消息增量事件，主要存放token数据、stop_reason、工具调用等
                # TODO 这里可以加token量记录相关功能，后续要加上
                pass
            case "content_block_start":
                # 文本块开始事件,根据返回信息构建文本块，目前仅支持下面类型，额外的类型直接忽略
                if event.content_block.type in [MSG_THINK, MSG_TEXT, MSG_TOOL]:
                    ai_msg.content.append(event.content_block)
                    if event.content_block.type == MSG_THINK:
                        print(f"[thinking...]", end="", flush=True)
                    if event.content_block.type == MSG_TOOL:
                        ai_msg.content[-1].input = {"temp_input": []}

            case "content_block_delta":
                # 增量消息目前仅解析text、thinking、tool_use
                if event.delta.type == "thinking_delta":
                    if not hide_thinking:
                        print(f"{event.delta.thinking[:1000]}", end="", flush=True)
                    ai_msg.content[-1].thinking = ''.join([ai_msg.content[-1].thinking, event.delta.thinking])
                elif event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
                    ai_msg.content[-1].text = ''.join([ai_msg.content[-1].text, event.delta.text])
                elif event.delta.type == "input_json_delta":
                    # 工具调用信息可能不是在一个delta里面传过来的，需要进行合并
                    # print(event.delta.partial_json, end="", flush=True)
                    ai_msg.content[-1].input["temp_input"].append(event.delta.partial_json)

            case "content_block_stop":
                # 消息块结束,构建合法且精简的请求message block
                if ai_msg.content[-1].type == MSG_TOOL:
                    # 如果是工具调用请求block，则需要触发对应的agent逻辑
                    ai_msg.content[-1].input = json.loads(''.join(ai_msg.content[-1].input["temp_input"]))
                    # del ai_msg.content[-1]["temp_input"]
                    await tool_call(ctx, agent_msg, ai_msg.content[-1])

            case "message_stop":
                # 单turn对话流结束
                LOGGER.debug("AI model single turn over.ai_msg id: %s", ai_msg.id)

    agent_msg.ai_msg = ai_msg.to_dict()
    return agent_msg


async def tool_call(ctx: SessionCtx, agent_msg: AgentMessages, tool_block):
    """处理大模型工具调用的agent包装方法"""
    name = tool_block.name
    success, tool_resp, tool_obj = await route_tool_use(name, ctx, **tool_block.input)
    # 工具调用信息
    agent_msg.user_content.append({"type": "tool_result", "tool_use_id": tool_block.id, "content": tool_resp})
    print(f"TOOL RESP：{tool_resp[:500]}")
    if not success:
        LOGGER.info("AI model tool_call - %s fail: %s", name, tool_resp)
    elif tool_obj:
        # 工具调用额外的返回值，存储到tool_dict中
        agent_msg.tool_objs[name] = tool_obj


async def _handle_resp_content(ctx: SessionCtx, content: list) -> list:
    """
    统一处理AI模型返回信息的方法
    :param ctx       会话上下文信息
    :param content  模型原始返回信息
    """
    # results存放本轮次返回信息的用户端的处理情况
    user_content = []
    # 拆分消息块，并根据消息类型来分别处理
    for block in content:
        match block.type:
            case "text":
                print(f"TEXT ====> {block.text}")
            case "thinking":
                # thinking 内容不需要发回给 API(前面已经全量存了)，仅打印即可
                print(f"thinking...  {block.thinking[:1000]}..." if len(block.thinking) > 1000 else f"thinking... {block.thinking}")
            case "tool_use":
                # 获取模型端返回的工具调用信息
                _, tool_resp, _ = await route_tool_use(block.name, ctx, **block.input)
                # 工具调用信息
                user_content.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_resp})
                print(f"TOOL RESP：{tool_resp[:1000] if len(tool_resp) > 1000 else tool_resp}")
            case "redacted_thinking":
                # 思考内容被隐藏，仅提示
                print("thinking... [内容已隐藏]")
    return user_content


def _is_stop(stop_reason: str) -> tuple[bool, str]:
    """判断任务是否继续执行，返回(是否继续, 原因)"""
    if stop_reason == StopReason.END_TURN.value:
        LOGGER.info("TASK FINISHED!")
        return True, ""
    elif stop_reason == StopReason.TOOL_USE.value:
        return False, ""
    elif stop_reason:
        LOGGER.error("AI stop error:%s", stop_reason)
        return True, stop_reason
    return False, ""

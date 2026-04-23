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
    ai_msg: dict = None                     # 模型端单轮次调用返回信息
    user_content = []                       # 用户端额外信息，主要是工具调用信息
    tool_objs = {}                          # 工具调用的额外参数信息，适用于部分状态控制，任务调度的tool


async def process_stream(stream: AsyncStream, ctx: SessionCtx, **kwargs) -> AgentMessages:
    """
    处理流式响应（anthropic规范）
    :param stream: 流式调用信息
    :param ctx: 上下问信息，单个会话的上下文是独立的，会话基础信息，状态数据、任务执行信息等都在这里
    """

    # 解析额外字典参数，hide_thinking-隐藏思考信息、
    hide_thinking = kwargs.get("hide_thinking", False)

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
                    if event.message.stop_reason != StopReason.TOOL_USE.value:
                        agent_msg.is_stop = True
                        agent_msg.stop_reason = event.message.stop_reason
                        agent_msg.stop_details = event.message.stop_details
                        print(f"TASK STOP: {event.message.stop_reason}", flush=True)


            case "message_delta":
                # 消息增量事件，主要存放token数据、stop_reason、工具调用等
                # TODO 这里可以加token量记录相关功能，后续要加上
                pass
            case "content_block_start":
                block = {"index": event.index}
                block.update(dict(event.content_block))
                # 文本块开始事件,根据返回信息构建文本块，目前仅支持下面类型，额外的类型直接忽略
                if event.content_block.type in [MSG_THINK, MSG_TEXT, MSG_TOOL]:
                    if event.content_block.type == MSG_TOOL:
                        block["temp_input"] = ""

                    ai_msg.content.append(block)
                    if block.get("citations"):
                        print(f"Citations: {event.content_block.citations}", flush=True)

            case "content_block_delta":
                # 增量消息目前仅解析text、thinking、tool_use
                # 如果block丢失，则重新构建，极端情况下消息丢失的降级处理
                if ai_msg.content is None or len(ai_msg.content) == 0 or ai_msg.content[-1].get("index") != event.index:
                    if event.delta.type == "thinking_delta":
                        ai_msg.content.append({"index": event.index, "type": MSG_THINK, "thinking": event.delta.thinking})
                    elif event.delta.type == "text_delta":
                        ai_msg.content.append({"index": event.index, "type": MSG_TEXT, "text": event.delta.text})
                    # 工具调用如果start丢失，就不知道调用什么tool，直接忽略
                    # elif event.delta.type == "input_json_delta":
                else:
                    if event.delta.type == "thinking_delta":
                        if not hide_thinking:
                            print(f"[thinking] {event.delta.thinking[:1000]}...", end="", flush=True)
                        ai_msg.content[-1]["thinking"] = ''.join([ai_msg.content[-1]["thinking"], event.delta.thinking])
                    elif event.delta.type == "text_delta":
                        print(event.delta.text, end="", flush=True)
                        ai_msg.content[-1]["text"] = ''.join([ai_msg.content[-1]["text"], event.delta.text])
                    elif event.delta.type == "input_json_delta":
                        # 工具调用信息可能不是在一个delta里面传过来的，需要进行合并
                        ai_msg.content[-1]["temp_input"] = ''.join([ai_msg.content[-1]["temp_input"], event.delta.partial_json])

            case "content_block_stop":
                # 文本块结束
                if ai_msg.content is None or len(ai_msg.content) == 0 or ai_msg.content[-1].get("index") != event.index:
                    LOGGER.error("illegal block, content_block_stop without block info.")
                elif ai_msg.content[-1].get("type") == MSG_TOOL:
                    ai_msg.content[-1]["input"] = json.loads(ai_msg.content[-1]["temp_input"])
                    # 如果是工具调用请求block，则需要触发对应的agent逻辑
                    await tool_call(ctx, agent_msg, ai_msg.content[-1])
            case "message_stop":
                # 单turn对话流结束
                LOGGER.info("AI model single turn over.ai_msg id: %s", ai_msg.id)

    agent_msg.ai_msg = ai_msg
    return agent_msg


async def tool_call(ctx: SessionCtx, agent_msg: AgentMessages, tool_block):
    """处理大模型工具调用的agent包装方法"""
    name = tool_block.get("name")
    success, tool_resp, tool_obj = await route_tool_use(name, ctx, **tool_block.get("input"))
    # 工具调用信息
    agent_msg.user_content.append({"type": "tool_result", "tool_use_id": tool_block.get("id"), "content": tool_resp})
    print(f"TOOL RESP：{tool_resp[:500]}")
    if not success:
        LOGGER.info("AI model tool_call - %s fail: %s", name, tool_resp)
    elif tool_obj:
        # 工具调用额外的返回值，存储到tool_dict中
        agent_msg.tool_objs[name] = tool_obj

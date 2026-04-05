import asyncio

from base_comp.ai_model import client, MODEL
from base_comp.prompt import PROMPT_SYS_SUB_AGENT, PROMPT_SYS_ANALYSIS, SCHEDULER_NAME, sys_task_types, \
    PROMPT_SYS_DEFAULT, get_sys_prompt, ANALYSIS_NAME, PROMPT_SYS_TASK_SCHEDULER
from base_comp.schedule import TaskGraph, Task, MAX_SESSION_TASK
from base_comp.session import SessionCtx
from .common import StopReason
from manager.tools_manager import route_tool_use, get_tools_for_anthropic
from tools import register_tools, ToolTaskAnalysis, ToolTaskScheduler

# 初始化项目的若干组件
# 注册tools方法
register_tools()

# 主agent的各类可用工具信息（目前仅兼容anthropic标准，后续扩展其他标准）
ANTHROPIC_ALL_TOOLS = get_tools_for_anthropic()
ANALYSIS_TOOLS = [ToolTaskAnalysis().get_anthropic_schema()]
SCHEDULER_TOOLS = [ToolTaskScheduler().get_anthropic_schema()]


# ============================================================================
# agent会话入口，异步设计支持多会话并行
# ============================================================================
# 每一个会话都是一个单独的agent_loop，多个会话同时开启就是异步调用，但是会话内部逻辑都是基于同步的

async def agent_loop(session_ctx: SessionCtx, messages: list):
    """
    agent的单次任务的主进程循环，从用户的初始消息开始，完成任务退出循环
    使用异步方法，支持多任务并行

    :param session_ctx: agent会话信息，会话的生命周期内保持唯一
    :param messages: 初始的用户信息列表，存放主体上下文
    """

    # AI模型分析用户任务类别，获取精准的系统提示词
    session_sys_prompt = analysis_task(session_ctx, messages)

    if session_ctx.need_sub:
        # 如果需要任务拆分则专门调用任务拆分工具，并进入多任务执行模式
        # 构建task_graph
        schedule_task(session_ctx, messages)
        # 等任务调度器把所有子任务执行完毕
        await _run_task_scheduler(session_ctx, messages)
        # 把所有的子任务汇总信息一起发送给大模型

    # 主任务循环执行
    # 如果有任务拆分，现在的messages已经有了所有的子任务执行摘要
    # 如果没有任务拆分，就是单任务的模式
    while True:
        resp_msgs = client.messages.create(max_tokens=10*1024, messages=messages, model=MODEL, system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)

        # 如果模型端有stop_reason信息，则进行对应的逻辑处理
        # 不是调用工具导致的stop，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
        if resp_msgs.stop_reason != StopReason.TOOL_USE.value:
            if resp_msgs.stop_reason == StopReason.END_TURN.value:
                print(f"TASK FINISHED!")
            else:
                print(f"TASK STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
            return

        # 没有stop说明任务没结束，messages要保存所有的历史信息重新发起对话
        messages.append({"role": "assistant", "content": resp_msgs.content})
        # 调用统一的AI模型返回信息处理方法
        user_content = handle_resp_content(session_ctx, resp_msgs.content)
        # len > 0 说明本轮次有用户端信息，一并发送回AI端
        if len(user_content) > 0:
            messages.append({"role": "user", "content": user_content})


def analysis_task(session_ctx: SessionCtx, messages: list) -> str:
    """
    用户任务分析方法，单独发起一次AI对话，分析任务类别，判断任务复杂度
    """
    sys_prompt = PROMPT_SYS_DEFAULT
    analysis_info = client.messages.create(max_tokens=1024, messages=messages, model=MODEL, system=PROMPT_SYS_ANALYSIS,
                                           tools=ANALYSIS_TOOLS)
    for block in analysis_info.content:
        if block.type == "tool_use" and block.name == ANALYSIS_NAME:
            is_success, task_type = route_tool_use(block.name, session_ctx, **block.input)
            # 根据分析的类别注入更精准的提示词，ANALYSIS工具获取了分析结果直接返回
            if is_success:
                sys_prompt = get_sys_prompt(task_type)
                return sys_prompt
    # 如果分析失败就返回默认提示词
    # 这里不把返回信息加入messages，避免污染主任务上下文
    return sys_prompt


def schedule_task(session_ctx: SessionCtx, sch_msg: list) -> TaskGraph | None:
    """
    任务拆分规划方法，单独发起一次AI对话，拆分用户任务并分析依赖关系
    """
    # 防止任务拆分失败，循环执行，执行成功或达到一定阈值退出循环
    while True:
        resp_msgs = client.messages.create(max_tokens=10*1024, messages=sch_msg, model=MODEL,
                                               system=PROMPT_SYS_TASK_SCHEDULER,tools=SCHEDULER_TOOLS)
        # 如果模型端有stop_reason信息，则进行对应的逻辑处理
        # 不是调用工具导致的stop，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
        if resp_msgs.stop_reason != StopReason.TOOL_USE.value:
            if resp_msgs.stop_reason == StopReason.END_TURN.value and SessionCtx.task_graph is not None:
                print(f"SCHEDULE TASK FINISHED!")
                return SessionCtx.task_graph
            else:
                print(f"SCHEDULE TASK STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
                return None

        sch_msg.append({"role": "assistant", "content": resp_msgs.content})
        # 调用统一的AI模型返回信息处理方法
        user_content = handle_resp_content(session_ctx, resp_msgs.content)
        # len > 0 说明本轮次有用户端信息，一并发送回AI端
        if len(user_content) > 0:
            sch_msg.append({"role": "user", "content": user_content})


def handle_resp_content(sd: SessionCtx, content: list) -> list:
    """
    统一处理AI模型返回信息的方法
    :param sd       会话上下文信息
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
                _, tool_resp = route_tool_use(block.name, sd, **block.input)
                # 工具调用信息
                user_content.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_resp})
                print(f"TOOL RESP：{tool_resp[:1000] if len(tool_resp) > 1000 else tool_resp}")
            case "redacted_thinking":
                # 思考内容被隐藏，仅提示
                print("thinking... [内容已隐藏]")
    return user_content


async def _run_task_scheduler(ctx: SessionCtx, main_massage: list):
    """
    任务调度中心
    :param ctx:
    :param main_massage:
    :return:
    """
    # 多个子任务存在并发执行的情况
    # 所有的子任务共享一个SessionCtx，通过ctx控制并发和任务依赖关系
    # 所有的子任务都是单独的模型对话，彼此独立
    # 子任务的执行状态都会存到ctx里，使用ctx_lock给上下文上锁，避免并发问题

    ctx_lock = asyncio.Lock()       # 任务锁，所有子任务共用
    event = asyncio.Event()         # 协程事件，类似golang的通道，触发式的协程并发控制
    tasks = ctx.task_graph.get_executable_tasks()

    # 并发执行任务
    async with asyncio.TaskGroup() as tg:
        for task in tasks:
            # 修改任务的状态为执行中
            async with ctx_lock:
                ctx.task_graph.set_running(task.id)
                # 开启一个并发的执行协程
                tg.create_task(_sub_task_worker(ctx, task, ctx_lock, event, main_massage))

        # 循环接收新的任务, event 由任务执行端触发
        while True:
            await event.wait()
            async with ctx_lock:
                # 所有任务都完成直接跳出
                if ctx.task_graph.is_all_completed():
                    event.clear()
                    break
                add_tasks = ctx.task_graph.get_executable_tasks()
                # 已经完成了可执行任务的获取，重置event标记
                event.clear()

            if add_tasks:
                # 存在新解锁的任务，直接并发执行
                # 加锁改变任务状态为运行中
                async with ctx_lock:
                    for task in add_tasks:
                        tg.create_task(_sub_task_worker(ctx, task, ctx_lock, event, main_massage))
                        ctx.task_graph.set_running(task.id)

    # 所有子任务都完成了，添加相关提示
    main_massage.append({"role": "user", "content": "<reminder>All sub task completed. Please check it!</reminder>"})



async def _sub_task_worker(session_ctx: SessionCtx, task: Task, ctx_lock: asyncio.Lock, event: asyncio.Event, main_massage: list):
    """
    任务基本执行单元
    :param session_ctx:
    :param task:
    :param ctx_lock:
    :param main_massage:
    :return:
    """
    # 控制子任务的并发数
    async with session_ctx.semaphore:

        # main_massage是主任务的全局信息，包含了目前所有已经完成的子任务执行结果摘要
        # 以主任务全局信息为基底加上当前任务的prompt，构建新的模型对话
        # 这样当前任务的上下文不会污染主任务上下文，并且当前任务也获得了充足的前置信息
        messages = main_massage + [{"role": "user", "content": task.prompt}]

        # 单任务内部循环执行，收到LLM的停止消息再跳出循环
        while True:
            resp_msgs = client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL, system=PROMPT_SYS_SUB_AGENT,
                                               tools=ANTHROPIC_ALL_TOOLS)
            # messages要保存所有的历史信息
            messages.append({"role": "assistant", "content": resp_msgs.content})

            # 如果模型端有stop_reason信息，则进行对应的逻辑处理
            # 不是调用工具导致的stop，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
            if resp_msgs.stop_reason != StopReason.TOOL_USE.value:
                if resp_msgs.stop_reason == StopReason.END_TURN.value:
                    print(f"TASK-{task.id} FINISHED!")
                else:
                    print(f"TASK-{task.id} STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
                break

            # 调用统一的AI模型返回信息处理方法
            user_content = handle_resp_content(session_ctx, resp_msgs.content)

            # len > 0 说明本轮次有用户端信息，包装到发送给AI端的信息中
            if len(user_content) > 0:
                messages.append({"role": "user", "content": user_content})

        # 最后一轮对话就是子任务的总结信息，整理好然后写入到总任务的上下文中
        summary_text = "".join([block.text for block in resp_msgs.content if block.type == "text"]) or "[no summary]"
        summary_msg = {"role": "user", "content": {"type": "task_summary", "task_id": task.id, "content": summary_text}}

        # 任务执行完毕,同步任务状态
        async with ctx_lock:
            session_ctx.task_graph.set_completed(task.id)
            # 把汇总的子任务处理结果写入到总任务的上下文中
            main_massage.append(summary_msg)
            # 通知依赖当前任务的其他任务
            event.set()


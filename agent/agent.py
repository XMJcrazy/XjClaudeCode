import asyncio

from base_comp.ai_model import async_client, MODEL
from base_comp.prompt import PROMPT_SYS_SUB_AGENT, PROMPT_SYS_ANALYSIS, \
    PROMPT_SYS_DEFAULT, get_sys_prompt, ANALYSIS_NAME, PROMPT_SYS_TASK_SCHEDULER, PROMPT_TASK_MONITOR, TASK_SYNC
from base_comp.schedule import TaskGraph, Task
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

async def agent_loop(ctx: SessionCtx, messages: list):
    """
    agent的单次任务的主进程循环，从用户的初始消息开始，完成任务退出循环
    使用异步方法，支持多任务并行

    :param ctx: agent会话信息，会话的生命周期内保持唯一
    :param messages: 初始的用户信息列表，存放主体上下文
    """

    # AI模型分析用户任务类别，获取精准的系统提示词
    session_sys_prompt = await analysis_task(ctx, messages)

    if ctx.need_sub:
        # 如果需要任务拆分则专门调用任务拆分工具，并进入多任务执行模式
        # 构建task_graph
        await schedule_task(ctx, messages)

        # ================================================================================
        # * 所有的子任务都是单独的模型对话，彼此独立，部分并发执行，提升整体效率
        # * 所有的任务共享一个SessionCtx，通过ctx控制并发和任务依赖关系
        # * 子任务的执行状态都会存到ctx里，使用ctx_lock给上下文上锁，避免并发问题
        # * 使用TaskGroup管理所有异步任务，通过event触发，动态添加并发的子任务
        # * 任务状态监控，回退、重试等功能后面版本继续完善
        # ================================================================================
        async with asyncio.TaskGroup() as tg:
            # 任务触发器，主任务子任务共享，子任务完成，跨协程通知主任务
            event = asyncio.Event()

            # 主任务添加 [任务监控，子任务完成度检查] 相关的系统提示词补充
            session_sys_prompt = session_sys_prompt + PROMPT_TASK_MONITOR
            # 添加开始监听子任务的用户消息
            messages.append({"role": "user", "content": {[
                {"type": "text", "text": f"开始监控子任务完成状态，子任务完成之后会通知你，你负责验收就行，我会根据你的验收结果让子任务的agent执行修复"},
                # {"type": "text", "text": f"子任务开始执行，当前任务执行状态为-->{ctx.task_graph.to_dict()}"},
            ]}})

            # 主任务开启专门的模型对话，和子任务的上下文进行隔离
            # 第一次会话发送开始监听子任务的消息
            resp_msgs = await async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                           system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
            messages.append({"role": "assistant", "content": resp_msgs.content})
            user_context = await handle_resp_content(ctx,resp_msgs.content)
            if len(user_context) > 0:
                messages.append({"role": "user", "content": user_context})

            # 异步启动所有可执行子任务，和主任务并发执行
            async with ctx.ctx_lock:
                add_tasks = ctx.task_graph.get_executable_tasks()
                if add_tasks:
                    # 存在新解锁的任务，直接并发执行
                    for task in add_tasks:
                        tg.create_task(_sub_task_worker(ctx, task, event, messages))
                        ctx.task_graph.set_running(task.id)

            # 主任务持续监听子任务
            # 有子任务完成就把相关信息同步给主任务
            while True:
                await event.wait()
                # 主任务重新开始和大模型对话
                resp_msgs = await async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                               system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
                messages.append({"role": "assistant", "content": resp_msgs.content})
                async with ctx.ctx_lock:
                    # 主任务结束
                    if resp_msgs.stop_reason == StopReason.END_TURN.value and ctx.task_graph.is_all_completed():
                        print(f"MAIN TASK FINISHED-------------------------->!")
                        break
                    elif resp_msgs.stop_reason == StopReason.END_TURN.value:
                        # 模型对话正常结束，但是ctx的任务信息还没全部完成，模型可能提前结束了，提醒模型重新检查任务执行情况
                        messages.append({"role": "user", "content": [
                            {"type": "text", "text": "还有子任务没有完成，下面是目前的任务完成状态:"},
                            {"type": "text", "text": ctx.task_graph},
                        ]})
                    elif resp_msgs.stop_reason != StopReason.TOOL_USE.value:
                        print(f"MAIN TASK STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")

                user_content = []
                # 拆分消息块，并根据消息类型来分别处理
                for block in resp_msgs.content:
                    match block.type:
                        case "text":
                            print(f"TEXT ====> {block.text}")
                        case "thinking":
                            print(f"thinking...  {block.thinking[:1000]}..." if len(
                                block.thinking) > 1000 else f"thinking... {block.thinking}")
                        case "tool_use":
                            # 获取模型端返回的工具调用信息
                            is_success, tool_resp, rsp_obj = await route_tool_use(block.name, ctx, **block.input)
                            user_content.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_resp})
                            # 如果调用了子任务检查同步工具并且调用成功，就查看检查结果并启动对应的子任务
                            async with ctx.ctx_lock:
                                if block.name == TASK_SYNC and is_success:
                                    # 检测通过，修改对应子任务的状态，
                                    if rsp_obj.get("is_passed"):
                                        ctx.task_graph.set_completed(rsp_obj.get("task_id"))
                                    # 检测不通过，把对应子任务的状态重置成等待
                                    else:
                                        ctx.task_graph.set_pending(rsp_obj.get("task_id"))

                                    # 修改完状态之后，拉取新一轮的可执行任务，开始并发执行
                                    if ctx.task_graph.is_all_completed():
                                        # 所有子任务全部完成，让主任务再检查最后一遍
                                        user_content.append({"type": "text", "text": "All sub task finished! check it last time."})
                                    else:
                                        add_tasks = ctx.task_graph.get_executable_tasks()
                                        if add_tasks:
                                            # 存在新解锁的任务，直接并发执行
                                            for task in add_tasks:
                                                tg.create_task(_sub_task_worker(ctx, task, event, messages))
                                                ctx.task_graph.set_running(task.id)
                                        # 修改event标记，阻塞主任务循环,继续等待下次子任务完成
                                        event.clear()
                            print(f"TOOL RESP：{tool_resp[:1000] if len(tool_resp) > 1000 else tool_resp}")

                messages.append({"role": "user", "content": user_content})
    else:
        # 没有任务拆分就直接走单任务模式
        while True:
            resp_msgs = await async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL, system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)

            # 如果模型端有stop_reason信息，则进行对应的逻辑处理
            # 不是调用工具导致的stop，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
            if resp_msgs.stop_reason == StopReason.END_TURN.value:
                print(f"TASK FINISHED-------------------------->!")
                break
            elif resp_msgs.stop_reason != StopReason.TOOL_USE.value:
                print(f"TASK STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
                break

            # 没有stop说明任务没结束，messages要保存所有的历史信息重新发起对话
            messages.append({"role": "assistant", "content": resp_msgs.content})
            # 调用统一的AI模型返回信息处理方法
            user_content = await handle_resp_content(ctx, resp_msgs.content)
            # len > 0 说明本轮次有用户端信息，一并发送回AI端
            if len(user_content) > 0:
                messages.append({"role": "user", "content": user_content})


async def analysis_task(session_ctx: SessionCtx, messages: list) -> str:
    """
    用户任务分析方法，单独发起一次AI对话，分析任务类别，判断任务复杂度
    """
    sys_prompt = PROMPT_SYS_DEFAULT
    analysis_info = await async_client.messages.create(max_tokens=1024, messages=messages, model=MODEL, system=PROMPT_SYS_ANALYSIS,
                                                       tools=ANALYSIS_TOOLS)
    for block in analysis_info.content:
        if block.type == "tool_use" and block.name == ANALYSIS_NAME:
            is_success, task_type = await route_tool_use(block.name, session_ctx, **block.input)
            # 根据分析的类别注入更精准的提示词，ANALYSIS工具获取了分析结果直接返回
            if is_success:
                sys_prompt = get_sys_prompt(task_type)
                return sys_prompt
    # 如果分析失败就返回默认提示词
    # 这里不把返回信息加入messages，避免污染主任务上下文
    return sys_prompt


async def schedule_task(ctx: SessionCtx, messages: list) -> TaskGraph | None:
    """
    任务拆分规划方法，单独发起一次AI对话，拆分用户任务并分析依赖关系
    """
    # 防止任务拆分失败，循环执行，执行成功或达到一定阈值退出循环
    while True:
        resp_msgs = await async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                       system=PROMPT_SYS_TASK_SCHEDULER, tools=SCHEDULER_TOOLS)
        # 如果模型端有stop_reason信息，则进行对应的逻辑处理
        # 不是调用工具导致的stop，直接退出，任务执行完成（简单处理，还有其他几种停止类型没管，后续补上）
        if resp_msgs.stop_reason != StopReason.TOOL_USE.value:
            if resp_msgs.stop_reason == StopReason.END_TURN.value and ctx.task_graph is not None:
                # 任务拆分完成，打印任务信息
                print(f"SCHEDULE TASK FINISHED!")
                ctx.task_graph.print_graph()
                break
            elif resp_msgs.stop_reason == StopReason.END_TURN.value:
                print(f"SCHEDULE TASK ERROR! ctx task graph is none")
            else:
                print(f"SCHEDULE TASK STOP!  reason:{resp_msgs.stop_reason} \n content:{resp_msgs.content}")
                return None

        messages.append({"role": "assistant", "content": resp_msgs.content})
        # 调用统一的AI模型返回信息处理方法
        user_content = await handle_resp_content(ctx, resp_msgs.content)
        # len > 0 说明本轮次有用户端信息，一并发送回AI端
        if len(user_content) > 0:
            messages.append({"role": "user", "content": user_content})


async def handle_resp_content(ctx: SessionCtx, content: list) -> list:
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
                _, tool_resp = await route_tool_use(block.name, ctx, **block.input)
                # 工具调用信息
                user_content.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_resp})
                print(f"TOOL RESP：{tool_resp[:1000] if len(tool_resp) > 1000 else tool_resp}")
            case "redacted_thinking":
                # 思考内容被隐藏，仅提示
                print("thinking... [内容已隐藏]")
    return user_content


async def _run_task_scheduler(ctx: SessionCtx, main_massage: list, event: asyncio.Event):
    """
    任务调度中心
    :param ctx: 任务总的上下文
    :param main_massage: 主任务AI模型上下文
    :param event: 协程触发事件，类似golang的通道，触发式的协程并发控制
    """


    tasks = ctx.task_graph.get_executable_tasks()

    # 并发执行任务
    async with asyncio.TaskGroup() as tg:
        for task in tasks:
            # 修改任务的状态为执行中
            async with ctx.ctx_lock:
                ctx.task_graph.set_running(task.id)
                # 开启一个并发的执行协程
                tg.create_task(_sub_task_worker(ctx, task, event, main_massage))

        # 循环接收新的任务, event 由任务执行端触发
        while True:
            await event.wait()
            async with ctx.ctx_lock:
                # 所有任务都完成直接跳出
                if ctx.task_graph.is_all_completed():
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



async def _sub_task_worker(ctx: SessionCtx, task: Task, event: asyncio.Event, main_massage: list):
    """
    任务基本执行单元
    :param ctx: 会话上下文
    :param task: 任务信息
    :param main_massage: 和大模型的主对话上下文
    """
    # 控制子任务的并发数
    async with ctx.semaphore:

        # main_massage是主任务的全局信息，包含了目前所有已经完成的子任务执行结果摘要
        # 以主任务全局信息为基底加上当前任务的prompt，构建新的模型对话
        # 这样当前任务的上下文不会污染主任务上下文，并且当前任务也获得了充足的前置信息
        messages = main_massage + [{"role": "user", "content": task.prompt}]

        # 单任务内部循环执行，收到LLM的停止消息再跳出循环
        while True:
            resp_msgs = await async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL, system=PROMPT_SYS_SUB_AGENT,
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
            user_content = await handle_resp_content(ctx, resp_msgs.content)

            # len > 0 说明本轮次有用户端信息，包装到发送给AI端的信息中
            if len(user_content) > 0:
                messages.append({"role": "user", "content": user_content})

        # 最后一轮对话就是子任务的总结信息，整理好然后写入到总任务的上下文中
        summary_text = "".join([block.text for block in resp_msgs.content if block.type == "text"]) or "[no summary]"
        summary_msg = [{"role": "user", "content": {"type": "text", "text":{"task_id": task.id, "summary": summary_text}}}]

        # 任务执行完毕,把子任务完成的汇总信息同步给主任务
        async with ctx.ctx_lock:
            # 把汇总的子任务处理结果写入到总任务的上下文中
            main_massage.append(summary_msg)
            # 通知依赖当前任务的其他任务
            event.set()

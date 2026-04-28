import asyncio

from base_comp.ai_model import MODEL, create_anthropic_stream
from base_comp.prompt import PROMPT_SYS_SUB_AGENT, PROMPT_SYS_ANALYSIS, \
    PROMPT_SYS_DEFAULT, get_sys_prompt, ANALYSIS_NAME, PROMPT_SYS_TASK_SCHEDULER, PROMPT_TASK_MONITOR, TASK_SYNC, \
    prompt_inject, SCHEDULER_NAME
from base_comp.schedule import TaskGraph, Task
from base_comp.session import SessionCtx
from utils.log import LOGGER
from .common import StopReason
from manager.tools_manager import route_tool_use, get_tools_for_anthropic
from tools import register_tools, ToolTaskAnalysis, ToolTaskScheduler
from .message import process_stream

# 初始化项目的若干组件
# 注册tools方法
register_tools()

# 主工具集，避免任务不断做分析和拆分，分析和拆分的工具不在主工具集里面
ANTHROPIC_ALL_TOOLS = get_tools_for_anthropic()
# 分析工具集
ANALYSIS_TOOLS = [ToolTaskAnalysis().get_anthropic_schema()]
# 任务拆解工具集 = 主工具集 + 任务拆解工具集
SCHEDULER_TOOLS = [ToolTaskScheduler().get_anthropic_schema()] + ANTHROPIC_ALL_TOOLS


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
    LOGGER.info("START ANALYSIS TASK...")
    ok, analysis_info = await create_anthropic_stream(max_tokens=512, messages=messages, model=MODEL,
                                                         system=PROMPT_SYS_ANALYSIS, tools=ANALYSIS_TOOLS)
    if not ok:
        LOGGER.error(f"model chat error:{analysis_info}")

    session_sys_prompt, need_schedule = await analysis_task(ctx, messages)

    if need_schedule:
        # 先进行任务拆分
        LOGGER.info("START SCHEDULE TASK...")
        fail = await schedule_task(ctx, messages)
        if fail: return

        # 任务触发器，主任务子任务共享，子任务完成，跨协程通知主任务
        event = asyncio.Event()

        # 主任务添加 [任务监控，子任务完成度检查] 相关的系统提示词补充
        session_sys_prompt = prompt_inject(session_sys_prompt, root_path=ctx.session.root_path) + PROMPT_TASK_MONITOR
        # 添加开始监听子任务的用户消息
        messages.append({"role": "user", "content": [
            {"type": "text", "text": "开始监控子任务完成状态，子任务完成之后会通知你，你负责验收就行，我会根据你的验收结果让子任务的agent执行修复"},
        ]})

        # 第一轮对话发送，开始监听子任务的消息
        ok, resp_stream = await create_anthropic_stream(max_tokens=10 * 1024, messages=messages, model=MODEL, system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
        if not ok:
            LOGGER.error(f"TASK Error:{resp_stream}")
            return

        agent_msg = await process_stream(resp_stream, ctx, task_info="MAIN TASK")
        if agent_msg.stop_reason and agent_msg.stop_reason != StopReason.END_TURN.value:
            return

        messages.append(agent_msg.ai_msg)
        if agent_msg.user_content:
            messages.append({"role": "user", "content": agent_msg.user_content})

        # 并发执行子任务
        await _run_task_graph_mode(ctx, messages, session_sys_prompt, event)
    else:
        # 没有任务拆分就直接走单任务模式
        await _run_single_mode(ctx, messages, session_sys_prompt)


async def _run_single_mode(ctx: SessionCtx, messages: list, sys_prompt: str):
    """单任务模式"""
    while True:
        is_ok, resp_stream = await create_anthropic_stream(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                          system=sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
        if not is_ok:
            LOGGER.error(f"TASK Error:{resp_stream}")
            return

        # 处理流式消息，如果分析完毕直接返回
        agent_msg = await process_stream(resp_stream, ctx)

        if agent_msg.is_stop:
            return
        # 执行没结束，记录历史上下文，重新发起请求
        messages.append(agent_msg.ai_msg)
        if agent_msg.user_content: messages.append({"type": "user", "content": agent_msg.user_content})


async def analysis_task(session_ctx: SessionCtx, messages: list) -> tuple[str, bool]:
    """
    用户任务分析方法，单独发起一次AI对话，分析任务类别，判断任务复杂度
    """
    # 构造新的模型上下文，不污染主任务上下文
    analysis_msgs = [{"role":"user", "content":["分析下面任务的任务类别并判断是否需要进行任务拆分"]}] + messages
    for _ in range(6):
        # 为了避免单次分析失败，加入循环确认，最多交互N次（可以根据实际情况调整），超过N次还没解决就用默认agent类别
        is_ok, analysis_stream = await create_anthropic_stream(max_tokens=512, messages=analysis_msgs, model=MODEL, system=PROMPT_SYS_ANALYSIS, tools=ANALYSIS_TOOLS)
        if not is_ok:
            # 极端情况下存在的请求失败，记录失败原因然后重试
            LOGGER.error(f"model chat error:{analysis_stream}")
            continue

        # 处理流式消息，如果分析完毕直接返回
        agent_msg = await process_stream(analysis_stream, session_ctx)
        if agent_msg.tool_objs and ANALYSIS_NAME in agent_msg.tool_objs:
            obj = agent_msg.tool_objs.get(ANALYSIS_NAME)
            return get_sys_prompt(obj.get("task_type")), obj.get("need_schedule")
        else:
            # 分析失败
            analysis_msgs.append(agent_msg.ai_msg)
            if agent_msg.user_content: analysis_msgs.append({"type": "user", "content": agent_msg.user_content})

    # 分析失败，返回默认提示词
    return PROMPT_SYS_DEFAULT, False


async def schedule_task(ctx: SessionCtx, messages: list):
    """
    任务拆分规划方法，单独发起一次AI对话，拆分用户任务并分析依赖关系
    """
    task_fail = True
    task_msg = [msg.get("content") for msg in messages]
    schedule_msg = [{"role": "user", "content": [
        {"type": "text", "text": f"Below is the task details you need to breakdown and plan it: {task_msg}"},
        {"type": "text", "text": f"Just schedule it. Sync the task breakdown and planning results to me via tools: {SCHEDULER_NAME}"},
    ]}]

    schedule_msg += messages
    # 防止任务拆分失败，循环执行，执行成功或达到一定阈值退出循环
    while True:
        if ctx.task_graph is not None and ctx.task_graph.is_valid():
            ctx.task_graph.print_graph()
            task_fail = False
            break
        is_ok, resp_stream = await create_anthropic_stream(max_tokens=10 * 1024, messages=schedule_msg, model=MODEL,
                                                       system=PROMPT_SYS_TASK_SCHEDULER, tools=SCHEDULER_TOOLS, stream=True)
        if not is_ok:
            LOGGER.error(f"model chat error:{resp_stream}")
            break

        agent_msg = await process_stream(resp_stream, ctx, task_info="SCHEDULE TASK")
        if agent_msg.is_stop:
            if agent_msg.stop_reason == StopReason.END_TURN.value and ctx.task_graph is not None:
                ctx.task_graph.print_graph()
                task_fail = False
            elif agent_msg.stop_reason == StopReason.END_TURN.value:
                LOGGER.error(f"SCHEDULE TASK success! nut ctx task graph is none")
            break

        schedule_msg.append(agent_msg.ai_msg)
        if agent_msg.user_content:
            schedule_msg.append({"type": "user", "content": agent_msg.user_content})
    return task_fail


async def _run_task_graph_mode(ctx: SessionCtx, messages: list, session_sys_prompt, event: asyncio.Event):
    # ================================================================================
    # * 所有的子任务都是单独的模型对话，彼此独立，部分并发执行，提升整体效率
    # * 所有的任务共享一个SessionCtx，通过ctx控制并发和任务依赖关系
    # * 子任务的执行状态都会存到ctx里，使用ctx_lock给上下文上锁，避免并发问题
    # * 使用TaskGroup管理所有异步任务，通过event触发，动态添加并发的子任务
    # * 任务状态监控，回退、重试等功能后面版本继续完善
    # ================================================================================
    async with asyncio.TaskGroup() as tg:
        # 异步启动所有可执行子任务，和主任务并发执行
        async with ctx.ctx_lock:
            add_tasks = ctx.task_graph.get_executable_tasks()
            if add_tasks:
                # 存在新解锁的任务，直接并发执行
                for task in add_tasks:
                    ctx.task_graph.set_running(task.id)
                    tg.create_task(_sub_task_worker(ctx, task, event, messages))

        # 主任务持续监听子任务
        while True:
            await event.wait()
            # 任务失败也会触发event，先判断是否有失败任务，如果有就重新拉起
            async with ctx.ctx_lock:
                field_tasks = ctx.task_graph.get_field_tasks()
                if field_tasks:
                    for field in field_tasks:
                        # 单个任务有问题不影响其他任务，直接记录日志
                        ctx.task_graph.set_running(field.id)
                        tg.create_task(_sub_task_worker(ctx, field, event, messages))

            # 如果是有子任务执行完毕，则主任务重新开始和大模型对话开始验收
            ok, resp_stream = await create_anthropic_stream(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                            system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
            if not ok:
                LOGGER.error(f"TASK Error:{resp_stream}")
                break

            agent_msg = await process_stream(resp_stream, ctx, task_info="MAIN TASK")
            if agent_msg.is_stop:
                async with ctx.ctx_lock:
                    if agent_msg.stop_reason != StopReason.END_TURN.value:
                        break
                    elif ctx.task_graph.is_all_completed():
                        # 模型对话正常结束，但是任务状态异常，发送提醒+继续监听
                        messages.append({"role": "user", "content": [{"type": "text",
                            "text": f"Have sub-tasks not completed.Current task completion status:{ctx.task_graph}"}]})

            # 工具调用有额外的参数信息，需要进行处理
            if agent_msg.tool_objs:
                async with ctx.ctx_lock:
                    # 如果调用了子任务检查同步工具并且调用成功，就查看检查结果并启动对应的子任务
                    if TASK_SYNC in agent_msg.tool_objs:
                        sync_info = agent_msg.tool_objs[TASK_SYNC]
                        if sync_info.get("is_passed"):
                            ctx.task_graph.set_completed(sync_info.get("task_id"))
                        else:
                            ctx.task_graph.set_pending(sync_info.get("task_id"))

                        # 修改完状态之后，检查是否全部完成，如果不是，拉取可执行任务，并发执行
                        if ctx.task_graph.is_all_completed():
                            LOGGER.info(f"ALL SUB TASK COMPLETED!")
                            break
                        else:
                            add_tasks = ctx.task_graph.get_executable_tasks()
                            if add_tasks:
                                # 存在新解锁的任务，直接并发执行
                                for task in add_tasks:
                                    ctx.task_graph.set_running(task.id)
                                    tg.create_task(_sub_task_worker(ctx, task, event, messages))
                            # 修改event标记，阻塞主任务循环,继续等待下次子任务完成
                            event.clear()

            messages.append(agent_msg.ai_msg)
            if agent_msg.user_content:
                messages.append({"type": "user", "content": agent_msg.user_content})

async def _sub_task_worker(ctx: SessionCtx, task: Task, event: asyncio.Event, main_massage: list):
    """
    任务基本执行单元
    :param ctx: 会话上下文
    :param task: 任务信息
    :param main_massage: 和大模型的主对话上下文
    """
    # 控制子任务的并发数
    async with ctx.semaphore:
        LOGGER.info(f"task-{task.id} starting ----------------------------->")
        # task_status是全局任务信息，包含了目前所有的子任务执行状态
        # 子任务是独立的messages，和主任务分开
        # 这样当前任务的上下文不会污染主任务上下文，并且当前任务也获得了充足的前置信息
        async with ctx.ctx_lock:
            sub_agent_prompt = prompt_inject(PROMPT_SYS_SUB_AGENT, root_path=ctx.session.root_path)
            task_status = ctx.task_graph.to_dict()
        sub_messages = [
            {"role": "user", "content": task.prompt},
            {"role": "user", "content": f"Your task_id is：{task.id}，concurrent task status: {task_status}"},
        ]

        # 单任务内部循环执行，收到LLM的停止消息再跳出循环
        while True:
            is_ok, resp_msgs = await create_anthropic_stream(max_tokens=10 * 1024, messages=sub_messages, model=MODEL, system=sub_agent_prompt, tools=ANTHROPIC_ALL_TOOLS)
            if not is_ok:
                # 子任务出错直接退出并通知主任务协程
                LOGGER.error(f"model chat error:{resp_msgs}")
                async with ctx.ctx_lock:
                    ctx.task_graph.set_field(task.id)
                    event.set()
                return

            agent_msg = await process_stream(resp_msgs, ctx, task_info=task.id)
            # 判断本轮对话后是否完成任务
            if agent_msg.is_stop:
                if agent_msg.stop_reason != StopReason.END_TURN.value:
                    async with ctx.ctx_lock:
                        ctx.task_graph.set_field(task.id)
                else:
                    # 最后一轮对话就是子任务的总结信息，整理好然后写入到总任务的上下文中
                    summary_text = "".join([block.text for block in resp_msgs.content if block.type == "text"]) or "[no summary]"
                    summary_msg = {"role": "user", "content": [
                        {"type": "text", "text": f"Sub task: {task.id} has finished.Summary as follows: {summary_text} "},
                    ]}
                    # 把汇总的子任务处理结果写入到总任务的上下文中
                    async with ctx.ctx_lock:
                        main_massage.append(summary_msg)
                # 子任务结束，通知主任务协程,成功和失败均要通知
                event.set()
                break
            else:
                # 子任务尚未完成，历史信息加入上下文
                sub_messages.append({"role": "assistant", "content": resp_msgs.content})
                if agent_msg.user_content:
                    sub_messages.append({"type": "user", "content": agent_msg.user_content})
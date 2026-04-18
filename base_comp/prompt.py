"""
提示词管理模块
包括提示词的读取、初始化、格式化、调用等
"""
import json
import os.path
import re
from typing import Any

from base_comp import CONFIG_PATH

ANALYSIS_NAME = "task_analysis"
SCHEDULER_NAME = "task_scheduler"
TASK_SYNC = "task_sync"

# 任务类别，由AI模型来判断，不同类别对应不同系统提示词
# 目前支持下面的类别-编程、系统设计、私人助手、聊天机器人、任务规划、文档总结、网络搜索
# 后续可以扩展
sys_task_types = ["coding", "system design", "personal assistant", "chat robot", "task schedule", "doc summary", "web search"]

# 加载配置文件,初始化部分系统提示词
with open(os.path.join(CONFIG_PATH, 'prompt_template.json'), "r") as f:
    sys_conf = json.load(f)

# ============================================================================
# 提示词占位符注入的相关方法
# ============================================================================
def prompt_inject(text: str, **params: Any) -> str:
    return re.sub(r'\{([^}]+)\}', lambda m: str(params.get(m.group(1), m.group(0))), text)


# ============================================================================
# 各种类型的agent系统提示词
# ============================================================================

# 解决用户的问题之间会分析玩家问题种类，根据种类再调用对应的agent
PROMPT_SYS_ANALYSIS = prompt_inject(sys_conf.get("sys_analysis"), ANALYSIS_NAME=ANALYSIS_NAME) + str(sys_task_types)
# 任务拆分规划提示词，复杂任务需要调用大模型提前拆分任务，后续子任务可以多agent并行，提升执行效率
PROMPT_SYS_TASK_SCHEDULER = prompt_inject(sys_conf.get("task_scheduler"), SCHEDULER_NAME=SCHEDULER_NAME)


PROMPT_SYS_CODING = sys_conf.get("sys_coding")
PROMPT_SYS_DESIGN = sys_conf.get("system_design")
PROMPT_SYS_ASSISTANT = sys_conf.get("assistant")
PROMPT_SYS_CHAT = sys_conf.get("chat_robot")
PROMPT_SYS_SUMMARY = sys_conf.get("doc_summary")
PROMPT_SYS_SEARCH = sys_conf.get("web_search")
PROMPT_SYS_SUB_AGENT = sys_conf.get("sub_agent")
PROMPT_SYS_DEFAULT = sys_conf.get("sys_default")

def get_sys_prompt(task_type: str) -> str:
    """根据分析的任务类别返回对应的系统提示词"""
    match task_type:
        case "coding":
            return PROMPT_SYS_CODING
        case "system design":
            return PROMPT_SYS_DESIGN
        case "personal assistant":
            return PROMPT_SYS_ASSISTANT
        case "chat robot":
            return PROMPT_SYS_CHAT
        case "task schedule":
            return PROMPT_SYS_TASK_SCHEDULER
        case "doc summary":
            return PROMPT_SYS_SUMMARY
        case "web search":
            return PROMPT_SYS_SEARCH
        case _:
            return PROMPT_SYS_DEFAULT

# ============================================================================
# 补充提示词
# ============================================================================

# 工作路径补充提示词，代码类、工程类这些涉及到文件操作的任务，需要在系统提示词里面加上工作路径，避免用户消息里面的工作路径被稀释
PROMPT_WORKSPACE = " work path:{work_path}"

# 子任务摘要提示补充，一般用于压缩上下文
PROMPT_SUB_SUMMARY = " PS:Complete the given task,summarize your findings."

# 任务监控的补充提示词，主任务system要加上这一段确保实时监控子任务进展、验收子任务执行结果
PROMPT_TASK_MONITOR = f"""
    <main>
    You are an agent for task scheduling and monitoring. 
    After other agents complete the sub-tasks, they will summarize the execution results of the sub-tasks and put them into your context.
    When sub task finish just check it, don't need solve it.
    Use tool:{TASK_SYNC} tell user the check result.
    Only all sub task finished,you can send stop_reason.
    </main>
"""
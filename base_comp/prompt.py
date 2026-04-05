"""
提示词管理模块
包括提示词的读取、初始化、格式化、调用等
"""
import json

PROMPT_CONFIG = "prompt/prompt_template.json"

ANALYSIS_NAME = "task_analysis"
SCHEDULER_NAME = "task_scheduler"

# 任务类别，由AI模型来判断，不同类别对应不同系统提示词
# 目前支持下面的类别-编程、系统设计、私人助手、聊天机器人、任务规划、文档总结、网络搜索
# 后续可以扩展
sys_task_types = ["coding", "system design", "personal assistant", "chat robot", "task schedule", "doc summary", "web search"]

# 加载配置文件,初始化部分系统提示词
with open(PROMPT_CONFIG, "r") as f:
    sys_conf = json.load(f)

# 解决用户的问题之间会分析玩家问题种类，根据种类再调用对应的agent
PROMPT_SYS_ANALYSIS = str(sys_conf.get("sys_analysis")).replace("ANALYSIS_NAME", ANALYSIS_NAME) + str(sys_task_types)
# 任务拆分规划提示词，复杂任务需要调用大模型提前拆分任务，后续子任务可以多agent并行，提升执行效率
PROMPT_SYS_TASK_SCHEDULER = str(sys_conf.get("task_scheduler")).replace("SCHEDULER_NAME", SCHEDULER_NAME)


# ============================================================================
# 各种类型的agent系统提示词
# ============================================================================

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

# 摘要提示补充，一般用于压缩上下文
PROMPT_SUMMARY = " PS:Complete the given task,summarize your findings."


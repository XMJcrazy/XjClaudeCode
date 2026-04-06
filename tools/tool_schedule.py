"""
agent管理相关的工具模块
"""
from base_comp.prompt import SCHEDULER_NAME, ANALYSIS_NAME, sys_task_types
from base_comp.schedule import TaskGraph
from base_comp.session import SessionCtx
from base_comp.tool_base import ToolBase, ToolResp, TOOL_ERROR_AI, TOOL_SUCCESS


class ToolTaskAnalysis(ToolBase):
    """
    AI模型完成任务类别分析之后的回调工具
    """
    def __init__(self):
        self.name = ANALYSIS_NAME
        self.description = "同步用户任务分析结果,包含任务类别和是否需要拆分子任务"

    def execute(self, ctx: SessionCtx, task_type: str, need_schedule: bool = False) -> ToolResp:
        if task_type not in sys_task_types:
            return ToolResp(TOOL_ERROR_AI, f"illegal task_type，task_type must in {sys_task_types}")
        ctx.need_sub = need_schedule
        return ToolResp(TOOL_SUCCESS, task_type)

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "user task type"},
                "need_schedule": {"type": "bool"},
            },
            "required": ["task_type", "need_schedule"],
        }


class ToolTaskScheduler(ToolBase):
    """
    AI模型完成复杂任务拆分后的回调工具
    """
    def __init__(self):
        self.name = SCHEDULER_NAME
        self.description = "同步用户任务的拆解信息，包含任务拆解、任务依赖。整体结构为有向无环图"

    def execute(self, ctx: SessionCtx, summary: str, map_info: dict[str, str], deps: dict[str, list[str]]) -> ToolResp:
        # 前置验证
        if not ctx.need_sub:
            return ToolResp(TOOL_ERROR_AI, "simple task don't require split")
        if ctx.task_graph is not None:
            return ToolResp(TOOL_ERROR_AI, "task_graph has already been created")

        try:
            task_graph = TaskGraph.from_dict(summary, map_info, deps)
        except Exception as e:
            return ToolResp(TOOL_ERROR_AI, str(e))

        ctx.task_graph = task_graph
        return ToolResp(TOOL_SUCCESS)

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "user task summary"},
                "map_info": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                    },
                    "description": "任务的id和具体任务内容的映射关系 id -> task_desc",
                },
                "deps": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "description": "任务依赖关系，key是任务id，value是依赖的任务列表id，至少存在一个无前置依赖的任务",
                    "examples": [{"a": [], "b": ["a"], "c": ["a", "b"]}]
                }
            },
            "required": ["summary", "map_info", "deps"]
        }

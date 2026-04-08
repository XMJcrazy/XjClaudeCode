"""
agent管理相关的工具模块
"""
from base_comp.prompt import SCHEDULER_NAME, ANALYSIS_NAME, sys_task_types, TASK_SYNC
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

    async def execute(self, ctx: SessionCtx, task_type: str, need_schedule: bool = False) -> ToolResp:
        if task_type not in sys_task_types:
            return ToolResp(TOOL_ERROR_AI, f"illegal task_type，task_type must in {sys_task_types}")
        return ToolResp(tool_obj={"task_type": task_type, "need_schedule": need_schedule})

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
        self.description = """
            同步用户任务的拆解信息，包含任务拆解、任务依赖。
            整体结构为有向无环图，必须至少有一个起点，起点没有前置任务。
        """

    async def execute(self, ctx: SessionCtx, summary: str, map_info: dict[str, str], deps: dict[str, list[str]]) -> ToolResp:
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
                    "description": "任务依赖关系，所有任务都必须在里面（包括无前置依赖的任务），key是任务id，value是它依赖的任务id列表（无依赖的任务则value=[]），至少存在一个无依赖id的任务",
                    "examples": [{"a": [], "b": ["a"], "c": ["a", "b"]}]
                }
            },
            "required": ["summary", "map_info", "deps"]
        }


class ToolTaskSync(ToolBase):
    """
    主任务验收子任务执行情况同步的方法
    """
    def __init__(self):
        self.name = TASK_SYNC
        self.description = "when sub task check field,sync reason to user"

    async def execute(self, ctx: SessionCtx, task_id: str, is_passed: bool,reason: str) -> ToolResp:
        if ctx.task_graph and ctx.task_graph.get_task(task_id):
            return ToolResp(tool_obj={"task_id": task_id, "is_passed": is_passed, "reason": reason})
        else:
            return ToolResp(TOOL_ERROR_AI, f"illegal task_id {task_id}: not in ctx")


    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "sub task id"},
                "is_passed": {"type": "boolean", "description": "is check passed"},
                "reason": {"type": "string", "description": "sub task check field reason"},
            },
            "required": ["task_id", "is_passed", "reason"],
        }

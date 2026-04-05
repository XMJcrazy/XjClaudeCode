# """
# 生成和控制todoList的模块
# """
# from base_comp.session import SessionData, SubTask, TodoManager, TODO_NAME
# from base_comp.tool_base import ToolBase, ToolResp, TOOL_ERROR_AI, BaseResp
#
#
# def check_todo_info(sub_list: list[SubTask]) -> BaseResp:
#     """检查todoList子任务的状态合法性，如果不合法会返回不合法的原因"""
#     if sub_list is None or len(sub_list) == 0:
#         return BaseResp(False, "sub_list is none")
#
#     for i, task in enumerate(sub_list):
#         if task.status == "processing":
#             # 不允许前置任务没执行完就执行下一个
#             if i > 0 and sub_list[i-1].status != "finished":
#                 return BaseResp(False, "sub task status error.Pre task not finished but current task processing")
#         if task.status == "finished":
#             # 不允许前置任务没执行完就执行下一个
#             if i > 0 and sub_list[i-1].status != "finished":
#                 return BaseResp(False, "sub task status error.Pre task not finished but current task finished")
#
#     return BaseResp()
#
#
# class ToolTodo(ToolBase):
#     """任务拆分功能类，以工具的身份实现"""
#     def __init__(self):
#         super().__init__()
#         self.name = TODO_NAME
#         self.description = "这是一个接收并控制任务列表状态更新的方法，你完成了任务的拆分和完成子任务之后就可以调用本方法。子任务要求如下：len(sub_list) <= 12"
#
#     def execute(self, sd: SessionData, task_info: str, sub_list: list[dict]) -> ToolResp:
#         """
#         接收大模型的任务拆分信息，并进行任务流程控制和状态更新
#         :param sd: agent会话信息
#         :param task_info: 主任务描述
#         :param sub_list: 子任务列表，包含子任务信息和执行状态
#         """
#         # 前置验证
#         if sub_list is None or len(sub_list) == 0 or len(sub_list) > 12 :
#             return ToolResp(False, "sub_list is None or len > 12")
#         for i, v in enumerate(sub_list):
#             # id和序号必须一一对应
#             if "id" not in v or v["id"] != i:
#                 return ToolResp(TOOL_ERROR_AI, f"sub_list[i].id must equal array index")
#
#         # 把大模型返回的信息转化成agent对象
#         task_list: list[SubTask] = []
#         try:
#             for task in sub_list:
#                 if not isinstance(task, dict):
#                     return ToolResp(False, "sub_list[i] must be dict")
#                 task_list.append(SubTask(**task))
#         except Exception as e:
#             return ToolResp(False, f"sub_list[i] is illegal: {str(e)}")
#
#         # 第一次调用，进行TodoManager的初始化
#         if sd.todo_manager is None:
#             # 前置验证
#             if task_list[0].status == "finished" :
#                 return ToolResp(TOOL_ERROR_AI, f"sub_list init error sub_list[0].status default pending or processing")
#             # 第一个子任务切换为执行中状态，初始化TodoManager对象
#             sd.todo_manager = TodoManager(task_info, task_list)
#         else:
#             # 前置检查，确保AI模型返回的是正确的任务状态
#             info = check_todo_info(task_list)
#             if not info.succ:
#                 return ToolResp(False, info.desc)
#
#             # 更新任务执行状态
#             sd.todo_manager = TodoManager(task_info, task_list)
#         # 初始化或者更新任务列表都要进行,更新完打印在终端（后需要进行额外的处理，先打印示意）
#         print(sd.todo_manager.print_info())
#         return ToolResp(content="tool_todo --> success")
#
#     def _get_input_schema(self) -> dict:
#         return {
#             "type": "object",
#             "properties": {
#                 "task_info": {
#                     "type": "string",
#                     "description": "用户原始任务摘要"
#                 },
#                 "sub_list": {
#                     "type": "array",
#                     "items": {
#                         "type": "object",
#                         "properties": {
#                             "id": {"type": "integer", "description": "sub task id,begin with 0"},
#                             "info": {"type": "string"},
#                             "status": {"type": "string", "enum": ["pending","processing","finished"]},
#                         },
#                         "required": ["id", "info", "status"],
#                     },
#                     "description": "拆分的子任务信息，按照顺序执行子任务，完成之后修改子任务状态",
#                 },
#             },
#             "required": ["task_info", "sub_list"],
#         }
#
#

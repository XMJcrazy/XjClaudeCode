"""agent会话管理基础模块"""
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


# ============================================================================
# agent会话类
# ============================================================================

class Session:
    id: str                     # 会话ID
    # user_id: str              # 用户ID，后续扩展添加
    name: str                   # 会话名称，也是会话描述
    root_path: str              # 会话根路径，也就是创建会话的路径
    white_path: set[str]        # 当前会话白名单
    create_time: datetime       # 会话创建时间
    last_time: datetime         # 会话最近活跃时间

    def __init__(self, name: str, root_path: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.root_path = root_path
        self.white_path = {root_path}
        self.create_time = datetime.now()
        self.last_time = datetime.now()
        # 会话集合是公共对象，存在并发可能
        with session_lock:
            if root_path in sessions:
                sessions[root_path].append(self)
            else:
                sessions[root_path] = [self]

    def update_last_time(self):
        self.last_time = datetime.now()

    def add_white_path(self, path: str):
        self.white_path.add(path)

    def remove_white_path(self, path: str):
        self.white_path.remove(path)

    def reset_white_path(self):
        self.white_path = {self.root_path}


# 会话集合，按照根路径存放会话信息
sessions: dict[str, list[Session]] = {}
session_lock = threading.Lock()

# planning过程中调用其它工具次数超过10次没同步规划信息就发送提醒
TOOL_LIMIT_TIMES = 10
TODO_NAME = "tool_todo"

@dataclass
class SubTask:
    id: int                                 # 子任务id
    info: str                               # 子任务具体内容
    status: str = Literal["pending","processing","finished"]       #子任务执行状态，氛围等待中、执行中、执行完毕三个类型

@dataclass
class TodoManager:
    task_info: str                  # 用户输入的原始任务摘要
    sub_list: list[SubTask]         # 子任务执行信息
    other_times: int = 0            # 其他工具调用次数，如果一直不调用todolist工具,会给AI模型发相关提示信息督促按照流程走

    def print_info(self) -> str:
        if self.sub_list is None or len(self.sub_list) == 0:
            return ""
        info_list = [f"任务信息:{self.task_info}"]
        for task in self.sub_list:
            info_list.append(f"    {task.id}.{task.info}------>{task.status}")
        return "\n".join(info_list)

# ============================================================================
# agent会话数据包，包含会话信息和相关资源（会话内部独享），避免并发问题
# ============================================================================

@dataclass
class SessionData:
    session: Session
    todo_manager: TodoManager = None


"""agent会话管理基础模块"""
import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from base_comp.schedule import TaskGraph, MAX_SESSION_TASK


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


# ============================================================================
# agent会话数据包，包含会话信息和相关资源（会话内部独享），避免并发问题
# ============================================================================

@dataclass
class SessionCtx:
    session: Session                                    # 用户会话信息
    need_sub: bool = False                              # 是否需要拆分子任务
    task_graph: TaskGraph = None                        # 任务规划信息，采用有向无环图结构，后续的任务控制要依赖这个
    _semaphore: asyncio.Semaphore =field(default=None)  # 会话内的任务最大并发数，执行过程中不可更改

    # 每个会话对象的信号量是独立的，但是不需要主动设置，这里用post_init方法注入
    def __post_init__(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(MAX_SESSION_TASK)

    @property
    def semaphore(self):
        return self._semaphore




"""agent会话管理基础模块"""
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
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
        if root_path in sessions:
            sessions[root_path].append(self)
        else:
            sessions[root_path] = [self]

# 会话集合，按照根路径存放会话信息
sessions: dict[str, list[Session]] = {}

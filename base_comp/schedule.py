"""
任务调度、管理、编排基础模块
"""
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# 最大子任务数量，后续可以改成配置
MAX_NUM = 100
# 最大单会话并发任务数
MAX_SESSION_TASK = 6

class TaskState(Enum):
    """任务状态枚举"""
    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 执行中
    COMPLETED = "completed"  # 已完成
    FIELD = "field"  # 任务失败

@dataclass
class Task:
    """任务类，表示图中的一个节点"""
    id: str                                                 # 任务ID，就是任务序号
    prompt: str                                             # 任务具体prompt
    dependencies: List[str] = field(default_factory=[])     # 依赖的任务列表
    state: TaskState = TaskState.PENDING                    # 初始状态为等待中


class TaskGraph:
    """
    任务图类
    - summary: 总任务摘要
    - _tasks: 任务名到Task对象的映射
    - _adjacency: 邻接表，表示每个任务的依赖任务
    """

    def __init__(self, summary: str):
        self.summary = summary              # 总任务摘要，TaskGraph是一个总任务的具体分拆信息
        self.num = 0                        # task数量
        self.completed = 0                  # 完成的task数量
        self._tasks: Dict[str, Task] = {}   # 所有的task信息

    def add_task(self, id: str, name: str, dependencies: List[str] = None):
        """
        添加一个任务节点到图中
        :param: id: 任务id
        :param: name: 任务具体内容
        :param: dependencies: 该任务依赖的任务名称列表
        Raises:
            ValueError: 如果任务已存在或依赖的任务不存在
        """
        # 检查任务是否已存在
        if id in self._tasks:
            raise ValueError(f"任务 '{id}' 已存在")

        # 创建任务对象并存储
        self._tasks[id] = Task(id, name, dependencies)

    def _has_entrance(self) -> bool:
        """检查是否有入口，没有前置依赖的任务就是入口，可以有多个入口"""
        for task in self._tasks.values():
            if len(task.dependencies) == 0:
                return True
        return False

    def is_valid(self) -> bool:
        """
        检查任务图的合法性

        合法性条件：
        1. 图有起点，可以有多个
        2. 图无环（不存在循环依赖）
        3. 所有依赖的任务都存在
        4. 节点个数 <= MAX_NUM
        """
        # 空图是非法的
        if not self._tasks:
            return False

        # 检查是否有入口
        if not self._has_entrance():
            return False
        # 节点个数要小于等于指定值
        if len(self._tasks) > MAX_NUM:
            return False

        # 检查是否有环，避免死锁
        if self._has_cycle():
            return False

        # 检查所有依赖是否都存在，避免任务不可达
        if not self._all_dependencies_exist():
            return False

        return True

    def _has_cycle(self) -> bool:
        """
        使用深度优先搜索检测图中是否存在环
        """
        visited = set()  # 已访问的节点
        rec_stack = set()  # 当前递归栈中的节点

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            task = self._tasks.get(node)
            if not task:
                raise ValueError(f"任务 '{node}' 不存在")
            # 遍历该节点的所有下游节点
            for neighbor in task.dependencies:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # 遇到仍在递归栈中的节点，说明有环
                    return True

            rec_stack.remove(node)
            return False

        # 检查所有节点
        for task_id in self._tasks.keys():
            if task_id not in visited:
                if dfs(task_id):
                    return True
        return False

    def _all_dependencies_exist(self) -> bool:
        """
        检查所有任务的依赖是否都存在于图中
        Returns:
            bool: 所有依赖是否都存在
        """
        for task in self._tasks.values():
            for dep in task.dependencies:
                if dep not in self._tasks:
                    return False
        return True

    def print_graph(self) -> None:
        """打印任务图"""
        print(f"\n{'=' * 60}")
        print(f"TaskGraph: {self.summary}")
        print(f"Progress: {self.completed}/{self.num} tasks completed")
        print(f"{'=' * 60}")
        if not self._tasks:
            print("  (empty)")
            return
        for task_id, task in self._tasks.items():
            status_icon = "✓" if task.state == TaskState.COMPLETED else "○" if task.state == TaskState.PENDING else "◐"
            deps = f" [depends on: {', '.join(task.dependencies)}]" if task.dependencies else ""
            print(f"  {status_icon} [{task_id}] {task.prompt[:50]}{'...' if len(task.prompt) > 50 else ''}{deps}")
        print(f"{'=' * 60}\n")

    def to_dict(self) -> dict:
        """把当前任务状态转化成通用字典格式，方便同步给模型端"""
        return {
            "summary": self.summary,
            "num": self.num,
            "completed": self.completed,
            "tasks": {
                task_id: {
                    "id": task.id,
                    "prompt": task.prompt,
                    "dependencies": task.dependencies,
                    "state": task.state.value,  # Enum 转字符串
                }
                for task_id, task in self._tasks.items()
            }
        }

    @classmethod
    def from_dict(cls, summary: str, map_info: dict[str, str], deps: Dict[str, List[str]]) -> "TaskGraph":
        """
        从字典创建TaskGraph对象
        字典格式：{任务id: [依赖的id列表]} 例如：{"1": [], "2": ["1"], "3": ["1"], "4": ["1", "2"], "5": ["3"]}
        Args:
            summary: 总的任务摘要
            map_info: id -> config 映射关系
            deps: 任务依赖字典
        Returns:
            TaskGraph: 创建的任务图对象
        Raises:
            ValueError: 如果字典不能构成合法的任务图
        """
        graph_data = cls(summary)

        # 遍历字典，添加所有任务
        for id, dep in deps.items():
            if id not in map_info:
                raise ValueError("无效的任务图：存在无效的任务id，deps里面的所有任务id必须在map_info中")
            graph_data.add_task(id, map_info[id], dep)

        # 检查图的合法性
        if not graph_data.is_valid():
            raise ValueError(f"无效的任务图：必须满足有起点、无环、所有依赖均存在且task数量 <= {MAX_NUM}")
        graph_data.num = len(deps)
        return graph_data

    def get_task(self, id: str) -> Optional[Task]:
        """根据id获取任务"""
        return self._tasks.get(id)

    def set_pending(self, id: str):
        """将任务设置为等待状态"""
        task = self._tasks.get(id)
        if not task:
            raise ValueError(f"任务 '{id}' 不存在")
        task.state = TaskState.PENDING

    def set_field(self, id: str):
        """将任务设置为等待状态"""
        task = self._tasks.get(id)
        if not task:
            raise ValueError(f"任务 '{id}' 不存在")
        task.state = TaskState.FIELD

    def set_running(self, id: str):
        """将任务设置为运行状态"""
        task = self._tasks.get(id)
        if not task:
            raise ValueError(f"任务 '{id}' 不存在")
        if not self.can_execute(id):
            raise ValueError(f"任务 '{id}' 尚不可执行（依赖未完成或状态不是pending或field）")
        task.state = TaskState.RUNNING

    def set_completed(self, id: str):
        """将任务设置为完成状态"""
        task = self._tasks.get(id)
        if not task:
            raise ValueError(f"任务 '{id}' 不存在")

        if task.state != TaskState.RUNNING:
            raise ValueError(f"任务 '{id}' 必须处于运行状态才能标记为完成")

        task.state = TaskState.COMPLETED
        self.completed += 1

    def can_execute(self, id: str) -> bool:
        """
        判断任务是否可以执行

        可执行条件：
        1. 任务存在
        2. 任务状态是pending
        3. 所有依赖任务都已完成
        """
        task = self._tasks.get(id)
        if not task:
            return False

        # 状态必须是pending或者field才能启动
        if task.state != TaskState.PENDING and task.state != TaskState.FIELD:
            return False

        # 所有依赖必须已完成
        for dep in task.dependencies:
            if self._tasks[dep].state != TaskState.COMPLETED:
                return False

        return True

    def get_all_tasks(self) -> List[Task]:
        """获取图中所有任务"""
        return list(self._tasks.values())

    def get_completed_tasks(self) -> List[Task]:
        """获取所有已完成的任务"""
        return [t for t in self._tasks.values() if t.state == TaskState.COMPLETED]

    def get_running_tasks(self) -> List[Task]:
        """获取所有正在执行的任务"""
        return [t for t in self._tasks.values() if t.state == TaskState.RUNNING]

    def get_executable_tasks(self) -> List[Task]:
        """
        获取所有可执行的任务
        可执行任务定义：状态为pending且所有依赖都已完成
        """
        return [t for t in self._tasks.values() if self.can_execute(t.id)]

    def get_field_tasks(self) -> List[Task]:
        """获取执行失败的任务"""
        return [t for t in self._tasks.values() if t.state == TaskState.FIELD]

    def is_all_completed(self) -> bool:
        """判断是否所有任务都已完成"""
        # 完成的任务数量等于总任务数量就说明任务均完成
        return self.completed == self.num


if __name__ == "__main__":
    # 示例用法
    data = {
        "1": [],  # 起点，无依赖
        "2": ["1"],  # 依赖1
        "3": ["1"],  # 依赖1
        "4": ["2", "3"],  # 依赖2,3
        "5": ["4"]  # 依赖4
    }
    map = {"1":"task1", "2":"task2", "3":"task3", "4":"task4", "5":"task5"}
    # 从字典创建任务图
    try:
        graph = TaskGraph.from_dict("总任务", map, data)

        graph.print_graph()
        print(graph.to_dict())
        print(f"图是否合法: {graph.is_valid()}")
        print(f"所有任务: {graph.get_all_tasks()}")
        print(f"可执行任务: {graph.get_executable_tasks()}")
        # 执行任务流程
        graph.set_running("1")
        graph.set_completed("1")
        print(f"start完成后，可执行任务: {graph.get_executable_tasks()}")
        graph.set_running("2")
        graph.set_completed("2")
        print(f"a完成后，可执行任务: {graph.get_executable_tasks()}")
        graph.set_running("3")
        graph.set_completed("3")
        print(f"b完成后，可执行任务: {graph.get_executable_tasks()}")
        graph.set_running("4")
        graph.set_completed("4")
        print(f"c完成后，可执行任务: {graph.get_executable_tasks()}")
        graph.set_running("5")
        graph.set_completed("5")
        print(f"所有任务都完成: {graph.is_all_completed()}")
    except Exception as e:
        print(e)
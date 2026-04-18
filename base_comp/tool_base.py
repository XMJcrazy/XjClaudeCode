from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ============================================================================
# 基础工具类
# ============================================================================

TOOL_SUCCESS = 1
TOOL_ERROR_AI = 2           # 需要返回给模型端的异常
TOOL_ERROR_USER = 3         # 本地处理的异常

@dataclass
class BaseResp:
    """基础的调用检查返回对象"""
    succ: bool = True
    desc: str = ""

@dataclass
class ToolResp:
    status_code: int = field(default=TOOL_SUCCESS)              # 工具调用状态，成功失败超时等
    content: str = field(default="")                            # 简单回调文本，纯文本的返回内容都用这个
    tool_obj: object = field(default=None)                      # 工具调用返回对象，部分工具会返回特定对象


class ToolBase(ABC):
    """anthropic-tools基类"""
    name: str
    description: str

    @abstractmethod
    async def execute(self, *args, **kwargs) -> ToolResp:
        """
        调用tool的具体逻辑，由具体的实现类完成
        :param args: agent内部传递的参数，目前只有session，后面如果有就往后添加
        :param kwargs: AI模型调用工具提供的参数
        :return: ToolResp  工具调用返回值，包含调用状态，简单回调文本和复杂返回对象
        """

        raise NotImplementedError

    # 这个是针对anthropic规范的工具信息打包方法，后续要用其他平台的话，再写新方法就行
    def get_anthropic_schema(self) -> dict:
        """获取 Anthropic 格式的工具定义"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._get_input_schema()
        }

    @abstractmethod
    def _get_input_schema(self) -> dict:
        """子类实现，返回输入参数的 JSON Schema"""
        raise NotImplementedError

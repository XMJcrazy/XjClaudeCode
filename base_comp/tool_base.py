from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ============================================================================
# 基础工具类
# ============================================================================

TOOL_SUCCESS = 1
TOOL_ERROR = 2
TOOL_TIMEOUT = 3

@dataclass
class ToolResp:
    status_code: int = field(default=TOOL_SUCCESS)
    content: str = field(default="")

class ToolBase(ABC):
    """anthropic-tools基类"""
    name: str
    description: str
    # session: Session

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResp:
        """执行tool"""
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




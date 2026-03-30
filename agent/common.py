"""
这个module主要进行通用属性的配置和定义
"""
from enum import Enum

# anthropic 允许的停止原因，这里进行自定义实现，方便代码编写
# StopReason: TypeAlias = Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "pause_turn", "refusal"]
class StopReason(Enum):
    END_TURN="end_turn"              # 任务结束
    MAX_TOKENS="max_tokens"            # token超出上限
    STOP_SEQUENCE="stop_sequence"         # 用户定义的停止序列
    TOOL_USE="tool_use"             # 模型调用工具
    PAUSE_TURN="pause_turn"            # 任务暂停，等待人工介入
    REFUSAL="refusal"               # 内容被拦截、拒绝

    # 下面的两个是beta版本的参数，先不管
    # COMPACT=""               # 上下文压缩
    # MODEL_WINDOW=""          # 超出模型上下文窗口
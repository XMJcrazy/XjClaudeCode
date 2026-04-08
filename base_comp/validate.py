import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

# ============================================================================
# 工具调用的权限验证模块
# ============================================================================

""" 风险等级枚举 """
SAFE = 1  # 安全
LOW = 2  # 低风险
MEDIUM = 3  # 中风险
HIGH = 4  # 高风险
CRITICAL = 5  # 极高风险，直接拒绝

@dataclass
class CommandContext:
    """命令执行上下文"""
    command: str                                            # 基础操作指令
    args: list[str]                                         # 指令参数
    working_dir: Optional[str]                              # 执行路径
    white_dir: Optional[set[str]]                           # 安全路径，包括会话根路径和用户确认过的安全路径
    user = "agent"                                          # 执行主体，默认是agent
    task_id: str                                            # 任务ID，用来记录追踪执行过程

@dataclass
class ValidationResult:
    """验证结果"""
    allowed: bool                                           # 是否允许
    message: str = field(default="safe command")            # 操作信息
    risk_level: int = field(default=SAFE)                   # 操作风险级别
    suggestions: list[str] = field(default_factory=list)    # 风险建议信息
    requires_approval: bool = False                         # 是否需要人工审核



class CommandRule:
    """记录命令具体规则的静态类，用来做安全校验"""

    # 危险指令的正则表达式，部分指令，后续还要补充
    DANGEROUS_PATTERNS = [
        (r"rm\s+-rf\s+/", CRITICAL, "删除根目录"),
        (r"rm\s+-rf\s+\*", CRITICAL, "递归删除当前目录所有文件"),
        (r"rm\s+-rf\s+--no-preserve-root\s+/", CRITICAL, "禁用保护删除根目录"),
        (r"format\s+/\S+", CRITICAL, "格式化操作"),
        (r">\s*/dev/sd[a-z]", CRITICAL, "直接写入设备文件"),
        (r"dd\s+.*of=/dev/", CRITICAL, "dd 直接写入设备"),
        (r"mkfs\.\w+\s+/\S+", CRITICAL, "格式化文件系统"),
        (r"mount\s+/\S+\s+/\S+", CRITICAL, "挂载设备"),
        (r"umount\s+/\S+", CRITICAL, "卸载设备"),
        (r"chmod\s+777\s+", HIGH, "设置777权限"),
        (r"chmod\s+-R\s+777", HIGH, "设置777权限"),
        (r"chown\s+-R\s+\w+:\w+\s+", HIGH, "修改所有者"),
        (r"curl.*\|.*sh", HIGH, "远程脚本执行 (pipe to shell)"),
        (r"wget.*\|.*sh", HIGH, "远程脚本执行 (pipe to shell)"),
        (r"eval\s+\$", HIGH, "动态命令执行"),
        (r"exec\s+", HIGH, "命令替换"),
        (r"\|\s*sh", HIGH, "管道到 shell"),
        (r"--no-check-certificate", HIGH, "跳过证书验证"),
    ]
    # 白名单指令
    # 白名单的指令都是相对安全的指令，没有危险操作，权限相对更宽松
    ALLOWED_COMMANDS = {
        "python", "python3", "pip", "pip3",
        "git", "ls", "ll", "cat", "grep", "find", "echo",
        "curl", "wget", "head", "tail", "wc",
        "mkdir", "touch", "cp", "mv", "vi", "vim",
        "node", "npm", "yarn", "apt",
        "go", "cargo", "rustc",
    }

    # 危险路径，要确认之后才允许进行操作，优先级高于白名单，可能存在隐私泄露的风险
    DANGEROUS_PATHS = {"/etc/passwd", "/etc/shadow", "/etc/sudoers"}
    # SENSITIVE_DIRS = {"/", "/home", "/root", "/var", "/etc", "/sys", "/proc"}

    # 报错和提示信息
    NOTICE_DANGEROUS_CMD = "不要执行危险的删除/格式化指令或其他不安全的操作"
    ERROR_LOSS_ARGS = "loss args"
    ERROR_NOT_SUPPORTED_PATH = "not supported working path"
    ERROR_NOT_SUPPORTED_CMD = "not supported command"
    ERROR_NOT_SUPPORTED_EXTENSIONS = "not supported extensions"


def _handel_validate(result: ValidationResult) -> ValidationResult:
    """处理command指令验证不通过的方法"""
    # 不同的不通过原因要出发不同的操作
    # 禁止的危险操作，直接驳回。高危的危险操作转人工确认
    # todo 待编写具体实践
    return result

class ValidationStage(ABC):
    """
    验证阶段基类，
    类似langchain的链式操作，所有的验证都可以串起来
    """
    def __init__(self):
        self._next: Optional[ValidationStage] = None

    def __or__(self, stage: "ValidationStage"):
        """链式执行的基础，用 | 串起所有的验证链条"""
        self._next = stage
        return stage

    def validate(self, ctx: CommandContext) -> ValidationResult:
        """执行验证，返回结果或传递给下一个阶段"""
        result = self._validate(ctx)
        # 验证不通过或者执行到链尾，直接返回验证结果
        if not result.allowed or self._next is None:
            # 验证结束，打印验证消息
            return result
        # 验证通过则执行后一个验证步骤
        return self._next.validate(ctx)

    @abstractmethod
    def _validate(self, ctx: CommandContext) -> ValidationResult:
        """子类实现具体验证逻辑"""
        raise NotImplementedError


class DangerousValidator(ValidationStage):
    """危险操作验证，如果是危险操作，直接拒绝"""
    def __init__(self):
        super().__init__()
        # 构建对象内部的正则表达式信息
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), level, desc)
            for pattern, level, desc in CommandRule.DANGEROUS_PATTERNS
        ]

    def _validate(self, ctx: CommandContext) -> ValidationResult:
        """危险操作的验证操作"""
        # 拼接指令
        full_command = f"{ctx.command} {" ".join(ctx.args)}"
        highest_risk = SAFE

        # 验证是否为危险操作，如果是禁止执行的操作直接返回，不是就把危险级别放到结尾
        for pattern, risk_level, description in self._compiled_patterns:
            if pattern.search(full_command):
                if risk_level == CRITICAL:
                    # 验证不通过，调用钩子函数并退出验证链
                    return ValidationResult(allowed=False, risk_level=risk_level, message=f"危险操作: {description}", suggestions=[CommandRule.NOTICE_DANGEROUS_CMD])
                highest_risk = max(highest_risk, risk_level)

        if highest_risk == SAFE:
            return ValidationResult(allowed=True)

        return ValidationResult(allowed=True, risk_level=highest_risk, message="风险操作", requires_approval=highest_risk >= HIGH)


class PathValidator(ValidationStage):
    """路径验证，如果是会话创建根路径，直接通过，其他路径则要进行验证"""
    def _validate(self, ctx: CommandContext) -> ValidationResult:
        """指令路径相关的验证，防止操作敏感路径"""

        if not ctx.working_dir:
            return ValidationResult(allowed=False, risk_level=CRITICAL, message=f"{CommandRule.ERROR_LOSS_ARGS}: working_dir is none")

        # 指令参数或command里面是否包含危险路径，转人工
        for danger_path in CommandRule.DANGEROUS_PATHS:
            for arg in ctx.args:
                if danger_path in ctx.command or danger_path in arg:
                    return ValidationResult(allowed=False, risk_level=HIGH, requires_approval=True,
                                            message=f"{CommandRule.ERROR_NOT_SUPPORTED_PATH}: {ctx.working_dir} CMD: {ctx.command}")

        # 白名单指令直接通过，不涉及危险操作
        if ctx.command in CommandRule.ALLOWED_COMMANDS:
            return ValidationResult(allowed=True)

        # 不是白名单中的操作就要验证执行路径，在安全路径下就通过，否则需要人工干预
        working_dir = Path(ctx.working_dir).resolve()
        for allowed in ctx.white_dir:
            allowed_path = Path(allowed).resolve()

            if working_dir == allowed_path:
                return ValidationResult(allowed=True)
            try:
                if working_dir.relative_to(allowed):
                    return ValidationResult(allowed=True)
            except ValueError:
                continue
        return ValidationResult(allowed=False, risk_level=HIGH, requires_approval=True,
                                message=f"{CommandRule.ERROR_NOT_SUPPORTED_PATH}: {ctx.working_dir} CMD: {ctx.command}")

#
# class ResourceLimitValidator(ValidationStage):
#     """资源限制验证 - 内存、CPU、时间限制"""
#     # TODO 后续补充，这个版本先不管
#     MAX_MEMORY_MB = 512
#     MAX_CPU_SECONDS = 30
#     MAX_OUTPUT_LINES = 1000
#
#     async def _validate(self, ctx: CommandContext) -> ValidationResult:
#         return ValidationResult(allowed=True)
#
# class SdkValidator(ValidationStage):
#     """外部调用验证，一般是调用外部服务或接口"""
#     # TODO 后续补充，这个版本先不管
#     async def _validate(self, ctx: CommandContext) -> ValidationResult:
#         return ValidationResult(allowed=True)

class SdkValidator(ValidationStage):
    """外部调用验证，一般是调用外部服务或接口"""
    # TODO 后续补充，这个版本先不管
    def _validate(self, ctx: CommandContext) -> ValidationResult:
        return ValidationResult(allowed=True)


def init_validate() -> ValidationStage:
    """初始化验证组件，默认串联所有的基础验证"""
    # 把所有的验证组件串联起来，后续有扩充直接添加就行
    return DangerousValidator() | PathValidator()
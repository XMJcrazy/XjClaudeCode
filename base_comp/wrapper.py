"""
包装模块，负责对部分逻辑和功能进行安全包装
包括异常处理，超时控制，状态控制，流程控制等
"""
from typing import Coroutine, Any

from anthropic import AsyncAnthropic


# 大模型对话异常处理包装方法
# 先简单实现，后面再慢慢细化这个模块
async def anthropic_message(
    client: AsyncAnthropic,
    **kwargs
) -> tuple[bool, Message | str]:
    try:
        response = await client.messages.create(**kwargs)
        return True, response
    except RateLimitError as e:
        return False, f"速率限制: {e}"
    except AuthenticationError as e:
        return False, f"认证失败: {e}"
    except BadRequestError as e:
        return False, f"请求错误: {e}"
    except Exception as e:
        return False, f"未知错误: {e}"

async_client.messages.create(max_tokens=10 * 1024, messages=messages, model=MODEL,
                                                           system=session_sys_prompt, tools=ANTHROPIC_ALL_TOOLS)
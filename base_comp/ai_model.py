"""
AI模型操作模块
主要做不同的模型兼容和转化
"""
import asyncio
import os

import dotenv
from anthropic import Anthropic, AsyncAnthropic, AsyncStream

MODEL_TIME_OUT = 600

# 获取大模型相关的配置信息
dotenv.load_dotenv()
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL")

# 构建anthropic模型访问客户端，提供两种api客户端，根据业务场景使用
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)
async_client = AsyncAnthropic(base_url=BASE_URL, api_key=API_KEY)


# ============================================================================
# 模型对话包装信息
# ============================================================================

# 先简单实现，后面再慢慢细化这个模块
async def anthropic_message(client_: AsyncAnthropic, **kwargs):
    return await client_.messages.create(**kwargs)


# 大模型对话异常处理包装方法
async def create_anthropic_message(**kwargs):
    try:
        response = await asyncio.wait_for(anthropic_message(async_client, **kwargs), timeout=MODEL_TIME_OUT)
        if response is None or response.content is None:
            return False, f"model response illegal. response:{response}"
        return True, response
    except TimeoutError:
        return False, f"模型访问超时: time > {MODEL_TIME_OUT}s"
    except Exception as e:
        return False, str(e)

# 大模型流式对话异常处理包装方法
async def create_anthropic_stream(**kwargs):
    try:
        kwargs["stream"] = True
        response = await asyncio.wait_for(anthropic_message(async_client, **kwargs), timeout=MODEL_TIME_OUT)
        if not isinstance(response, AsyncStream):
            return False, f"model response illegal. response:{response}"
        return True, response
    except TimeoutError:
        return False, f"模型访问超时: time > {MODEL_TIME_OUT}s"
    except Exception as e:
        return False, str(e)

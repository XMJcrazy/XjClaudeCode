"""
AI模型操作模块
主要做不同的模型兼容和转化
"""
import os

import dotenv
from anthropic import Anthropic

# 获取大模型相关的配置信息
dotenv.load_dotenv()
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL")

# 构建anthropic模型访问客户端
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)


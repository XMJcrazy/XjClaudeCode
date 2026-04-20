"""
基础组件包
"""
import os

# 唯一的项目的根路径，避免测试的时候相对路径导包问题
ROOT_PATH = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(ROOT_PATH, "config")
LOG_PATH = os.path.join(ROOT_PATH, "data/logs")
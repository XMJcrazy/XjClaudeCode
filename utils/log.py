from datetime import date
import logging
from logging import Logger
from logging.handlers import RotatingFileHandler

import colorlog
from base_comp import LOG_PATH
from enum import Enum


# 日志存储方式
class LogType(Enum):
    DEBUG = 1       # 开发模式
    LOCAL = 2       # 本地运行模式
    SERVER = 3      # 服务器运行模式

LOGGER: Logger = logging.getLogger()

file_handler = RotatingFileHandler(f"{LOG_PATH}/{date.today()}.log", maxBytes=10240, backupCount=3)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
console_handler = logging.StreamHandler()


def get_logger(level=logging.INFO):
    """自定义的logger构造方法"""
    # 创建logger对象
    global LOGGER
    LOGGER.setLevel(level)
    # 创建控制台日志处理器
    console_handler.setLevel(level)
    # 定义颜色输出格式
    color_formatter = colorlog.ColoredFormatter(
        '%(asctime)s - %(name)s - %(log_color)s%(levelname)s: %(message)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    # 将颜色输出格式添加到控制台日志处理器
    console_handler.setFormatter(color_formatter)
    # 移除默认的handler
    for handler in LOGGER.handlers:
        LOGGER.removeHandler(handler)
    # 将控制台日志处理器添加到logger对象
    LOGGER.addHandler(console_handler)
    return LOGGER


def init_logger(tp: LogType, level=logging.INFO):
    global LOGGER
    match tp:
        case LogType.DEBUG:
            # 本地debug模式配置
            LOGGER = get_logger(level)
        case LogType.LOCAL:
            LOGGER = get_logger(level)
            # 本地服务器模式要添加日志文件输出
            LOGGER.addHandler(file_handler)
        case LogType.SERVER:
            # 线上不需要开启日志颜色功能
            LOGGER.setLevel(level)
            LOGGER.addHandler(file_handler)

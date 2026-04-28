"""异常处理工具包"""
from utils.log import LOGGER


def exception_handler(func):
    """通用异常捕捉装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            LOGGER.error(f"Exception in {func.__name__}: {e}")
    return wrapper


def exception_handler_func(exception_type, custom_handler):
    """指定异常类型和处理逻辑的装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                return result
            except exception_type as e:
                if custom_handler:
                    custom_handler(e)
                else:
                    LOGGER.error(f"Exception in {func.__name__}: {e}")
        return wrapper
    return decorator

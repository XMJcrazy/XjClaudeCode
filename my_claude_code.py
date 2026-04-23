"""
agent服务开启的总入口
"""


import asyncio


from agent.agent import agent_loop
from base_comp.session import Session, SessionCtx
from utils.log import init_logger, LogType, LOGGER

eg_output1 = "/Users/xingjun/PycharmProjects/Pacman/"

eg_task1 = f"""模仿这个网页：https://game.haiyong.site/dou.html 写一个同款的网页小游戏，用Typescript语言实现，项目写在:{eg_output1}路径下。具体要求如下：
            1.纯前端项目，本地开箱既玩。
            2.项目要有架构文档和设计说明，
            3.相关的素材贴图直接用这个网站的，如果下不下来，就自己去找类似的吃豆人素材
            4.代码要以模块的形式组织，确保项目的可读性
            5.所有的模块都要有详尽的测试，确保功能没bug
            6.项目完成之后，在项目根路径下写一个README.md文件，总结开发过程的痛点和卡点
    """


if __name__ == '__main__':
    # 初始化日志系统
    init_logger(LogType.LOCAL)
    messages = [
        {"role":"user", "content":eg_task1},
    ]

    # 初始化会话信息
    session = Session(name="test_chat", root_path=eg_output1)

    # 开始循环执行任务
    LOGGER.info("START TASK ...")
    asyncio.run(agent_loop(SessionCtx(session), messages))
    LOGGER.info("FINISH TASK ...")


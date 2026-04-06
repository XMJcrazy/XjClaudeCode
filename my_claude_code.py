"""
agent服务开启的总入口
"""


import asyncio


from agent.agent import agent_loop
from base_comp.schedule import TaskGraph
from base_comp.session import Session, SessionCtx

if __name__ == '__main__':
    output = "/Users/xingjun/Documents/data/doc"
    task1 = f"基于slg游戏玩法，编写一个符合actor设计模式的，用golang编写{output}"

    messages = [
        {"role":"user", "content":task1},
    ]

    # 初始化会话信息
    session = Session(name="test_chat", root_path=output)

    # 开始循环执行任务
    print("start tasks ...")
    asyncio.run(agent_loop(SessionCtx(session), messages))


import asyncio
from my_async.async_chain import benchmark_stream_vs_sequential

# langchain流式调用同步异步性能对比
asyncio.run(benchmark_stream_vs_sequential())
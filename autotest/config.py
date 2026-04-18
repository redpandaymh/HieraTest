# 导入库：os读取环境变量，Generation是DashScope的核心调用类
import os
from dashscope import Generation
# 发起调用：原生SDK的调用格式
response = Generation.call(
    # 从环境变量读取API-Key
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    # 模型名称，和兼容接口一致
    model="qwen-plus",
    # 消息内容，格式和兼容接口相同
    messages=[{"role": "user", "content": "你是谁？请简单介绍一下自己"}],
    # 输出格式：设置为“message”，让响应格式更易读
    result_format="message"
)
# 处理响应：先判断调用是否成功，再提取结果
if response.status_code == 200:
    # 调用成功，打印模型回答
    print("模型回答：")
    print(response.output.choices[0].message.content)
else:
    # 调用失败，打印错误信息（方便排查问题）
    print("调用失败：")
    print(f"错误码：{response.status_code}")
    print(f"错误信息：{response.message}")
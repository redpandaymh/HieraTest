import os

# 全局环境配置类型
class EnvType:
    LOCAL = "local"
    REMOTE = "remote"

class EnvConfig:
    def __init__(self):
        pass

# 一些默认常量，防止旧代码报错
model = "gpt-4o"
env = EnvType
DEEP_DEPENDENCY_MODE = False
ONE_CLASS_FOR_ONE_FOCAL_METHOD = True
ADD_TEST = True
GENERATION_SKIP = False

# 日志输出目录，从 README 看要求名为 BUILDING_DATA_AND_LOG_STORE_PATH
BUILDING_DATA_AND_LOG_STORE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "BUILDING_DATA_AND_LOG_STORE_PATH"))

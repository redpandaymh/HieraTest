import os
import sys


def get_package_name(file_path):
    """从Java文件路径中提取包名"""
    normalized_path = file_path.replace(os.sep, '/')

    # 查找标准源码目录结构
    for pattern in ['/src/main/java/', '/src/test/java/']:
        if pattern in normalized_path:
            split_path = normalized_path.split(pattern)
            if len(split_path) > 1:
                relative_path = split_path[1]
                package_path = os.path.dirname(relative_path)
                return package_path.replace('/', '.')
    return None


def get_test_file_path(original_path: str, class_name: str):
    """生成测试文件路径"""
    # 标准化路径为POSIX格式（统一使用/分隔符）
    normalized_path = original_path.replace(os.sep, '/')

    # 替换首个出现的src/main/java（不区分大小写）
    if 'src/main/java' in normalized_path:
        test_path = normalized_path.replace(
            'src/main/java',
            'src/test/java',
        )
        # 恢复原始路径大小写（除替换部分外）
        # test_path = normalized_path.split('src/main/java', 1)[0] + test_path.split('src/test/java', 1)[1]
    elif 'src/test/java' in normalized_path:
        # 那么默认不需要进行特殊的处理
        test_path = normalized_path
        pass
    else:
        test_path = normalized_path
    # else:
    #     raise ValueError("路径中未找到src/main/java目录结构")

    # 重组为系统路径格式
    test_path = test_path.replace('/', os.sep)
    test_dir = os.path.dirname(test_path)
    return os.path.join(test_dir, f"{class_name}Test.java")


def create_test_file(test_path):
    """创建测试文件"""
    if not os.path.exists(test_path):
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        return True
    return False


def generate_test_file(file_path: str, class_name: str):

    # 验证输入文件
    if not os.path.isfile(file_path) or not file_path.endswith('.java'):
        print(f"错误：'{file_path}' 不是有效的Java文件")
        # sys.exit(1)

    # # 提取包名
    # package_name = get_package_name(files_path)
    # if not package_name:
    #     print("无法从路径中识别包名，请确认文件在src/main/java目录下")
    #     sys.exit(1)

    # 生成测试文件
    test_path = get_test_file_path(file_path, class_name)

    if create_test_file(test_path):
        return True, test_path
        # print(f"成功创建测试文件：{test_path}")
    else:
        return False, test_path
        # print(f"测试文件已存在：{test_path}")


if __name__ == "__main__":
    # generate_test_file()
    print("A")

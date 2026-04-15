import os
import shutil
import subprocess
import argparse
import logging
import time
from pathlib import Path
from typing import List

from config.configs import EnvConfig
from utils.utils import find_minimal_submodules, execute_maven_capture


def build_classpath(classlist_path, randoop_jar):
    """
    构建完整的 classpath 字符串
    :param classlist_path: classlist.txt 文件路径
    :param randoop_jar: randoop-all jar 文件路径
    :return: 完整的 classpath 字符串
    """
    try:
        # 读取 classlist.txt 并处理路径
        with open(classlist_path, 'r') as f:
            content = f.read().strip()

        # 处理分号分隔的路径（兼容单行和多行格式）
        dependency_paths = [path.strip() for path in content.split(';') if path.strip()]
        # 添加基础路径
        classpath_parts = ['.', randoop_jar] + dependency_paths

        # 检查路径是否存在
        for path in classpath_parts[1:]:  # 跳过当前目录(.)
            if not Path(path).exists():
                logging.warning(f"路径不存在: {path}")

        return ';'.join(classpath_parts)

    except FileNotFoundError:
        logging.error(f"文件未找到: {classlist_path}")
        raise
    except Exception as e:
        logging.error(f"构建 classpath 时出错: {str(e)}")
        raise


def run_randoop(java_exe: str, classpath: str, classlist_path: str, output_limit: int, run_position: str,class_pathtxt_path:str):
    """
    执行 Randoop 命令
    :param run_position: 执行命令的位置
    :param java_exe: Java 可执行文件路径
    :param classpath: 完整的 classpath 字符串
    :param classlist_path: classlist.txt 文件路径
    :param output_limit: 输出限制
    """
    try:
        # 构建完整的命令
        cmd = [
            "&",
            f'"{java_exe}"',
            '-ea',
            '-classpath', f'"{classpath}"',  # 整个classpath用双引号包裹
            'randoop.main.Main',
            'gentests',
            f'--classlist={classlist_path}',
            f'--output-limit={output_limit}'
            # f'--classpath-file="{class_pathtxt_path}"'  # 使用classpath-file选项
        ]

        # logging.info(f"执行命令: {' '.join(cmd)}")

        full_cmd_list = [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-Command',  # 告诉PowerShell接下来是执行的命令字符串
            ' '.join(cmd)  # 将你的PowerShell命令部分拼接成一个字符串
        ]
        # 执行命令并实时输出
        process = subprocess.run(
            full_cmd_list,
            cwd=str(run_position),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False
        )

    except Exception as e:
        logging.error(f"执行 Randoop 时出错: {str(e)}")
        raise


def setup_logging():
    """配置日志系统"""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = f"randoop_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    logging.info(f"日志文件: {log_file}")


def copy_file_if_exists(source_path: str, destination_path: str) -> tuple[bool, str]:
    """
    检查源文件是否存在，如果存在，则将其复制到目标位置。

    Args:
        source_path (str): 源文件的完整路径。
        destination_path (str): 目标文件的完整路径（包括文件名）。
                                如果目标目录不存在，函数会尝试创建它。

    Returns:
        tuple[bool, str]: 一个元组，第一个元素是布尔值，表示操作是否成功。
                          第二个元素是字符串，包含操作结果或错误信息。
    """
    # 1. 检查源文件是否存在并且是一个文件
    if not os.path.isfile(source_path):
        if os.path.exists(source_path):
            # 路径存在，但不是一个文件（可能是目录或其他类型）
            return False, f"源路径 '{source_path}' 存在但不是一个文件，无法复制。"
        else:
            # 路径根本不存在
            return False, f"源文件 '{source_path}' 不存在，无法复制。"

    # 2. 确保目标目录存在
    # 获取目标文件所在的目录
    destination_dir = os.path.dirname(destination_path)

    # 如果目标目录部分不为空（即目标路径不仅仅是文件名）
    if destination_dir:
        try:
            # 创建目标目录，如果它不存在的话。exist_ok=True 避免目录已存在时抛出错误。
            os.makedirs(destination_dir, exist_ok=True)
            print(f"目标目录 '{destination_dir}' 已确认存在或已成功创建。")
        except OSError as e:
            return False, f"无法创建目标目录 '{destination_dir}': {e}"

    # 3. 复制文件
    try:
        # shutil.copy2 会复制文件数据和文件元数据（如修改时间、权限）。
        # 如果目标文件已存在，它将被覆盖。
        shutil.copy2(source_path, destination_path)
        return True, f"文件 '{source_path}' 已成功复制到 '{destination_path}'。"
    except shutil.SameFileError:
        return True, f"源文件和目标文件是同一个文件 '{source_path}'，无需复制。"
    except FileNotFoundError:
        # 理论上，os.path.isfile 已经检查过源文件，os.makedirs 也处理了目标目录。
        # 这种错误在这里发生通常意味着文件在检查后被删除或权限问题。
        return False, f"复制失败：找不到文件或路径问题。源: '{source_path}', 目标: '{destination_path}'"
    except PermissionError:
        return False, f"复制失败：权限不足，无法访问 '{source_path}' 或写入 '{destination_path}'。"
    except Exception as e:
        # 捕获其他任何可能发生的异常（如磁盘空间不足等）
        return False, f"复制文件时发生未知错误: {e}"


def main():
    # 需要使用randoop生成单元测试的项目根目录
    project_path = r"xxx"
    # java可执行文件地址
    java_path = r"xxx\bin\java.exe"
    # randoop-all的jar包
    randoop_jar_path = r"xxx\randoop-all-4.3.4.jar"
    output_limit = 600
    sub_module_list = find_minimal_submodules(root_dir=project_path)
    for sub_module_dir in sub_module_list:
        fqcn_list = get_fqcn_from_maven_classes(module_root_path=sub_module_dir)
        print()
        try:
            # 使用 'w' 模式打开文件，如果文件不存在则创建，如果存在则覆盖。
            # encoding='utf-8' 确保正确处理各种字符（尽管FQCN通常是ASCII）。
            with open(os.path.join(sub_module_dir, "target", "classes", "classlist.txt"), 'w', encoding='utf-8') as f:
                for fqcn in fqcn_list:
                    if "package-info" in fqcn:
                        continue
                    f.write(fqcn + '\n')  # 写入FQCN，并在末尾添加换行符
        except Exception as e:
            print(e)
        full_cmd_list = ["mvn", "dependency:build-classpath", "-Dmdep.outputFile=classpath.txt"]
        # 执行命令并实时输出
        process = subprocess.run(
            full_cmd_list,
            cwd=str(sub_module_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True
        )

        class_pathtxt_path = os.path.join(sub_module_dir, "classpath.txt")
        try:
            # 构建 classpath
            logging.info("开始构建 classpath...")
            classpath = build_classpath(class_pathtxt_path, randoop_jar_path)
            logging.info(f"Classpath 构建完成，长度: {len(classpath)} 字符")

            # 执行 Randoop
            logging.info("开始执行 Randoop...")
            run_position = os.path.join(sub_module_dir, "target", "classes")
            run_randoop(java_path, classpath, "classlist.txt", output_limit, run_position=run_position,class_pathtxt_path=class_pathtxt_path)

        except Exception as e:
            logging.critical(f"程序异常终止: {str(e)}")
            exit(1)
        generated_file = ["ErrorTest.java", "ErrorTest0.java", "RegressionTest.java", "RegressionTest0.java"]
        for file in generated_file:
            origin_file_path = os.path.join(sub_module_dir, "target", "classes", file)
            target_file_path = os.path.join(sub_module_dir, "src", "test", "java", file)
            copy_file_if_exists(source_path=origin_file_path, destination_path=target_file_path)

    print()


def get_fqcn_from_maven_classes(module_root_path: str) -> List[str]:
    """
    通过执行Maven命令并扫描target/classes目录获取类的全限定名称。
    """
    classes_dir = os.path.join(module_root_path, "target", "classes")

    # 首先尝试编译项目
    try:
        # 这里的 cwd 非常重要，确保是在模块的根目录执行命令
        process = subprocess.run(
            ["mvn", "clean", "compile"],
            cwd=module_root_path,
            capture_output=True,
            text=True,
            check=True,  # 如果mvn命令返回非零退出码则抛出异常
            shell=True  # 在Windows上可能需要shell=True来找到mvn命令
        )
        print("Maven构建成功。")
        # print("Maven stdout:\n", process.stdout) # 可以取消注释以查看构建输出
        # print("Maven stderr:\n", process.stderr)
    except FileNotFoundError:
        print("错误: 'mvn' 命令未找到。请确保Maven已安装并配置在PATH环境变量中。")
        return []
    except subprocess.CalledProcessError as e:
        print(f"Maven构建失败，返回码: {e.returncode}")
        print("Maven stdout:\n", e.stdout)
        print("Maven stderr:\n", e.stderr)
        return []
    except Exception as e:
        print(f"执行Maven命令时发生未知错误: {e}")
        return []

    # 扫描classes目录
    fqcns = set()
    if not os.path.isdir(classes_dir):
        print(f"警告: Maven构建输出目录 '{classes_dir}' 未找到。")
        return []

    for root, _, files in os.walk(classes_dir):
        for file in files:
            if file.endswith(".class"):
                # 获取相对于classes_dir的相对路径
                relative_path = os.path.relpath(os.path.join(root, file), classes_dir)
                # 将路径转换为类名，例如：com/example/MyClass.class -> com.example.MyClass
                class_name = relative_path.replace(os.sep, '.').replace('.class', '')
                fqcns.add(class_name)

    return sorted(list(fqcns))


# 找到一个大型项目的最小的子模块，然后在子模块的位置运行randoop程序，生成单元测试，并复制到指定位置

if __name__ == '__main__':
    main()

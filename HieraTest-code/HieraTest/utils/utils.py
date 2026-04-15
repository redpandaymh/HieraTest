import subprocess
import logging
import os
import shutil
from functools import wraps
import tokenize
from io import StringIO
import re

from utils.filter_rules import filter_rule_list

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 设置镜像源
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # 禁用警告
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"  # 完全禁用符号链接

from transformers import AutoTokenizer

from config.configs import Model, DEBUG_MOD, EnvConfig
import tree_sitter_java
from tree_sitter import Language, Parser, Node
from lxml import etree
# 引入 ElementTree 的默认解析器
from lxml.etree import XMLParser
from typing import List, Optional
from pathlib import Path
from enum import Enum, auto

from templates.pom_reference_template import maven_compiler_plugin_template, maven_compiler_plugin_template_top_module, \
    maven_compiler_plugin_lombok_dependency

# 指定提取的class和method的过滤元素
selected_keys_class = ["modifiers",
                       "extends",
                       "extends_identifiers",
                       "import_list",
                       "implements",
                       "fields",
                       "constructor_info",
                       "methods",
                       "type",
                       "generic_type_parameters",
                       "name",
                       "enum_constant"
                       ]
selected_keys_method = ["modifiers",
                        "return_type",
                        # "params",
                        "name"  # 这里的name就已经是函数签名了
                        ]

common_members_class_enum_interface = [
    "type",
    "name",
    "inner_classes",
    "inner_interfaces",
    # "generic_class_declarations",
    "full_name",
    "fields",
    "methods",
    "extends",
    "implements",
    "constructor_info",
    "modifiers",
    "package",

    # 泛型符号
    "generic_type_parameters",
    # enum 相关
    "enum_constant",
]


class MethodAttr(str, Enum):
    # return_type = "return_type"
    # params = "params"
    # modifiers = "modifiers"
    # file = "file"
    # exceptions = "exceptions"
    # line = "line"
    # name = "name"
    # generic_method_declaration = "generic_method_declaration"
    return_type = auto()
    params = auto()
    modifiers = auto()
    file = auto()
    exceptions = auto()
    line = auto()
    method_name = "name"
    generic_method_declaration = auto()


class FieldAttr(str, Enum):
    type = "type"
    modifiers = "modifiers"
    init_value = "init_value"
    field_name = "name"


class EnumConstantAttr(str, Enum):
    enum_name = "name"
    init_value = "init_value"


class ResultHandleMode(str, Enum):
    eliminate_mode = "eliminate_mode"
    fix_mode = "fix_mode"



ClassAttr = Enum(
    "ClassAttr",
    [(name, name)
     for name in common_members_class_enum_interface],  # 生成 (名称, 值) 的元组列表
    module=__name__,  # 显式指定模块名（可选）
    type=str  # 继承自 str，使成员值成为字符串
)

EnumAttr = Enum(
    "EnumAttr",
    [(name, name)
     for name in common_members_class_enum_interface],  # 生成 (名称, 值) 的元组列表
    module=__name__,  # 显式指定模块名（可选）
    type=str  # 继承自 str，使成员值成为字符串
)

InterfaceAttr = Enum(
    "InterfaceAttr",
    [(name, name)
     for name in common_members_class_enum_interface],  # 生成 (名称, 值) 的元组列表
    module=__name__,  # 显式指定模块名（可选）
    type=str  # 继承自 str，使成员值成为字符串
)


def init_parser():
    """
    初始化tree-sitter解析器
    args:
        None
    :return:
        tree-sitter：parser
    """
    # 加载 Java 语言解析器
    java_language = Language(tree_sitter_java.language())

    # 初始化解析器（无需显式调用 set_language）
    language_parser = Parser(java_language)  # 直接传入语言对象

    # print(language_parser.node_types)  # 应输出所有节点类型
    return language_parser


def get_tree_root(content: str) -> Node:
    parser = init_parser()
    # 解析语法树
    tree = parser.parse(bytes(content, "utf-8"))
    root_node = tree.root_node
    return root_node


def check_in_scope(check_list: list, left_bound: int, right_bound: int) -> bool:
    if any(left_bound <= x <= right_bound for x in check_list):
        return True
    else:
        return False


def get_error_list(check_list: list[dict], left_bound: int, right_bound: int) -> list:
    in_scope_list = [x for x in check_list if left_bound <=
                     int(x.get("Line", -1)) - 1 <= right_bound]
    return in_scope_list


def extract_java_code(text):
    # 优化后的正则表达式（支持格式容错）
    pattern = re.compile(
        r'```\s*java\s*([\s\S]*?)\s*```',  # 关键优化点
        flags=re.IGNORECASE | re.DOTALL
    )

    # 执行匹配
    match = pattern.search(text)

    # 返回逻辑
    return match.group(1).strip() if match else ""


def extract_json_code(text):
    # 优化后的正则表达式（支持格式容错）
    pattern = re.compile(
        r'```\s*json\s*([\s\S]*?)\s*```',  # 关键优化点
        flags=re.IGNORECASE | re.DOTALL
    )

    # 执行匹配
    match = pattern.search(text)

    # 返回逻辑
    return match.group(1).strip() if match else text.strip()


def ordered_dedup(lst):
    return list(dict.fromkeys(lst))


def execute_maven_capture(target_dir: str, full_command: list) -> dict:
    """
    在指定pom.xml目录执行完整Maven命令

    参数：
    target_dir   - 包含pom.xml的项目目录
    full_command - 完整的Maven命令列表（需包含mvn路径）

    返回：包含执行状态和日志的字典
    """
    # 路径标准化与校验
    project_path = Path(target_dir).resolve()

    # 校验目录和pom.xml
    if not project_path.is_dir():
        return {"code": -1, "error": f"目录不存在: {target_dir}"}
    if not (project_path / "pom.xml").exists():
        return {"code": -2, "error": "目标目录未包含pom.xml"}

    env_config = EnvConfig()
    java_home_path = env_config.jdk_path
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home_path

    try:
        # 执行命令
        result = subprocess.run(
            full_command,
            cwd=str(project_path),  # 直接指定工作目录
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,  # 禁用shell提升安全性
            check=False,  # 避免自动抛出异常
            env=env
        )

        return {
            "code": result.returncode,
            "output": result.stdout.strip(),
            "error": result.stderr.strip()
        }

    except Exception as e:
        raise ValueError("maven capture failed") from e


def ruled_filter_test_result(error_list: list) -> list:
    """
    检查传入的运行报错信息中是否存在指定的规则过滤内容，如果存在，则表明该函数需要被处理
    保留所有符合规则的报错信息

    :param error_list: 运行时错误的报错list
    :return: 经过检查符合对应规则的报错list
    """

    rule_set = set(filter_rule_list)
    # 第一层过滤，按照关键词保留需要过滤的错误
    filtered_error_list = [item for item in error_list if any(
        rule in item.get("Description", "") for rule in rule_set)]

    # 第二层过滤，针对空指针问题，将空指针报错发生在单元测试函数内部的错误添加到过滤列表中
    for error in error_list:
        err_msg = error.get("Description", "")
        err_file = error.get("File", "")
        if not err_file:
            continue
        if not err_file.endswith(".java"):
            err_file += ".java"
        if "java.lang.NullPointerException" not in err_msg:
            continue
        # 记录空指针的最外面的一帧，也就是空指针在何处发生
        first_null_pointer = ""
        err_msg_line_list = err_msg.splitlines()
        for line in err_msg_line_list:
            if line.strip().startswith("at"):
                first_null_pointer = line
                break
        if first_null_pointer and err_file in first_null_pointer:
            filtered_error_list.append(error)

    return filtered_error_list


def run_command(target_dir: str, command_list: list, task_env: dict) -> dict:
    # 确保目标目录存在
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)

    try:
        # 使用 cwd 参数指定工作目录
        # shell=True 允许你执行包含 shell 特性的命令，如管道、重定向等
        # 但要注意安全风险，如果命令来自用户输入，应避免 shell=True
        # capture_output=True 捕获标准输出和标准错误
        # text=True (或 encoding='utf-8') 将输出解码为字符串
        result = subprocess.run(
            command_list,
            cwd=target_dir,
            shell=False,
            capture_output=True,
            text=True,
            env=task_env,
            check=False
        )

        return {
            "code": result.returncode,
            "output": result.stdout.strip(),
            "error": result.stderr.strip()
        }

    except FileNotFoundError:
        print(f"错误：命令 '{command_list[0]}' 未找到。请确保它在 PATH 中。")
        return {}
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败！退出码: {e.returncode}")
        print(f"标准输出: {e.stdout}")
        print(f"标准错误: {e.stderr}")
        return {}
    except Exception as e:
        print(f"发生未知错误: {e}")
        return {}


def extract_defect4j_compile_error(log_string: str) -> list:
    """
    从 javac 编译报错信息中精确提取包含文件路径、行号和错误/警告关键字的日志块。

    Args:
        log_string: 包含 javac 编译日志的字符串。

    Returns:
        一个列表，其中每个元素是精确提取出的错误或警告日志块。
    """
    errors = []
    warnings = []
    lines = log_string.strip().split('\n')

    current_error_block = []

    # 正则表达式，用于匹配核心的错误/警告信息行
    # 它需要包含：可能的前缀 [javac]、文件路径、行号、错误/警告类型
    # 文件路径和行号的格式可能略有不同，这里使用一个相对宽泛的匹配
    # [\s\S] 用于匹配任何字符，包括换行符，以防文件路径或名称本身包含特殊字符
    error_start_pattern = re.compile(
        r"^\s*\[javac]\s+"  # 开头是 [javac] 加上空格
        r"(/.*?\.java:\d+)"  # 文件路径和行号（捕获组1）
        r":\s+"  # 文件路径和行号后面的冒号和空格
        r"(error|warning):"  # 错误或警告类型（捕获组2）
        r".*$",  # 匹配该行的剩余部分
        re.IGNORECASE  # 忽略大小写，以防意外的 'Error:' 或 'Warning:'
    )

    # 正则表达式，用于匹配 continuation 行 (以空格或制表符开头)
    continuation_pattern = re.compile(r"^\s{2,}")  # 匹配至少两个空格或制表符开头的行
    error_type = ""
    for i, line in enumerate(lines):
        # 首先尝试匹配核心错误/警告行
        match = error_start_pattern.match(line)

        if match:
            # 如果找到一个核心错误/警告行
            # 如果之前有正在收集的错误块，先将其添加到结果列表
            error_type = match.group(2)
            if current_error_block:
                if error_type == "error":
                    errors.append("\n".join(current_error_block))
                elif error_type == "warning":
                    warnings.append("\n".join(current_error_block))
                error_type = ""
            # 开始一个新的错误块，将当前行作为第一个元素
            current_error_block = [line]
        elif current_error_block:
            # 如果当前行不是核心错误/警告行，但我们正在收集错误块
            # 检查它是否是一个 continuation 行
            if continuation_pattern.match(line):
                current_error_block.append(line)
            else:
                # 如果不是 continuation 行，说明上一个错误块结束了
                # 将上一个错误块添加到结果列表
                if error_type == "error":
                    errors.append("\n".join(current_error_block))
                elif error_type == "warning":
                    warnings.append("\n".join(current_error_block))
                error_type = ""
                # 并重置 current_error_block 为空，准备接收新的错误
                current_error_block = []
        # else: 如果 current_error_block 为空，并且当前行不是核心错误行，则忽略该行 (例如，"Compiling 37 source files to...")

    # 循环结束后，如果还有未添加到列表的错误块，则添加它
    if current_error_block:
        errors.append("\n".join(current_error_block))

    # 最后一步清理：将每个错误块内的多余连续空格替换为单个空格
    # 注意：这里我们不移除换行符，而是将连续空格合并，保持原有的分行结构
    cleaned_errors = []
    for block in errors:
        # 将块内的所有连续空白字符（包括换行、空格、制表符）替换为单个空格，但保留基本的行结构
        # 更精细的清理：保留换行符，但合并同一行内的多余空格
        cleaned_lines = []
        for block_line in block.split('\n'):
            cleaned_lines.append(" ".join(block_line.split()))
        cleaned_errors.append("\n".join(cleaned_lines))

    return cleaned_errors


def extract_defect4j_test_error(log_string: str) -> int:
    # 正则表达式：匹配 "Failing tests: " 后面跟着一个或多个数字
    # (\d+) 捕获组会捕捉到数字
    match = re.search(r"Failing tests: (\d+)", log_string)

    if match:
        # match.group(1) 会返回捕获组中的字符串，即数字
        failing_tests_count_str = match.group(1)
        try:
            failing_tests_count = int(failing_tests_count_str)
            return failing_tests_count
        except ValueError:
            print(
                f"Could not convert '{failing_tests_count_str}' to an integer.")
    else:
        print("Could not find the number of failing tests in the line.")

    return 0


# ==============================================================================
# Java files find and analysis
# ==============================================================================

def find_file_path(target_file: str, search_dir: str) -> list:
    """
    在指定目录及其子目录中递归搜索文件

    参数:
        target_file (str): 要查找的文件名（含扩展名）
        search_dir (str): 搜索的根目录

    返回:
        list: 包含所有匹配文件绝对路径的列表（空列表表示未找到）

    异常:
        ValueError: 当 search_dir 不存在时抛出
    """
    # 检查目录是否存在
    if not os.path.isdir(search_dir):
        raise ValueError(f"目录不存在: {search_dir}")

    found_files = []
    search_dir = os.path.abspath(search_dir)  # 标准化路径

    # 使用 pathlib 实现更安全的遍历
    for file_path in Path(search_dir).rglob('*'):
        try:
            # 处理大小写不敏感（跨平台兼容）
            if file_path.is_file() and file_path.name.lower() == target_file.lower():
                found_files.append(str(file_path.resolve()))
        except PermissionError:
            # 忽略无权限访问的目录
            continue

    return found_files


def find_java_files(
        path: str,
        include_dirs: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
        exact_match: bool = False
) -> List[str]:
    """
    递归查找Java文件路径，精确控制包含目录范围

    :param path: 起始搜索路径
    :param include_dirs: 仅处理包含的目录名（默认None表示不限制）
    :param exclude_dirs: 排除的目录名（默认["test","target","build,".idea"]）
    :param exact_match: 目录名是否要求精确匹配（默认False模糊匹配）
    :return: Java文件绝对路径列表
    """
    default_exclude_dirs = ["test", "target", "build", ".idea", ".mvn", ".vscode", ".evosuite", "evo",
                            "chatunitest-tests", "temp"]
    exclude_dirs = exclude_dirs or default_exclude_dirs
    include_dirs = include_dirs or []
    java_files = []
    active_paths = set()

    base_path = os.path.abspath(path)
    if os.path.isfile(base_path):
        return [base_path] if base_path.endswith('.java') else []

    base_dir = os.path.join("src", "main", "java")
    for root, dirs, files in os.walk(base_path):
        if base_dir not in root:
            continue
        current_dir = os.path.basename(root)
        abs_root = os.path.abspath(root)
        relative_root = os.path.relpath(root, base_path)
        dir_name_list = relative_root.split(os.sep)

        parent_included = any(abs_root.startswith(p) for p in active_paths)

        if include_dirs:
            if exact_match:
                inner_include_dirs = False
                for include_dir in include_dirs:
                    include_dir_path = Path(include_dir)
                    # include_dir_name_list = include_dir.split(os.sep)
                    include_dir_name_list = list(include_dir_path.parts)
                    # 如果是单一的文件夹（如controller），那么只需要简单的判断是否在文件夹名称的list中就可以了
                    if len(include_dir_name_list) == 1:
                        if include_dir_name_list[0] in dir_name_list:
                            inner_include_dirs = True
                    # 否则就是连续的文件夹地址（如service/impl），那么就需要判断是否是文件夹名称的list的子串
                    else:
                        for i in range(len(dir_name_list) - len(include_dir_name_list) + 1):
                            # 检查从索引 i 开始的，长度等于 include_dir_name_list 的切片是否等于 include_dir_name_list
                            if dir_name_list[i: i + len(include_dir_name_list)] == include_dir_name_list:
                                inner_include_dirs = True
                    # if include_dir in abs_root:
                    #     inner_include_dirs = True
                    #     break
                dir_match = current_dir in include_dirs or inner_include_dirs
            else:
                dir_match = any(d in current_dir for d in include_dirs)

            if dir_match or parent_included:
                active_paths.add(abs_root)
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                java_files.extend(process_files(files, root))
            else:
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
        else:
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            java_files.extend(process_files(files, root))

    return ordered_dedup(java_files)


def delete_java_files_in_dir(directory: str, dry_run: bool = False):
    """
    递归删除指定目录及其子目录中的所有Java文件(.java)

    参数:
        directory (str): 要处理的根目录路径
        dry_run (bool): 为True时仅模拟操作不实际删除(默认False)

    返回:
        dict: 包含操作结果的字典 {
            'deleted': 已删除文件列表,
            'failed': 删除失败的文件列表及错误信息,
            'total': 总Java文件数
        }
    """
    # 验证目录有效性
    if not os.path.exists(directory):
        raise FileNotFoundError(f"目录不存在: {directory}")
    if not os.path.isdir(directory):
        raise NotADirectoryError(f"路径不是目录: {directory}")

    deleted_files = []
    failed_deletions = []
    java_count = 0

    # 遍历目录树[1,6,8](@ref)
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith('.java'):
                java_count += 1
                file_path = os.path.join(root, filename)

                try:
                    if dry_run:
                        # 模拟模式仅记录不删除
                        deleted_files.append(f"[模拟] {file_path}")
                    else:
                        # 实际删除文件[9,10](@ref)
                        os.remove(file_path)
                        deleted_files.append(file_path)
                except Exception as e:
                    # 记录删除失败的文件和原因
                    failed_deletions.append({
                        'file': file_path,
                        'error': str(e)
                    })


def get_test_base_path(full_path: str) -> str:
    """
    保留路径中第一个 'test' 或 'tests' 目录及之前的路径
    :param full_path: 原始路径（文件或目录）
    :return: 新文件夹路径（字符串）
    """
    # 获取目录部分（去掉文件名或最后一级目录名）
    dir_part = os.path.split(full_path)[0]
    # 拆分目录为层级列表（如 ['home', 'project', 'src', 'test']）
    parts = list(Path(dir_part).parts)

    # 搜索第一个 'test' 或 'tests' 目录的位置
    target_index = -1
    for i, part in enumerate(parts):
        if part.lower() in ['test', 'tests']:
            target_index = i
            break

    # 重建路径
    if target_index != -1:
        # 保留到目标目录（含）
        new_path = Path(*parts[:target_index + 1])
        return str(new_path)
    else:
        # 未找到时返回原始目录
        return dir_part


def process_files(files: List[str], root: str) -> List[str]:
    # 先简单的排除掉package-info.java
    default_excluded_java_file = ["package-info.java"]
    return [os.path.join(root, f) for f in files if f.endswith('.java') and f not in default_excluded_java_file]


def find_minimal_submodules(root_dir: str) -> list:
    """查找所有包含pom.xml且无子模块的目录"""
    candidates = []
    # 步骤1：收集所有包含pom.xml的目录
    for dirpath, _, filenames in os.walk(root_dir):
        if 'pom.xml' in filenames:
            candidates.append(dirpath)

    minimal_modules = []
    # 步骤2：验证每个候选目录是否为最小模块
    for candidate in candidates:
        if not _has_child_pom(candidate):
            minimal_modules.append(candidate)

    return minimal_modules


def _has_child_pom(candidate_dir: str) -> bool:
    """检查目录的子目录中是否存在pom.xml"""
    for root, _, filenames in os.walk(candidate_dir):
        if root == candidate_dir:
            continue  # 跳过当前目录本身
        if 'pom.xml' in filenames:
            return True
    return False


def find_top_level_module(root_dir: str) -> list:
    """
    查找Java项目中的顶层模块（包含pom.xml且层级最浅的目录）
    :param root_dir: 项目根目录路径
    :return: 顶层模块路径（可能有多个并列顶层模块）
    """
    root_dir = os.path.abspath(root_dir)
    candidates = []
    min_depth = float('inf')

    for dirpath, _, filenames in os.walk(root_dir):
        if 'pom.xml' in filenames:
            current_depth = _calculate_depth(root_dir, dirpath)

            # 动态更新候选列表
            if current_depth < min_depth:
                min_depth = current_depth
                candidates = [dirpath]
            elif current_depth == min_depth:
                if dirpath not in candidates:  # 避免重复添加
                    candidates.append(dirpath)

    return candidates if candidates else []


def _calculate_depth(root_dir: str, current_path: str) -> int:
    # 显式转换为字符串
    root_dir = str(Path(root_dir).resolve())
    current_path = str(Path(current_path).resolve())

    rel_path = os.path.relpath(current_path, root_dir)
    return len(Path(rel_path).parts) if rel_path != "." else 0


def get_current_dir_from_path(dir_path: str) -> str:
    path = Path(dir_path)
    folder_name = path.name
    return folder_name


def get_relative_path_str(top_dir: str, sub_dir: str) -> str:
    """
    计算两个目录之间的相对路径，并将其格式化为一个特定字符串。

    Args:
        top_dir: 顶层目录的路径字符串。
        sub_dir: 子目录的路径字符串。

    Returns:
        格式化后的相对路径字符串，包含顶层目录名和相对路径部分。
    """
    # 将输入的字符串转换为 Path 对象，类型检查器会知道这一点
    # 这里的类型转换是函数内部实现细节，不影响函数签名承诺的 str 输入
    _top_dir_path: Path = Path(top_dir)
    _sub_dir_path: Path = Path(sub_dir)

    # 使用 Path 对象进行操作
    relative_path: Path = _sub_dir_path.relative_to(_top_dir_path)

    # parts 是一个包含字符串的列表 (top_dir.name 是 str, relative_path.parts 是 str 的元组)
    # 显式注解 parts 的类型为 List[str]
    parts: List[str] = [_top_dir_path.name] + list(relative_path.parts)

    # ".".join(parts) 返回的是 str，这一点是符合函数返回类型注解的
    result: str = ".".join(parts)

    return result


class PomModifier:
    def __init__(self, pom_path: str):
        self.pom_path = pom_path
        # lxml.etree.XMLParser() 创建的是默认配置的解析器
        default_parser = XMLParser()
        self.tree = etree.parse(pom_path, parser=default_parser)
        self.root = self.tree.getroot()
        self.ns = {"ns": "http://maven.apache.org/POM/4.0.0"}

    @staticmethod
    def find_from_properties(root, property_name: str, namespaces: dict) -> str:
        version = root.xpath(f"//ns:properties/ns:{property_name}/text()", namespaces=namespaces)
        version = version[0]
        return version

    @staticmethod
    def get_component_version(root, version: str, namespaces: dict) -> str:

        if version.startswith("${") and version.endswith("}"):
            property_name = version.strip("${}")
            final_version = PomModifier.find_from_properties(root=root, property_name=property_name,
                                                             namespaces=namespaces)
        else:
            final_version = version
        return final_version

    def get_dependency_version_from_pom(self, dependency_name: str) -> str:
        target_dep = self.root.xpath(
            f"//ns:dependency[ns:artifactId='{dependency_name}']", namespaces=self.ns)
        version: str = ""
        if target_dep:
            if version := target_dep[0].xpath("ns:version/text()", namespaces=self.ns):
                version = version[0]
                version = self.get_component_version(
                    root=self.root, version=version, namespaces=self.ns)
        return version

    def get_plugin_info_from_pom(self, plugin_name: str) -> dict:
        # 查找特定插件
        plugin_elements = self.root.xpath(
            f"//ns:plugin[ns:artifactId='{plugin_name}']", namespaces=self.ns)
        plugin_info: dict = {}
        if plugin_elements:
            # 处理每个找到的插件
            for i, plugin in enumerate(plugin_elements, 1):
                # 1. 提取插件基本信息
                group_id = plugin.findtext(
                    "ns:groupId", namespaces=self.ns, default="org.apache.maven.plugins")
                artifact_id = plugin.findtext(
                    "ns:artifactId", namespaces=self.ns)
                version = plugin.findtext("ns:version", namespaces=self.ns)
                version = self.get_component_version(
                    root=self.root, version=version, namespaces=self.ns)
                plugin_info[artifact_id] = {
                    "groupId": group_id, "version": version, "artifact_id": artifact_id}

                # 2. 提取配置信息
                config_info: dict = {}
                config = plugin.find("ns:configuration", namespaces=self.ns)
                if config is not None:
                    # 提取主要配置项
                    encoding = config.findtext(
                        "ns:encoding", namespaces=self.ns)
                    source = config.findtext("ns:source", namespaces=self.ns)
                    target = config.findtext("ns:target", namespaces=self.ns)
                    compiler_id = config.findtext(
                        "ns:compilerId", namespaces=self.ns)
                    plugin_info[artifact_id]["configuration"] = {"encoding": encoding, "source": source,
                                                                 "target": target,
                                                                 "compiler_id": compiler_id}

        return plugin_info

    def _ensure_compiler_id(self) -> bool:
        """
        确保 maven-compiler-plugin 的 configuration 标签中的 compilerId 属性为 javac。
        如果不存在则添加，如果值不对则更新。
        返回 True 如果进行了修改或已满足条件，False 如果发生错误。
        """
        if self.root is None:
            print("Error: POM file not loaded properly.")
            return False

        compiler_plugin_elements = self.root.xpath("//ns:plugin[ns:artifactId='maven-compiler-plugin']",
                                                   namespaces=self.ns)

        if not compiler_plugin_elements:
            print(
                "Info: 'maven-compiler-plugin' not found in the POM. Cannot ensure compilerId.")
            return True  # 插件不存在不视为错误，但无法进行compilerId的确保
        else:
            for plugin in compiler_plugin_elements:
                configuration = plugin.find("ns:configuration", namespaces=self.ns)
                if configuration is None:
                    configuration = etree.SubElement(plugin, "{%s}configuration" % self.ns['ns'])
                    print("Info: Created 'configuration' tag for maven-compiler-plugin.")

                compiler_id_element = configuration.find("ns:compilerId", namespaces=self.ns)
                if compiler_id_element is None:
                    compiler_id_element = etree.SubElement(configuration, "{%s}compilerId" % self.ns['ns'])
                    compiler_id_element.text = "javac"
                    print("Info: Added 'compilerId' with value 'javac' to maven-compiler-plugin configuration.")
                elif compiler_id_element.text != "javac":
                    compiler_id_element.text = "javac"
                    print(f"Info: Updated 'compilerId' to 'javac' in maven-compiler-plugin configuration.")
                else:
                    print("Info: 'compilerId' is already 'javac' in maven-compiler-plugin configuration.")
            return True

    # --- 修改后的 _add_dependency_to_pom 方法 ---
    def _add_dependency_to_plugin(self, plugin_artifact_id: str, dependency_string: str) -> bool:
        """
        在指定插件的 dependencies 标签中添加给定的 dependency_string。
        如果插件或其 dependencies 标签不存在，则会创建它们。
        返回 True 如果成功添加，False 如果发生错误。
        """
        if self.root is None:
            print("Error: POM file not loaded properly.")
            return False

        # 1. 查找指定的插件
        plugin_xpath = f"//ns:plugin[ns:artifactId='{plugin_artifact_id}']"
        plugin_elements = self.root.xpath(plugin_xpath, namespaces=self.ns)

        if not plugin_elements:
            print(
                f"Info: Plugin with artifactId '{plugin_artifact_id}' not found. Cannot add dependency to it.")
            return False

        # 假设只有一个目标插件，如果可能存在多个，此处需要根据具体需求选择处理方式
        # 这里我们处理找到的第一个插件
        plugin_element = plugin_elements[0]

        # 2. 查找插件的 dependencies 标签
        plugin_dependencies_element = plugin_element.find("ns:dependencies", namespaces=self.ns)
        if plugin_dependencies_element is None:
            # 如果插件没有 dependencies 标签，则创建一个
            plugin_dependencies_element = etree.SubElement(plugin_element, "{%s}dependencies" % self.ns['ns'])
            # print(f"Info: Created 'dependencies' tag for '{plugin_artifact_id}' plugin.")

        # 3. 解析并添加给定的 dependency_string
        try:
            # 注意：wrapper 的 xmlns 声明应该与 self.ns['ns'] 匹配
            wrapper = \
                f"""
                <dependencies xmlns="{self.ns["ns"]}">
                        {dependency_string}
                </dependencies>
                """

            # 解析 wrapper，然后获取第一个子元素（期望是 dependency）
            dependency_container = etree.fromstring(wrapper)
            # 因为只有一个元素，所以应该可以直接提取出来
            new_dependency = dependency_container.find('*')

            if new_dependency is not None and new_dependency.tag.endswith('dependency'):
                # 检查是否已存在相同的 dependency (这里使用简单的字符串比较，不够健壮)
                # TODO: 实现对于dependency的去重

                # 将新依赖添加到插件的 dependencies 下
                plugin_dependencies_element.append(new_dependency)
                return True
            else:
                return False
        except etree.XMLSyntaxError:
            print(
                f"Error: Invalid XML syntax in provided dependency_string: {dependency_string}")
            return False
        except Exception as e:
            print(
                f"An unexpected error occurred while adding dependency to plugin: {e}")
            return False

    def get_compiler_plugin_as_string(self, dependency_string_to_add: str) -> Optional[str]:
        """
        查找 maven-compiler-plugin，确保其 compilerId 为 javac，
        在 maven-compiler-plugin 的 dependencies 中添加给定的依赖字符串，
        然后返回修改后的整个 plugin 元素（包括其子节点）的字符串表示。

        Args:
            dependency_string_to_add: 要添加到 maven-compiler-plugin 的 dependencies 标签中的字符串，格式如 "<dependency>...</dependency>"

        Returns:
            Optional[str]: 如果成功找到了 maven-compiler-plugin 并进行了必要的修改，则返回其 XML 字符串；
                           否则返回 None。
        """
        if self.root is None:
            print("Error: POM file not loaded properly.")
            return None

        # 1. 确保 compilerId 是 javac
        if not self._ensure_compiler_id():
            print("Failed to ensure compilerId for maven-compiler-plugin.")
            return None

        # 2. 将指定的依赖添加到 maven-compiler-plugin 的 dependencies 中
        if not self._add_dependency_to_plugin("maven-compiler-plugin", dependency_string_to_add):
            print("Failed to add the specified dependency to maven-compiler-plugin.")
            return None

        # 3. 找到修改后的 maven-compiler-plugin 元素
        compiler_plugin_elements = self.root.xpath("//ns:plugin[ns:artifactId='maven-compiler-plugin']",
                                                   namespaces=self.ns)

        if not compiler_plugin_elements:
            print("Error: 'maven-compiler-plugin' not found after modifications.")
            return None
        elif len(compiler_plugin_elements) > 1:
            print(
                "Warning: Multiple 'maven-compiler-plugin' found. Returning the first one.")
            plugin_element = compiler_plugin_elements[0]
        else:
            plugin_element = compiler_plugin_elements[0]

        # # 4. 保存修改后的 POM 文件
        # try:
        #     self.tree.write(self.pom_path, pretty_print=True, xml_declaration=True, encoding='utf-8')
        #     print(f"Success: Modified POM file saved to {self.pom_path}")
        # except Exception as e:
        #     print(f"Error saving POM file: {e}")
        #     # 即使保存失败，也尝试返回插件字符串

        # 5. 将找到的 plugin 元素转换为字符串
        return etree.tostring(plugin_element, encoding='unicode', pretty_print=True)

    def add_compiler_plugin_to_pom(self, plugin_str: str):
        """
            固定功能:删除原有的compiler_plugin,向pom中添加新的compiler_plugin
        :return:
        """

        # XPath查找所有匹配的plugin元素
        xpath_expr = f'//ns:plugin[ns:artifactId="maven-compiler-plugin"]'
        plugins = self.root.xpath(xpath_expr, namespaces=self.ns)

        # 删除找到的插件
        for plugin in plugins:
            parent = plugin.getparent()
            if parent is not None:
                parent.remove(plugin)

        # 将字符串转换为带命名空间的元素
        wrapper = f'<plugins xmlns="{self.ns["ns"]}">{plugin_str}</plugins>'
        plugin_element = etree.fromstring(wrapper)[0]

        # 查找或创建 build -> plugins 节点
        build = self.root.find("ns:build", namespaces=self.ns)
        if build is None:
            build = etree.SubElement(self.root, etree.QName(self.ns["ns"], "build"))

        plugins = build.find("ns:plugins", namespaces=self.ns)
        if plugins is None:
            plugins = etree.SubElement(build, etree.QName(self.ns["ns"], "plugins"))

        # 添加插件到plugins节点末尾
        plugins.append(plugin_element)

        # 美化XML格式并保存
        self.tree.write(self.pom_path,
                        encoding="utf-8",
                        xml_declaration=True,
                        pretty_print=True,
                        standalone=False)


def modify_pom_top():
    # 考虑到顶层的pom比较复杂，暂未自动修改
    # TODO: 针对顶层pom的自动化修改
    pass


def recover_pom_top():
    # TODO: 针对顶层pom的恢复
    pass


def backup_restore_factory(func):
    """通过函数参数传递路径"""

    @wraps(func)
    def wrapper(dir_path, ori_file_name, tmp_file_name, *args, **kwargs):
        backup_file(dir_path, ori_file_name, tmp_file_name)
        try:
            return func(dir_path, ori_file_name, tmp_file_name, *args, **kwargs)
        finally:
            restore_file(dir_path, ori_file_name, tmp_file_name)

    return wrapper


@backup_restore_factory
def modify_file(dir_path: str, ori_file_name: str, tmp_file_name: str):
    print(f"动态处理文件: {os.path.join(dir_path, ori_file_name)}")


# ==============================================================================
# Calculate token consumption during interaction with LLM
# ==============================================================================

def calculate_token(model: str, instructions: list) -> int:
    if model == Model.DeepSeekV3_BaiLian:
        model = "deepseek-ai/DeepSeek-V3-0324"
    elif model == Model.DeepSeekR1:
        model = "deepseek-ai/DeepSeek-R1"
    elif model == Model.Qwen25:
        model = "Qwen/Qwen2.5-72B-Instruct"
    else:
        model = "deepseek-ai/DeepSeek-V3-0324"
    # 拼接所有对话内容
    full_text = " ".join([item.get("content", "") for item in instructions])
    tokenizer = AutoTokenizer.from_pretrained(model)
    tokens = tokenizer.encode(full_text, add_special_tokens=False)
    token_count = len(tokens)
    return token_count


# ==============================================================================
# path selection func needed
# ==============================================================================
def remove_comments_and_docstrings(source, lang):
    if lang in ['python']:
        io_obj = StringIO(source)
        out = ""
        prev_toktype = tokenize.INDENT
        last_lineno = -1
        last_col = 0
        prev_tokstr = ""
        for tok in tokenize.generate_tokens(io_obj.readline):
            token_type = tok[0]
            token_string = tok[1]
            start_line, start_col = tok[2]
            end_line, end_col = tok[3]
            ltext = tok[4]
            if start_line > last_lineno:
                last_col = 0
            if start_col > last_col:
                out += (" " * (start_col - last_col))
            if token_type == tokenize.COMMENT:
                pass
            elif token_type == tokenize.STRING:
                if prev_toktype != tokenize.INDENT:
                    if prev_toktype != tokenize.NEWLINE:
                        if start_col > 0:
                            out += token_string
            else:
                out += token_string
            prev_toktype = token_type
            prev_tokstr = token_string
            last_col = end_col
            last_lineno = end_line
        temp = []
        temp_dict = {}
        lineno = 1
        for x in out.split('\n'):
            if x.strip() != "":
                temp.append(x)
                temp_dict[lineno] = x
                lineno += 1
        return '\n'.join(temp), temp_dict
    elif lang in ['ruby']:
        return source
    else:
        def replacer(match):
            s = match.group(0)
            if s.startswith('/'):
                return " "  # note: a space and not an empty string
            else:
                return s

        pattern = re.compile(
            r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
            re.DOTALL | re.MULTILINE
        )
        temp = []
        temp_dict = {}
        lineno = 1
        for x in re.sub(pattern, replacer, source).split('\n'):
            if x.strip() != "":
                temp.append(x)
                temp_dict[lineno] = x
                lineno += 1
        return '\n'.join(temp), temp_dict


def extract_pathtoken(source, path_sequence):
    seqtoken_out = []
    for path in path_sequence:
        seq_code = ''
        for line in path:
            if line != 'exit' and (line in source):
                seq_code += source[line]
        seqtoken_out.append(seq_code)
        if len(seqtoken_out) > 5:
            break
    if len(path_sequence) == 0:
        seq_code = ''
        for i in source:
            seq_code += source[i]
        seqtoken_out.append(seq_code)
    seqtoken_out = sorted(seqtoken_out, key=lambda i: len(i), reverse=False)
    return seqtoken_out


# 如果被测试代码中不包含分支语句，该怎么办
def extract_constraints(source, path_sequence, constraint_dict):
    constraints = []
    for path in path_sequence:
        seq_constraint = ''
        for idx, line in enumerate(path):
            if line != 'exit' and (line in source):
                code_line = source[line]
                if code_line in constraint_dict:
                    if idx < len(path):
                        next_node = path[idx + 1]
                    else:
                        next_node = path[-1]
                    if next_node - line == 1:
                        constraint = code_line.strip() + '\n'
                        seq_constraint += constraint
                    else:
                        constraint = 'not ' + code_line.strip() + '\n'
                        seq_constraint += constraint
        if len(seq_constraint) == 0:
            print("The extracted constraints is None!!!")
        constraints.append(seq_constraint)
        if len(constraints) == 0:
            print("The selected constraints is None!!!")
    if len(path_sequence) == 0:
        print("The selected path is None!!!")
    return constraints


# ==============================================================================
# other func
# ==============================================================================

def eliminate_func(func_content: str) -> str:
    """
    为Java函数添加多行注释
    参数:
        func_content (str): 未经注释的Java函数字符串
    返回:
        str: 被/*...*/包裹的带注释函数字符串或者逐行注释
    """
    # 处理可能存在的嵌套注释风险
    if '*/' in func_content:
        # 将每行内容前添加 "\\"
        lines = func_content.split('\n')
        commented_content = "\n".join([f"//{line}" for line in lines])
        return f"{commented_content}"
    else:
        # 直接包裹为多行注释
        return f"/*\n{func_content}\n*/"


def ends_with_any(suffix: str, str_list: list[str]) -> str:
    str_result = ""
    for string in str_list:
        if string.endswith(suffix):
            str_result = string
            break
    return str_result


def remove_last_segment(full_name: str) -> str:
    """高效移除最后一个点（.）后的内容
    Args:
        full_name: 如 "com.baomidou.mybatisplus.annotation.TableName"
    Returns:
        移除末尾段后的字符串，如 "com.baomidou.mybatisplus.annotation"
    """
    return full_name.rsplit('.', 1)[0]  # 从右侧分割1次后取第一部分


def create_directory(path: str, verbose=False):
    """
    在指定路径创建文件夹（支持多级目录），若已存在则跳过
    参数:
        path (str): 目标文件夹路径
        verbose (bool): 是否打印操作日志（默认True）
    返回:
        bool: True表示创建成功，False表示文件夹已存在
    """
    try:
        # 检查路径是否已存在
        if os.path.exists(path) and os.path.isdir(path):
            if verbose:
                print(f"目录已存在: {path}")
            return False

        # 创建目录（自动处理多级目录）
        os.makedirs(path, exist_ok=True)

        # 验证创建结果
        if os.path.exists(path):
            if verbose:
                print(f"目录创建成功: {path}")
            return True
        else:
            raise RuntimeError(f"未知错误: 目录创建失败")

    except PermissionError as e:
        if verbose:
            print(f"权限不足: 无法在 {path} 创建目录（需要管理员权限）")
        raise
    except OSError as e:
        if verbose:
            print(f"系统错误: {str(e)}")
        raise
    except Exception as e:
        if verbose:
            print(f"未知错误: {str(e)}")
        raise

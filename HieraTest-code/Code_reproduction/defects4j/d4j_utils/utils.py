import re
from enum import unique, Enum, auto

from tree_sitter import Node

from generate.formalizer import integrate_error_list
from utils.parse_utils import find_nodes_by_type, TreeSitterJava, extract_method_signature


@unique
class Baseline(Enum):
    # 定义 __new__ 方法来处理枚举值的创建
    def __new__(cls, value, has_compile):
        # 创建枚举成员
        member = object.__new__(cls)
        member._value_ = value
        # 添加自定义属性
        member.has_compile = has_compile
        return member

    def __str__(self):
        return self.name

    BugWhisper = auto(), True
    ChatUnitTest = auto(), True
    Hits = auto(), True
    TestBench = auto(), False
    ChatTester = auto(), True



test_skeleton = \
    """
    package tmp.a.b.c;
    import java.util.List;
    import junit.framework.TestCase;
    import static org.junit.Assert.*;
    public class TestClass extends TestCase{
    """

def handle_compile_error_list(error_list:list)->str:
    compile_error = ""
    if error_list:
        error_tmp = error_list[0]
        if isinstance(error_tmp,str):
            compile_error = "\n".join(error_list)
        elif isinstance(error_tmp,dict):
            compile_error = integrate_error_list(error_list=error_list)
    return compile_error

def find_method_list_signature(node: Node, fm_method_signature: str) -> list:
    other_method_signature_list = []
    method_declaration_node_list = find_nodes_by_type(node=node, target_type=TreeSitterJava.method_declaration)
    for method_declaration_node in method_declaration_node_list:
        method_signature = extract_method_signature(node=method_declaration_node)
        if method_signature != fm_method_signature:
            other_method_signature_list.append(method_signature)
    return other_method_signature_list


def extract_coverage_info(coverage_str: str) -> dict:
    # 定义一个包含所有预期标签的列表
    expected_labels = [
        "Lines total",
        "Lines covered",
        "Conditions total",
        "Conditions covered",
        "Line coverage",
        "Condition coverage"
    ]

    # 构建最终的、更精确且精简的正则表达式
    # 核心思路：
    # 1. 使用 `|` 连接所有预期的标签，并将其放在第一个捕获组中。
    # 2. 使用 `re.escape()` 确保标签中的特殊字符被正确处理。
    # 3. 匹配冒号和周围的空格 (`\s*:\s*`)。
    # 4. 匹配值的模式 (`\d+\.?\d*%?`)，并将其放在第二个捕获组中。
    # 5. 使用 `^`, `$`, 和 `re.MULTILINE` 来匹配整行。

    # 构建包含所有标签的 OR 模式
    # re.escape(label) 确保标签中的特殊字符（如 . * + ? 等）被当作字面值匹配
    label_part = "|".join(re.escape(label) for label in expected_labels)

    # 最终的正则表达式模式
    # ^\s*             : 行的开始，后跟可选的空白字符（处理缩进）
    # (label_part)     : 第一个捕获组，匹配预期的标签之一
    # \s*:\s*          : 冒号，前后有可选的空白字符
    # (\d+\.?\d*%?)    : 第二个捕获组，匹配数字，可选的小数点，数字，可选的百分号
    # \s*$             : 行的结束，后跟可选的空白字符
    regex_pattern = rf"^\s*({label_part})\s*:\s*(\d+\.?\d*%?)\s*$"

    # 编译正则表达式，提高效率
    regex = re.compile(regex_pattern, re.MULTILINE)

    extracted_data = {}

    # 查找所有匹配项
    for match in regex.finditer(coverage_str):
        # match.group(1) 是捕获到的标签
        label = match.group(1)
        # match.group(2) 是捕获到的值
        value = match.group(2)

        # 将提取到的数据存入字典
        if label and value:  # 确保标签和值都成功捕获
            extracted_data[label] = value.strip()  # .strip() 移除值前后可能存在的空白

    # # 打印提取的数据
    # for label, value in extracted_data.items():
    #     print(f"{label}: {value}")
    return extracted_data


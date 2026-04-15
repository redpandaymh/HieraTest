import concurrent
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional, Callable, Protocol

from tqdm import tqdm
from tree_sitter import Node

from config.logging_config import setup_logging

logger = setup_logging(log_prefix="method_analysis", app_logger_name="method_analysis.py")

from utils.utils import selected_keys_class, selected_keys_method, MethodAttr, FieldAttr, ClassAttr, \
    EnumAttr, InterfaceAttr, EnumConstantAttr, find_java_files, get_tree_root, init_parser, ends_with_any, \
    remove_last_segment, ordered_dedup, create_directory, remove_comments_and_docstrings
from utils.parse_utils import (find_node_by_type, find_nodes_by_type, get_node_text, find_node_in_children,
                               extract_java_package_name, TreeSitterJava, extract_method_nodes,
                               extract_method_name_node, extract_import_str_list, generate_import_stmt,
                               generate_package_stmt, edit_str_in_byte, find_nodes_in_children)
from locate.bug_locator import locate
from generate.path_selection import path_selection, simple_path_selection
from generate.generator import generate_unit_test
from generate.generate_test_file import generate_test_file
from generate.formalizer import formatter, formatter_one_for_one
from config.configs import model, env, EnvConfig, DEEP_DEPENDENCY_MODE, ONE_CLASS_FOR_ONE_FOCAL_METHOD, ADD_TEST, \
    GENERATION_SKIP

possibleDependencyBasicType = [TreeSitterJava.type_identifier]
possibleDependencyType = possibleDependencyBasicType + [TreeSitterJava.array_type, TreeSitterJava.generic_type,
                                                        TreeSitterJava.annotated_type,
                                                        TreeSitterJava.scoped_type_identifier]
basicEncapsulation = ["Boolean", "Byte", "Short",
                      "Integer", "Long", "Float", "Double", "Character"]


class Position:
    first = 1
    second = 2


class JavaTestGenerator:
    def __init__(self):
        # 匿去
        print()

    def file_analysis(self, file_path: str) -> Tuple[int, int, dict]:
        """
        :param file_path: 文件地址
        :return:生成单元测试类的数量、函数的数量以及具体的单元测函数的字典
        """
        # 两个重要的变量声明
        generated_func_cnt = 0
        generated_class_cnt = 0

        generated_func_table_wrap = {}
        # 处理环境问题

        symbol_table = self.repo_table

        with open(file_path, "r", encoding="utf-8") as file:
            source_code = file.read()

        root_node = get_tree_root(content=source_code)
        if not root_node:
            return 0, 0, {}

        package_name = extract_java_package_name(root_node=root_node)
        import_list: list[str] = extract_import_str_list(node=root_node)

        generated_result = {}
        generated_func_cnt += self.class_analysis(root_node=root_node, parent_fqdn=package_name,
                                                  import_list=import_list,
                                                  symbol_table=symbol_table, package_name=package_name,
                                                  generated_result=generated_result,
                                                  generated_func_table_wrap=generated_func_table_wrap)

        if not generated_result:
            return 0, 0, {}

        for k, v in generated_result.items():
            # 对于每一个类，去项目对应的地方创建空的java文件（如果之前不存在的话）
            if ONE_CLASS_FOR_ONE_FOCAL_METHOD:
                class_name = extract_identifier_from_fqdn(k, Position.second)
                method_name = extract_identifier_from_fqdn(k, Position.first)
                cls_name = "_".join([class_name, method_name])
                print()
            else:
                cls_name = extract_identifier_from_fqdn(k, Position.first)
            is_ok, test_path = generate_test_file(
                file_path=file_path, class_name=cls_name)
            try:
                with open(test_path, 'w', encoding='utf-8') as file:
                    file.write(v)
                    generated_class_cnt += 1
            except IOError as e:
                logging.error(f"文件操作失败，未能将单元测试写入文件: {e}", exc_info=True)

        return generated_class_cnt, generated_func_cnt, generated_func_table_wrap


    def test_generator(self):
        """
        单元测试生成任务的入口，负责挑选出指定的java文件，然后以文件为基本单位进行任务的分发，
        借由method_analysis来实现具体的单元测试文件的生成
        :return:
        """
        # 需要进行存储的字典
        generated_func_table_wrap = {}

        project_name = self.project_name

        files = find_java_files(path=self.project_path, exact_match=True, include_dirs=self.include_dirs)
        logger.info(f"共发现{len(files)}个java文件")

        start = time.time()
        generated_func_cnt: int = 0
        generated_class_cnt: int = 0

        with ThreadPoolExecutor(max_workers=16) as executor:
            # 使用列表推导式提交所有任务
            futures = [executor.submit(
                self.file_analysis,
                file_path=file,
            ) for file in files]

            # 使用tqdm包装as_completed实现动态进度条
            for future in tqdm(concurrent.futures.as_completed(futures),
                               total=len(files),
                               desc="Analyzing Java files",
                               unit="file"):
                class_cnt, func_cnt, func_dict = future.result()
                generated_func_table_wrap.update(func_dict)
                generated_func_cnt += func_cnt
                generated_class_cnt += class_cnt

        end = time.time()
        # 日志记录部分保持原样
        generate_log = {"generated_class_cnt": generated_class_cnt, "generated_func_cnt": generated_func_cnt,
                        "time_consumed": end - start}

        # 使用 os.path 标准化路径
        target_dir = os.path.normpath(self.generate_log_store_path)
        file_path = os.path.join(
            target_dir, f"{project_name}_{env.value}_{model}_generate_log.json")

        # 创建目录（若不存在）
        create_directory(path=target_dir)

        with open(
                file_path,
                "w",
                encoding="utf-8") as f:
            json.dump(generate_log, f, indent=4)  # indent 为缩进，使文件可读

        # 使用 os.path 标准化路径
        target_dir = os.path.normpath(self.fix_dependency_table_dir_path)
        file_path = os.path.join(
            target_dir, f"{project_name}_{env.value}_{model}_methods.json")

        # 创建目录（若不存在）
        os.makedirs(target_dir, exist_ok=True)  # exist_ok=True 避免重复创建异常

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(generated_func_table_wrap, f, indent=4)  # indent 为缩进，使文件可读


# ==============================================================================
# 其他函数
# ==============================================================================

def get_func_cnt(class_content: str) -> int:
    """
    统计单元测试函数的数量
    :param class_content: 单元测试的类的字符串
    :return: 统计出来的包含@Test注解符的单元测试的数量
    """
    cnt = 0
    root = get_tree_root(content=class_content)
    method_node_list = find_nodes_by_type(node=root, target_type=TreeSitterJava.method_declaration)
    for method_node in method_node_list:
        if modifiers_node := find_node_in_children(node=method_node, target_type=TreeSitterJava.modifiers):
            modifiers_str = get_node_text(node=modifiers_node)
            if "@Test" in modifiers_str or "@ParameterizedTest" in modifiers_str:
                cnt += 1
    return cnt


def get_nested_parent_fqdn(fqdn: str, import_list: list[str]) -> list[str]:
    fqdn_list: list[str] = [fqdn]
    fqdn_tmp = fqdn
    while "." in fqdn_tmp:
        fqdn_tmp = remove_last_segment(fqdn_tmp)
        if fqdn_tmp in import_list:
            fqdn_list.append(fqdn_tmp)
    return fqdn_list


def extract_function_name_from_signature(signature: str) -> str:
    """
    从函数签名中获取函数名
    :param signature:完整的函数签名
    :return: 截断后的函数名称
    """
    # 使用 '(' 分割字符串，取第一部分
    return signature.split('(')[0]


def get_method_return_type(symbol_table: dict, fqdn: str, method_name: str) -> str:
    """
    从给定的符号表中，根据fqdn和method_name来获取函数的返回值
    考虑到只凭借函数名称，会存在函数重载的问题，所以只返回第一个找到的函数的类型
    :param symbol_table:
    :param fqdn:
    :param method_name:
    :return:
    """
    current_symbol_table = symbol_table.get(fqdn, {})
    method_dict: dict = current_symbol_table.get("methods", {})
    matched_method_list = [v for k, v in method_dict.items() if k.startswith(method_name + "(")]
    if len(matched_method_list) == 0:
        return ""
    else:
        return matched_method_list[0].get("return_type", "")


def get_fqdn_from_class_name(import_list: list[str], class_name: str) -> str:
    """
    按照类名从import信息中获取fqdn
    :param import_list:
    :param class_name:
    :return:
    """
    fqdn: str = ""
    if not class_name:
        return fqdn
    for import_item in import_list:
        if import_item.endswith(class_name):
            fqdn = import_item
            break
    return fqdn




def get_generated_func_table(methods_info: dict, class_content: str) -> dict:
    """
    整合生成的单元测试与其所依赖的信息，方便在修复的时候也能得到相关信息，提升修复效果
    :param class_content:
    :param methods_info:
    :return:
    """
    generated_func_info = {}
    parser = init_parser()
    method_name_list: list = []
    simple_context = get_simple_context(file_context=class_content)
    for k, v in methods_info.items():
        method_dict = {"fm_name": v.get("fm_name", ""),
                       "trigger_fm": v.get("trigger_fm", ""),
                       "generated_test": [],
                       "simple_context": simple_context,
                       "dependency_info_str": v.get("dependency_info_str", "")}
        generated_test = v.get("generated_test", [])
        for idx, item in enumerate(generated_test):
            tree = parser.parse(bytes(item, "utf-8"))
            # source_bytes = bytearray(item.encode('utf-8'))
            test_func = item
            root_node = tree.root_node
            method_node_list = extract_method_nodes(root_node=root_node)
            # 根据在原始字符串中的位置进行降序排序，方便直接进行字符串的修改
            method_node_list = sorted(
                method_node_list, key=lambda s: s.start_byte, reverse=True)
            for method_node in method_node_list:
                # method_name = extract_method_name(root_node=method_node)
                method_name_node = extract_method_name_node(root_node=method_node)
                method_name = get_node_text(method_name_node) if method_name_node else ""
                if method_name and method_name in method_name_list:
                    method_name = f"{method_name}_{uuid.uuid4().hex[:8]}"
                    test_func = edit_str_in_byte(new_str=method_name, start_byte=method_name_node.start_byte,
                                                 end_byte=method_name_node.end_byte, source_str=item)
                if method_name and method_name not in method_dict.get("generated_test", {}):
                    method_dict["generated_test"].append(method_name)
                method_name_list.append(method_name)
            generated_test[idx] = test_func
        generated_func_info[method_dict.get("fm_name", "")] = method_dict

    return generated_func_info


# ==============================================================================
# 解析辅助函数
# ==============================================================================


def get_simple_context(file_context: str) -> str:
    root = get_tree_root(content=file_context)

    fields = []
    simple_method = []
    simple_context_list = []
    simple_context = ""

    # --- 1. 解析包声明 ---
    if package_declaration_node := find_node_by_type(node=root, target_type=TreeSitterJava.package_declaration):
        simple_context_list.append(get_node_text(package_declaration_node))

    # --- 2. 解析导入声明 ---
    if import_declaration_node_list := find_nodes_by_type(node=root,
                                                          target_type=TreeSitterJava.import_declaration):
        for import_declaration_node in import_declaration_node_list:
            simple_context_list.append(get_node_text(import_declaration_node))

    # --- 3. 解析顶级类声明 ---
    if class_declaration_node := find_node_in_children(node=root, target_type=TreeSitterJava.class_declaration):
        class_component_list = []
        # 提取类声明的其他部分 (修饰符, class 关键字, 类名)
        for class_component in class_declaration_node.children:
            if class_component.type not in [TreeSitterJava.class_body]:
                class_component_list.append(get_node_text(class_component))

        # 解析类体内的字段、方法、构造函数和嵌套类
        if class_body_node := find_node_in_children(node=class_declaration_node,
                                                    target_type=TreeSitterJava.class_body):
            for member_node in class_body_node.children:
                if member_node.type == TreeSitterJava.field_declaration:
                    fields.append(get_node_text(member_node))
                elif member_node.type == TreeSitterJava.method_declaration:
                    simple_list = []
                    # 提取方法签名（不包含方法体）
                    for component in member_node.children:
                        if component.type != TreeSitterJava.block:
                            simple_list.append(get_node_text(component))
                    func_signature = " ".join(simple_list)
                    simple_method.append(func_signature + ";")
                elif member_node.type == TreeSitterJava.constructor_declaration:
                    # 直接添加构造函数声明
                    simple_method.append(get_node_text(member_node))
                elif member_node.type in [TreeSitterJava.class_declaration, TreeSitterJava.enum_declaration]:
                    # 递归解析嵌套类
                    simple_context_class = get_simple_context(get_node_text(member_node))
                    simple_method.append(simple_context_class)
                # 可以在这里添加对 interface_declaration, enum_declaration 的递归处理

            class_component_list.extend(["{\n", "\n".join(fields), "\n", "\n".join(simple_method), "\n}"])
            class_str = " ".join(class_component_list)
            simple_context_list.append(class_str)

    # --- 4. 解析顶级枚举声明 ---
    # !!! 新增的枚举类解析部分 !!!
    if enum_declaration_node := find_node_in_children(node=root, target_type=TreeSitterJava.enum_declaration):
        enum_component_list = []
        # 提取枚举声明的其他部分 (修饰符, enum 关键字, 枚举名)
        for enum_component in enum_declaration_node.children:
            if enum_component.type not in [TreeSitterJava.enum_body]:
                enum_component_list.append(get_node_text(enum_component))

        # 解析枚举体内的枚举常量、方法和嵌套类
        if enum_body_node := find_node_in_children(node=enum_declaration_node,
                                                   target_type=TreeSitterJava.enum_body):
            enum_constants = []
            enum_methods_and_nested = []

            for member_node in enum_body_node.children:
                if member_node.type == TreeSitterJava.enum_constant:
                    # 枚举常量
                    enum_constants.append(get_node_text(member_node))
                elif member_node.type == TreeSitterJava.method_declaration:
                    # 枚举方法，与类方法类似解析
                    simple_list = []
                    for component in member_node.children:
                        if component.type != TreeSitterJava.block:
                            simple_list.append(get_node_text(component))
                    func_signature = " ".join(simple_list)
                    enum_methods_and_nested.append(func_signature + ";")
                elif member_node.type == TreeSitterJava.constructor_declaration:
                    # 枚举常量实现的匿名类构造函数
                    enum_methods_and_nested.append(get_node_text(member_node))
                elif member_node.type == TreeSitterJava.field_declaration:
                    # 枚举常量实现的匿名类的字段
                    enum_methods_and_nested.append(get_node_text(member_node))
                elif member_node.type == TreeSitterJava.class_declaration:
                    # 递归解析枚举实现的匿名类
                    simple_context_class = get_simple_context(get_node_text(member_node))
                    enum_methods_and_nested.append(simple_context_class)
                # 可以在这里添加对 interface_declaration, enum_declaration 的递归处理

            # 构建枚举的文本表示
            enum_declaration_str_parts = enum_component_list
            enum_declaration_str_parts.append("{\n")
            if enum_constants:
                enum_declaration_str_parts.append(",\n".join(enum_constants))  # 枚举常量用逗号分隔
            if enum_methods_and_nested:
                enum_declaration_str_parts.append(";\n" + "\n".join(enum_methods_and_nested))  # 方法和嵌套类

            enum_declaration_str_parts.append("\n}")
            enum_str = " ".join(enum_declaration_str_parts)
            simple_context_list.append(enum_str)

    # --- 5. 组合所有解析结果 ---
    # 注意：这里将所有顶级声明（类、枚举）都添加到了 simple_context_list
    # 如果你的目标是只输出第一个找到的类或枚举，需要调整这里的逻辑
    # 当前的实现会输出所有找到的顶级声明
    simple_context = "\n".join(simple_context_list)

    # 如果有顶级文档注释（通常在文件开头），可以将其添加到最前面
    # 需要额外逻辑来查找顶级的 block_comment，这里沿用你原有的 find_node_in_children(node=root, target_type=TreeSitterJava.block_comment)
    if docstring_node := find_node_in_children(node=root, target_type=TreeSitterJava.block_comment):
        docstring = get_node_text(docstring_node)
        simple_context = docstring + "\n" + simple_context

    return simple_context


# ==============================================================================
# 拼接辅助函数
# ==============================================================================

def concat_constructor_func(method: dict) -> str:
    result = method.get("content")
    if result is None:
        result = concat_method(method=method)
    return "\n" + result + ";" + "\n"


# ==============================================================================
# 工具函数
# ==============================================================================


def extract_identifier_from_fqdn(s: str, pos: int) -> str:
    parts = s.split('.')
    if pos == Position.first:
        return parts[-1] if len(parts) > 1 else ""
    elif pos == Position.second:
        return parts[-2] if len(parts) > 1 else ""
    else:
        return ""


def extract_fqdn_from_import_stmt(import_stmt: str) -> str:
    lst = import_stmt.split(" ")
    fqdn = lst[-1] if len(lst) > 0 else " "
    if fqdn.endswith(";"):
        fqdn = fqdn[:-1]
    return fqdn


def filter_dict(dic: Dict[str, Any], attr: List) -> Dict:
    """
        给定字典和需要过滤的属性，返回过滤后的字典
        仅处理单层字典的过滤
    :param dic:
    :param attr:
    :return:
    """

    return {k: dic[k] for k in attr if k in dic}


# ==============================================================================
# Main
# ==============================================================================

def main_wrapper():
    generator = JavaTestGenerator()
    generator.test_generator()


if __name__ == "__main__":
    main_wrapper()

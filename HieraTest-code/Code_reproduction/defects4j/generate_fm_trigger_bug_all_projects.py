import concurrent
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from glob import glob

import pandas as pd
from tqdm import tqdm
from tree_sitter import Node

from utils.parse_utils import find_node_by_type, TreeSitterJava, find_nodes_in_children, get_node_scope, get_node_text, \
    extract_method_name
from utils.utils import get_tree_root


# defects4j项目检出的临时目录
checkout_dir = 'xxx'
# defects4j项目所在的位置(用于提取项目相关bug信息)
d4j_path = "xxx"
# defects4j可执行文件地址
d4j_exe_path = "xxx"


def get_paths(java_file):
    contexts = []
    with open(java_file) as f:
        for line in f:
            line = line.strip()
            contexts += [line]
    return contexts


def read_txt(file_path):
    with open(file_path) as f:
        content = f.read()
    return content


def get_active_bugs(d4j_project_dir):
    active_bugs_df = pd.read_csv(d4j_project_dir + '/active-bugs.csv', index_col=0)
    bug_scm_hashes = active_bugs_df[['revision.id.buggy', 'revision.id.fixed']].to_dict()
    return active_bugs_df.index.to_list(), bug_scm_hashes


def get_project_layout(d4j_project_dir):
    project_layout_df = pd.read_csv(d4j_project_dir + '/dir-layout.csv', index_col=0,
                                    names=['src_dir', 'test_dir'])
    return project_layout_df.to_dict()


def dfs_visit(node, methods_list):
    # 检查当前节点是否为'method'类型
    if node.type == 'method_declaration':
        method_str = node.text.decode('utf-8')
        methods_list.append(method_str)  # 如果没有'text'字段，则默认为空字符串
    # 遍历当前节点的所有子节点
    for child in node.children:  # 如果没有'children'字段，则默认为空列表
        dfs_visit(child, methods_list)


def traverse_ast(ast):
    methods_list = []
    dfs_visit(ast, methods_list)
    return methods_list


def get_class_content(file_name):
    with open(file_name) as f:
        fm_content = f.read()
    return fm_content


def process_file_to_dict(filename):
    # 读取文件内容
    result_dict = {}
    try:
        with open(filename, 'r') as file:
            file_content = file.read()
    except:
        return result_dict
    # 按@@划分字符串
    parts = file_content.split('@@')

    for part in parts:
        # 寻找class关键字和第一个{之间的字段
        class_index = part.find('class')
        brace_index = part.find('{', class_index)

        if class_index != -1 and brace_index != -1:
            key = part[class_index + len('class'):brace_index].strip()
            value_list = []

            # 对每个划分的字符串按行处理
            lines = part.split('\n')
            for line in lines:
                if line.startswith('-'):
                    # 处理以-开头的行
                    processed_line = line[1:].strip()  # 去除-字符和前后的空格
                    if len(processed_line) > 5:
                        value_list.append(processed_line)

            # 如果键不为空，添加到结果字典中
            if key:
                result_dict[key] = list(set(value_list))

    return result_dict


def process_file_to_list(filename: str):
    result_list = []
    try:
        with open(filename, 'r') as file:
            file_content = file.read()
    except:
        return result_list

    # 按@@划分字符串
    parts = file_content.split('@@')
    for part in parts:
        # 对每个划分的字符串按行处理
        lines = part.split('\n')
        for line in lines:
            if line.startswith('-'):
                processed_line = line[1:].strip()  # 去除-字符和前后的空格
                if len(processed_line) > 5:
                    result_list.append(processed_line)
    return result_list


def extract_hunk_markers(diff_string: str):
    """
    从 Git diff 字符串中提取所有 hunk 的目标文件标记（如 '+92,7'）。

    Args:
        diff_string: 包含 Git diff 内容的字符串。

    Returns:
        一个列表，其中包含所有找到的目标文件标记（例如 '+92,7'）。
        如果未找到任何 hunk，则返回空列表。
    """

    # 正则表达式来匹配 hunk 头部，例如 @@ -63,7 +63,7 @@
    # 我们需要捕获的是 '+' 后面的行号和行数
    hunk_header_pattern = re.compile(r'^@@ -\d+,\d+ \+(\d+),(\d+) @@')

    hunk_markers = []
    lines = diff_string.splitlines()

    for line in lines:
        hunk_match = hunk_header_pattern.match(line)
        if hunk_match:
            # 构造目标文件标记，例如 '92,7'
            marker = f"{hunk_match.group(1)}"
            hunk_markers.append(marker)

    return hunk_markers


# 这里需要修改执行命令的地址
def run_command(target_directory: str, command_to_run: list, task_env: dict):
    # 确保目标目录存在
    if not os.path.isdir(target_directory):
        os.makedirs(target_directory)

    try:
        # 使用 cwd 参数指定工作目录
        # shell=True 允许你执行包含 shell 特性的命令，如管道、重定向等
        # 但要注意安全风险，如果命令来自用户输入，应避免 shell=True
        # capture_output=True 捕获标准输出和标准错误
        # text=True (或 encoding='utf-8') 将输出解码为字符串
        result = subprocess.run(
            command_to_run,
            cwd="/xxx",
            shell=False,  # 如果命令是简单的字符串且包含 shell 特性，则需要 shell=True
            capture_output=True,
            text=True,
            env=task_env,
            check=True  # 如果命令返回非零退出码，则抛出 CalledProcessError
        )

        # 打印命令的标准输出
        print("命令执行成功！输出：")
        # print(result.stdout)

        # 如果有标准错误（即使命令成功，也可能打印警告等）
        # if result.stderr:
        #     print("命令执行的错误输出（如果有）：")
        #     print(result.stderr)

    except FileNotFoundError:
        print(f"错误：命令 '{command_to_run[0]}' 未找到。请确保它在 PATH 中。")
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败！退出码: {e.returncode}")
        print(f"标准输出: {e.stdout}")
        print(f"标准错误: {e.stderr}")
    except Exception as e:
        print(f"发生未知错误: {e}")


def extract_test_path(file_path: str) -> list[str]:
    """
    读取文件的每一行，从中提取类名

    参数:
        file_path (str): 文件路径

    返回:
        str: 提取的类名（如"org.jfree.chart.renderer.category.junit.AbstractCategoryItemRendererTests"）
        None: 当文件不存在或格式不匹配时返回None
    """
    test_path_list:list = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()  # 去除首尾空白
                # 使用正则表达式匹配类名格式
                pattern = r'^---\s+([\w\.]+(?:::\w+)?\.[A-Za-z][\w\.]*)::'
                match = re.search(pattern, line)

                if match:
                    # 提取完整的类名路径
                    full_path = match.group(1)
                    if full_path not in test_path_list:
                        test_path_list.append(full_path)

        return test_path_list

    except FileNotFoundError:
        print(f"错误：文件不存在 - {file_path}")
        return []
    except Exception as e:
        print(f"处理文件时出错: {e}")
        return []


# 定义一个函数来处理单个项目和bug的逻辑
def process_project_bug(project_dir: str, d4j_path: str, d4j_exe_path: str, checkout_dir: str, my_env: dict):
    """
    处理单个项目和bug的下载、分析和数据收集逻辑。

    Args:
        project_dir (str): 当前项目的目录。
        d4j_path (str): defects4j 的安装路径。
        d4j_exe_path (str): defects4j 可执行文件的路径。
        checkout_dir (str): Checkout 项目的根目录。
        my_env (dict): 需要传递给子进程的环境变量。

    Returns:
        list: 符合条件的触发方法数据。
    """
    all_data_trigger_bug_local = []


    project_id: str = os.path.basename(project_dir)
    modified_classes_dir = os.path.join(project_dir, "modified_classes")
    trigger_tests_dir = os.path.join(project_dir, "trigger_tests")

    active_bug_list, _ = get_active_bugs(project_dir)

    collected_buggy_method_list_local_thread:dict[str, list] = {}

    for active_bug in active_bug_list:
        bug_id: str = str(active_bug)
        output_dir = os.path.join(checkout_dir, f"{project_id}_{bug_id}_b")
        command_list: list = [d4j_exe_path,
                              "checkout",
                              "-p", project_id,
                              "-v", f"{bug_id}b",
                              "-w", output_dir]
        # 运行 checkout 命令
        run_command(target_directory=output_dir, command_to_run=command_list, task_env=my_env)

        # 记录test文件所在的地址
        # 这里需要注意的是，涉及到的test文件可能有多个，所以需要全部进行提取
        actual_test_path_list:list = extract_test_path(os.path.join(trigger_tests_dir, f"{bug_id}"))
        actual_test_path_list = [p.replace(".", os.sep) for p in actual_test_path_list]


        src_path = os.path.join(modified_classes_dir, bug_id + ".src")
        focal_method_paths = get_paths(src_path)
        project_layout = get_project_layout(project_dir)
        _, bug_scm_hashes = get_active_bugs(project_dir)
        bug_hash = bug_scm_hashes['revision.id.buggy'].get(int(bug_id), "")
        if not bug_hash:
            continue
        src_dir = project_layout['src_dir'].get(bug_hash, "")
        test_dir = project_layout['test_dir'].get(bug_hash, "")
        actual_test_path_list = [os.path.join(test_dir, p) for p in actual_test_path_list]
        actual_test_path_list = [
            p if p.endswith(".java") else p + ".java"  # 表达式部分
            for p in actual_test_path_list  # 迭代部分
        ]

        if not src_dir or not test_dir:
            continue

        patches_dir = os.path.join(project_dir, "patches", f"{bug_id}.src.patch")
        git_diff_content = ""
        try:
            with open(patches_dir, 'r') as file:
                git_diff_content = file.read()
        except Exception as e:
            print(f"Error reading patch file {patches_dir}: {e}")
            continue
        modified_marker = extract_hunk_markers(git_diff_content)
        idx_local = 0

        for fm_path in focal_method_paths:

            p = fm_path.replace(".", "/")
            trigger_fm_dir = os.path.join(output_dir, src_dir, p + '.java')
            if os.path.exists(trigger_fm_dir):
                try:
                    class_name = os.path.basename(trigger_fm_dir).removesuffix('.java')
                    file_content = get_class_content(trigger_fm_dir)
                    root_node = get_tree_root(content=file_content)
                    class_body_node: Node = find_node_by_type(node=root_node, target_type=TreeSitterJava.class_body)
                    method_node_list = find_nodes_in_children(node=class_body_node,
                                                              target_type=TreeSitterJava.method_declaration)

                    for method_node in method_node_list:
                        node_scope = get_node_scope(node=method_node)
                        method_name: str = extract_method_name(root_node=method_node)

                        # 使用本地的收集记录来避免重复添加
                        if not collected_buggy_method_list_local_thread.get(class_name):
                            collected_buggy_method_list_local_thread[class_name] = []

                        if method_name in collected_buggy_method_list_local_thread[class_name]:
                            continue

                        # 检查方法范围是否在修改范围内
                        if any(node_scope[0] <= int(marker_line) <= node_scope[1] for marker_line in modified_marker):
                            idx_local += 1
                            item = dict()
                            print(f"success: {project_id}, {bug_id}")
                            item['bug_id'] = bug_id
                            item['func_idx'] = idx_local
                            item['project_id'] = project_id
                            item['src_fm'] = get_node_text(node=method_node)
                            item['trigger_fm_dir'] = trigger_fm_dir
                            item['modify_class'] = file_content
                            item['fm_name'] = method_name
                            item['test_dir'] = json.dumps(actual_test_path_list)
                            all_data_trigger_bug_local.append(item)
                            collected_buggy_method_list_local_thread[class_name].append(method_name)

                except Exception as e:
                    print(f"Error processing method in {trigger_fm_dir}: {e}")
                    continue

        # 删除产生的文件，以防止占用过多存储空间
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
    return all_data_trigger_bug_local


if __name__ == '__main__':

    # csv文件地址
    csv_path = "/xxx"
    df = pd.read_csv(csv_path, encoding="utf-8")  # 转换为字典列表（每行一个字典）
    data_list = df.to_dict(orient='records')

    all_data_trigger_bug = data_list
    idx = 0
    idx_fm_tb = 0
    method_id = 0

    # 获取并添加环境变量
    # 1. 复制当前环境
    my_env = os.environ.copy()

    # 2. 添加环境变量
    java_home_path = "xxx"
    my_env["JAVA_HOME"] = java_home_path
    my_env["PATH"] = f"{java_home_path}/bin:{my_env.get('PATH', '')}"  # 添加 JAVA_HOME/bin 到 PATH

    d4j_project_dir = os.path.join(d4j_path, "framework", "projects")
    # 构建搜索模式，例如 "/path/to/your/folder/*"
    search_pattern = os.path.join(d4j_project_dir, "*")

    folder_paths = [item for item in glob(search_pattern) if os.path.isdir(item)]

    # 过滤掉不需要处理的文件夹
    folder_paths = [p for p in folder_paths if os.path.basename(p) not in ["lib"]]


    # 使用 ThreadPoolExecutor 进行并发执行
    # max_workers 可以根据你的系统资源进行调整
    with ThreadPoolExecutor(max_workers=16) as executor:
        # 提交所有任务
        futures = [executor.submit(
            process_project_bug,
            project_dir=project_dir,
            d4j_path=d4j_path,
            d4j_exe_path=d4j_exe_path,
            checkout_dir=checkout_dir,
            my_env=my_env,
        ) for project_dir in folder_paths]

        # 使用tqdm包装as_completed实现动态进度条
        for future in tqdm(concurrent.futures.as_completed(futures),
                           total=len(folder_paths),
                           desc="Processing projects and bugs",
                           unit="project"):
            try:
                # 获取每个任务的结果（一个列表）并合并到主列表中
                result_list = future.result()
                all_data_trigger_bug.extend(result_list)
            except Exception as e:
                print(f"An error occurred during task execution: {e}")

    # 打印最终结果
    print(f"\nCollected {len(all_data_trigger_bug)} triggering method entries.")

    df = pd.DataFrame(all_data_trigger_bug)
    print(df.count())
    df.to_csv("trigger_bug_fm_all_projects_d4j.csv", index=False)
    print(idx, method_id)


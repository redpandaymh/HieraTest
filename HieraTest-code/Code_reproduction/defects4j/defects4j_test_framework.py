import concurrent
import copy
import json
import logging
import os
import re
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum

import pandas as pd
from tqdm import tqdm

from reappearance.defect4j.Hits_core import hits_generate
from reappearance.defect4j.bugWhisper_core import bugWhisper_generate
from reappearance.defect4j.chatTester_core import chatTester_generate
from reappearance.defect4j.chatUnitTest_core import chatUnitTest_generate
from reappearance.defect4j.d4j_utils.extract_compile_error import extract_compile_errors
from reappearance.defect4j.d4j_utils.formalizer_d4j import filtered_generated_file_d4j
from reappearance.defect4j.d4j_utils.utils import Baseline
from reappearance.defect4j.testBench_core import testBench_generate
from utils.parse_utils import extract_class_name, extract_java_package_name
from utils.utils import run_command, get_tree_root, get_test_base_path, \
    delete_java_files_in_dir, extract_defect4j_compile_error, extract_defect4j_test_error, ResultHandleMode

current_baseline = Baseline.BugWhisper

class ResultCode(IntEnum):
    # --- States indicating the origin or initial condition ---
    INITIAL_STATE = -3  # Represents the initial or default state before any processing.

    # --- Error codes indicating problems during the process ---
    SYNTAX_ERROR = -2  # Indicates a syntax error encountered during compilation or parsing.
    COMPILE_ERROR = -1 # Indicates a compilation error that prevented successful execution.

    # --- Codes indicating the outcome of bug detection ---
    FAIL_TO_DETECT_BUG = 0  # The bug detection process did not find any bugs.
    SUCCESS_TO_DETECT_BUG = 1 # The bug detection process successfully found bugs.
    ADVANCE_BUG_DETECTION = 2 # Indicates a more advanced or thorough bug detection mechanism was used
                              # and potentially found more complex bugs.

def defects4j_test(csv_file_path: str):
    # 项目检出的地址
    checkout_dir = 'xxx'
    # defects4j执行文件的地址
    d4j_exe_path = "xxx"
    # 存放结果日志的地址
    logging_dir_path = "xxx"
    fail_count: int = 0
    success_count: int = 0
    advance_count: int = 0
    compile_error_count:int = 0
    version = 'b'
    reverse_version = 'f' if version == 'b' else 'b'
    compare_dict: dict = {}

    df = pd.read_csv(csv_file_path, encoding="utf-8")  # 转换为字典列表（每行一个字典）
    data_list = df.to_dict(orient='records')

    # 2. 按 project_id 分组数据
    # 使用 defaultdict 可以简化分组逻辑
    grouped_tasks_by_project = defaultdict(list)
    project_order = []  # 存储 project_id 的出现顺序，以确保按原始顺序执行

    for data in data_list:
        project_id = data.get("project_id", "UnknownProject")

        if project_id not in project_order:
            project_order.append(project_id)
        grouped_tasks_by_project[project_id].append(
            (data, checkout_dir, d4j_exe_path, logging_dir_path, version, reverse_version, compare_dict)
        )
        # --- 结束过滤逻辑 ---

    # 确保 logging 目录存在
    os.makedirs(logging_dir_path, exist_ok=True)

    # 存储所有项目的总结果
    all_project_results = {}
    # 遍历 projects_order 来确保按顺序处理
    for project_id in project_order:
        tasks_for_current_project = grouped_tasks_by_project.get(project_id)

        if not tasks_for_current_project:
            print(f"No tasks found for project_id: {project_id}. Skipping.")
            continue

        print(f"\n--- Processing project: {project_id} ({len(tasks_for_current_project)} bugs) ---")

        # 为当前 project_id 创建一个线程池
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # 提交当前 project_id 的所有任务
            futures = [executor.submit(defects4j_test_thread, *args) for args in tasks_for_current_project]

            # 使用 tqdm 显示当前 project_id 的进度条
            project_results = []
            for future in tqdm(concurrent.futures.as_completed(futures),
                               total=len(futures),
                               desc=f"  Processing {project_id} bugs",
                               unit="bug",
                               leave=True):  # leave=True 保留当前 project 的进度条直到完成
                try:
                    result = future.result()
                    project_results.append(result)
                except Exception as exc:
                    # 捕获任务执行中的异常
                    # 尝试从 args 中获取 project_id 和 bug_id 来更好地记录错误
                    # 注意：这里 future.result() 抛出异常后，args 不直接可用，
                    # 需要更精细的设计来关联 future 和原始 args
                    # 简单起见，这里只记录 generic 错误信息
                    error_msg = f"Error processing a bug in {project_id}: {exc}"
                    print(f"\n{error_msg}")  # 使用 print 打印错误，不影响 tqdm
                    project_results.append(f"Error: {exc}")  # 也可以将错误信息记录到结果中

            all_project_results[project_id] = project_results


def defects4j_test_thread(data: dict, checkout_dir: str, d4j_exe_path: str,
                          logging_dir_path: str, version: str, reverse_version: str,
                          compare_dict: dict) -> int:

    # ======================================
    # 环境准备
    # ======================================
    # 1. 复制当前环境
    my_env: dict = os.environ.copy()

    # 2. 添加环境变量
    # java home的地址
    java_home_path = "xxx"
    my_env["JAVA_HOME"] = java_home_path
    # 添加 JAVA_HOME/bin 到 PATH
    my_env["PATH"] = f"{java_home_path}/bin:{my_env.get('PATH', '')}"

    # 项目属性
    project_id = data.get("project_id", "")
    bug_id = data.get("bug_id", "")
    func_idx = data.get("func_idx", "")

    # 准备日志文件夹及文件名称
    bug_detection_log_dir_path = os.path.join(logging_dir_path,"bug_detection_log",str(current_baseline),"experiment_test_log")
    if not os.path.exists(bug_detection_log_dir_path):
        os.makedirs(bug_detection_log_dir_path)
    logging_file_path = os.path.join(
        bug_detection_log_dir_path, f"{project_id}_{bug_id}_{func_idx}_{version}.txt")

    # 增加已存在则不再重复实验的设置
    if os.path.exists(logging_file_path):
        return 0

    # 设置 result_code
    # 返回-2代表存在语法错误，无法通过编译，
    # 返回-1代表不存在语法错误，但是无法通过编译
    # 返回0代表无区分，
    # 返回1代表有区分，
    # 返回2代表在buggy上失败但是在fix上成功

    # -3代表初始状态
    result_code = ResultCode.INITIAL_STATE

    # ======================================
    # 生成阶段
    # ======================================

    # 获取项目地址
    dir_name = f"{project_id}_{bug_id}_{func_idx}_{version}"
    # print("dir_name", dir_name)

    project_path = os.path.join(checkout_dir, dir_name)
    test_file_path_list: list[str] = json.loads(data['test_dir'])
    test_dir_pre = ""
    if test_file_path_list:
        test_file_path_tmp = test_file_path_list[0]
        while os.path.basename(test_file_path_tmp)!= "com" and os.path.basename(test_file_path_tmp)!= "org":
            test_file_path_tmp = os.path.dirname(test_file_path_tmp)
        test_file_path_tmp = os.path.dirname(test_file_path_tmp)
        test_dir_pre = test_file_path_tmp
    # 删除旧项目
    if os.path.exists(project_path):
        shutil.rmtree(project_path)

    command_list: list = [d4j_exe_path,
                          "checkout",
                          "-p", project_id,
                          "-v", f"{bug_id}{version}",
                          "-w", project_path]
    # 创建新的项目
    run_command(target_dir=project_path,
                command_list=command_list, task_env=my_env)

    # # 获取测试文件地址，如果不存在则可能影响后续的实验，所以直接跳过
    # # 拼接获取完整的文件地址
    # test_file_path_list = [os.path.join(
    #     project_path, p) for p in test_file_path_list]
    # if not test_file_path_list:
    #     return 0

    fm_method: str = data.get("src_fm", "")
    class_content: str = data.get("modify_class", "")
    fm_name: str = data.get("fm_name", "")

    # 获取类名称
    root_node = get_tree_root(content=class_content)
    class_name = extract_class_name(node=root_node)
    package_name = extract_java_package_name(root_node=root_node)
    package_path = package_name.replace(".",os.sep)

    # 使用不同的baseline进行实验
    if current_baseline == Baseline.BugWhisper:
        generated_class_content = bugWhisper_generate(class_content=class_content,
                                                      fm_name=fm_name,
                                                      fm_method=fm_method)
    elif current_baseline == Baseline.ChatUnitTest:
        generated_class_content = chatUnitTest_generate(class_content=class_content,
                                                        fm_name=fm_name,
                                                        fm_method=fm_method)
    elif current_baseline == Baseline.Hits:
        generated_class_content = hits_generate(class_content=class_content,
                                                fm_name=fm_name,
                                                fm_method=fm_method)
    elif current_baseline == Baseline.TestBench:
        generated_class_content = testBench_generate(class_content=class_content,
                                                     fm_name=fm_name,
                                                     fm_method=fm_method)
    elif current_baseline == Baseline.ChatTester:
        generated_class_content = chatTester_generate(class_content=class_content,
                                                      fm_name=fm_name,
                                                      fm_method=fm_method)
    else:
        generated_class_content = ""

    # 将新的文件创建并放到指定的地点
    new_class_name = "_".join([class_name, fm_name])
    # test_file_path_tmp = test_file_path_list[0]
    test_path = os.path.join(project_path, test_dir_pre, package_path, f"{new_class_name}Test.java")
    # _, test_path = generate_test_file(
    #     file_path=test_file_path_tmp, class_name=new_class_name)
    # 采用删除所有其他的单元测试文件以防止编译时的干扰
    # test_base_dir = get_test_base_path(full_path=test_file_path_tmp)
    test_base_dir = get_test_base_path(full_path=test_path)
    delete_java_files_in_dir(directory=test_base_dir)
    # # 成功生成单元测试类之后，需要前往对应的地址，将原有的单元测试文件进行删除
    # for test_file_path in test_file_path_list:
    #     if os.path.exists(test_file_path) and os.path.isfile(test_file_path):
    #         os.remove(test_file_path)
    test_file_base_dir = os.path.dirname(test_path)
    if not os.path.exists(test_file_base_dir):
        os.mkdir(test_file_base_dir)

    try:
        with open(test_path, 'w', encoding='utf-8') as file:
            file.write(generated_class_content)
    except IOError as e:
        logging.error(f"文件操作失败，未能将单元测试写入文件: {e}", exc_info=True)

    # ======================================
    # 修复阶段
    # ======================================
    # 如果指定的baseline存在修复阶段:
    if current_baseline.has_compile:
        max_fix_time: int = 5
        cnt: int = 0
        compile_success = False
        while cnt <= max_fix_time:
            command_list: list = [d4j_exe_path, "compile"]
            result = run_command(target_dir=project_path,
                                 command_list=command_list, task_env=my_env)
            compile_error: str = result.get("error", "")
            compile_error_list = extract_compile_errors(compile_log=compile_error)
            compile_error_list_tmp = copy.deepcopy(compile_error_list)
            compile_error_list = ["\n".join([item.get("File", ""), item.get("Line", ""), item.get("Description", "")])
                                  for item in compile_error_list]
            if not compile_error_list:
                compile_success = True
                break

            if cnt == max_fix_time:
                n: int = 0
                while n < 5:
                    command_list: list = [d4j_exe_path, "compile"]
                    result = run_command(target_dir=project_path,
                                         command_list=command_list, task_env=my_env)
                    compile_error: str = result.get("error", "")
                    error_list = extract_compile_errors(compile_log=compile_error)
                    if not error_list:
                        compile_success = True
                        break
                    filtered_result = filtered_generated_file_d4j(generated_content=generated_class_content,
                                                                  fm_method=fm_method,
                                                                  error_list=error_list,
                                                                  origin_class_content=class_content,
                                                                  handle_mode=ResultHandleMode.eliminate_mode,
                                                                  current_baseline=current_baseline
                                                                  )
                    # filtered_result = filter_method(file_content=generated_class_content, error_list=error_list)
                    with open(test_path, 'w', encoding='utf-8') as file:
                        file.write(filtered_result)
                    generated_class_content = filtered_result

                    n += 1
                break

            fixed_result = filtered_generated_file_d4j(generated_content=generated_class_content,
                                                       fm_method=fm_method,
                                                       error_list=compile_error_list_tmp,
                                                       origin_class_content=class_content,
                                                       handle_mode=ResultHandleMode.fix_mode,
                                                       current_baseline=current_baseline
                                                       )


            try:
                with open(test_path, 'w', encoding='utf-8') as file:
                    file.write(fixed_result)
            except IOError as e:
                logging.error(f"文件操作失败，未能将单元测试写入文件: {e}", exc_info=True)
            generated_class_content = fixed_result
            cnt += 1

        # 代表修复失败，无法进行test实验对比，此时判断是否存在语法错误
        root = get_tree_root(content=generated_class_content)
        has_error = root.has_error
        if not compile_success:
            if has_error:
                result_code = ResultCode.SYNTAX_ERROR
            else:
                result_code = ResultCode.COMPILE_ERROR
    # 所指定baseline没有修复的过程，则直接进行编译，如果通过则进入对比，没通过则直接返回失败
    else:
        command_list: list = [d4j_exe_path, "compile"]
        result = run_command(target_dir=project_path,
                             command_list=command_list, task_env=my_env)
        compile_error: str = result.get("error", "")
        compile_error_list = extract_compile_errors(compile_log=compile_error)
        build_failure = "BUILD FAILED" in compile_error

        root = get_tree_root(content=generated_class_content)
        has_error = root.has_error
        if compile_error_list or build_failure:
            if has_error:
                result_code = ResultCode.SYNTAX_ERROR
            else:
                result_code = ResultCode.COMPILE_ERROR

    # 如果result_code 不为-3，说明已经无法继续进行接下来的操作
    if result_code != ResultCode.INITIAL_STATE:
        if os.path.exists(project_path):
            shutil.rmtree(project_path)
        logging_content = f"code:{result_code}\n"+\
                          "generated_content:\n" + generated_class_content
        try:
            with open(logging_file_path, 'w', encoding='utf-8') as file:
                file.write(logging_content)
        except IOError as e:
            logging.error(f"写入测试日志失败: {e}", exc_info=True)

        return result_code

    # 代表在指定的修复次数限制下修复成功，那么接下来需要在两个版本上进行test验证，以对比生成的单元测试究竟是否有检测bug的效果
    # ======================================
    # 对比阶段
    # ======================================

    # 首先检测是否存在fix版本的checkout
    # 如果存在就删除旧版本，以避免旧文件的影响
    dir_name_reverse = f"{project_id}_{bug_id}_{func_idx}_{reverse_version}"
    another_version_project_path = os.path.join(
        checkout_dir, dir_name_reverse)

    if os.path.exists(another_version_project_path):
        shutil.rmtree(another_version_project_path)
    command_list: list = [d4j_exe_path,
                          "checkout",
                          "-p", project_id,
                          "-v", f"{bug_id}{reverse_version}",
                          "-w", another_version_project_path]
    run_command(target_dir=another_version_project_path,
                command_list=command_list, task_env=my_env)
    another_version_test_path = os.path.join(another_version_project_path,test_dir_pre,package_path,f"{new_class_name}Test.java")
    # 删除可能影响测试的test文件
    # another_version_test_file_path_list = [
    #     p.replace(dir_name, f"{project_id}_{bug_id}_{func_idx}_{reverse_version}") for p
    #     in test_file_path_list]
    # 采用删除所有其他的单元测试文件以防止编译时的干扰
    # test_file_path_tmp = another_version_test_file_path_list[0]
    test_base_dir = get_test_base_path(full_path=another_version_test_path)
    delete_java_files_in_dir(directory=test_base_dir)
    # for file_path in another_version_test_file_path_list:
    #     if os.path.exists(file_path) and os.path.isfile(file_path):
    #         os.remove(file_path)
    # 写入修复好的文件
    another_version_test_path = another_version_test_path.replace(
        dir_name, f"{project_id}_{bug_id}_{func_idx}_{reverse_version}")

    test_file_base_dir = os.path.dirname(another_version_test_path)
    if not os.path.exists(test_file_base_dir):
        os.mkdir(test_file_base_dir)

    try:
        with open(another_version_test_path, 'w', encoding='utf-8') as file:
            file.write(generated_class_content)
    except IOError as e:
        logging.error(f"文件操作失败，未能将单元测试写入文件: {e}", exc_info=True)

    # 在两个版本中分别进行defects4j test，并记录运行结果
    buggy_project_path: str = another_version_project_path if another_version_project_path.endswith(
        "b") else project_path
    fix_project_path: str = another_version_project_path if another_version_project_path.endswith(
        "f") else project_path
    # buggy版本
    command_list: list = [d4j_exe_path,
                          "test"]
    result_b = run_command(
        target_dir=buggy_project_path, command_list=command_list, task_env=my_env)
    test_error_b = result_b.get("output", "")
    buggy_error_cnt = extract_defect4j_test_error(
        log_string=test_error_b)

    # fix 版本
    result_f = run_command(
        target_dir=fix_project_path, command_list=command_list, task_env=my_env)
    test_error_f = result_f.get("output", "")
    fix_error_cnt = extract_defect4j_test_error(
        log_string=test_error_f)
    # 进行对比
    is_useful_test: int = int(buggy_error_cnt != fix_error_cnt)
    compare_dict[f"{project_id}_{bug_id}_{func_idx}_{reverse_version}"] = {"fix_error_cnt": fix_error_cnt,
                                                                           "buggy_error_cnt": buggy_error_cnt,
                                                                           "is_useful_test": is_useful_test
                                                                           }
    # 更新result_code
    if buggy_error_cnt == fix_error_cnt:
        result_code = ResultCode.FAIL_TO_DETECT_BUG
    elif buggy_error_cnt > fix_error_cnt:
        result_code = ResultCode.ADVANCE_BUG_DETECTION
    else:
        result_code = ResultCode.SUCCESS_TO_DETECT_BUG

    # bug_detection_log_dir_path = os.path.join(logging_dir_path,"bug_detection_log",str(current_baseline),"experiment_test_log")
    # if not os.path.exists(bug_detection_log_dir_path):
    #     os.makedirs(bug_detection_log_dir_path)
    # logging_file_path = os.path.join(
    #     bug_detection_log_dir_path, f"{project_id}_{bug_id}_{func_idx}_{version}.txt")
    logging_content = f"code:{result_code}\n"+\
                      "buggy_version_test_error:\n" + test_error_b + "\n\n\n\n" + \
                      "fix_version_test_error:\n" + test_error_f + "\n\n\n\n" + \
                      "generated_content:\n" + generated_class_content
    try:
        with open(logging_file_path, 'w', encoding='utf-8') as file:
            file.write(logging_content)
    except IOError as e:
        logging.error(f"文件操作失败，未能将单元测试写入文件: {e}", exc_info=True)

    # 最后清除掉checkout的文件，以防止内存消耗过大
    if os.path.exists(buggy_project_path):
        shutil.rmtree(buggy_project_path)
    if os.path.exists(fix_project_path):
        shutil.rmtree(fix_project_path)

    return result_code


if __name__ == '__main__':
    # 使用csv来对defects4j上的实验集进行实验
    csv_path = "xxx"
    defects4j_test(csv_file_path=csv_path)
    print()

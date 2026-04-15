import concurrent
import os
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

import config.configs
from check.check_result import JavaTestFileChecker
from config.configs import EnvType
from generate.generate_test_file import create_test_file
from generate.method_analysis import extract_identifier_from_fqdn, Position
from reappearance.TestBench.content_repair import repair_error
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_java_package_name, find_nodes_by_type, TreeSitterJava, get_node_text, \
    find_node_in_children, find_node_by_type, find_nodes_in_children, extract_import_str_list
from utils.utils import get_tree_root, find_java_files, extract_java_code

generate_mode = "SourceCodeOnly"


def instruct_prompt_large_1(source_code: str, test_info: str) -> str:
    return f"""Below is an instruction that describes a task. Write a response that appropriately completes the request.
    \n\n### Instruction:\nWrite a unit test for the following Java Source Code with junit. 
    \nUnit test has been finished partially. Please complete the section contains <FILL> tag and output the whole test case.
    \n\n### JAVA Source Code:\n{source_code}
    \n\n### JUNIT Test case:\n{test_info}
    \n\n### Response:"""


def instruct_prompt_large_2(source_code: str, context: str, test_info: str) -> str:
    return f"""Below is an instruction that describes a task. Write a response that appropriately completes the request.
    \n\n### Instruction:\nWrite a unit test for the following Java Source Code with junit. the Context information is given.
    \nUnit test has been finished partially. Please complete the section contains <FILL> tag and output the whole test case.
    \n\n### JAVA Source Code:\n{source_code}
    \n\n### Context:\n{context}
    \n\n### JUNIT Test case:\n{test_info}
    \n\n### Response:"""


def test_bench_generate(source_code: str, env: EnvType, model: str) -> dict:
    """
    生成单元测试框架和函数
    :return:
    """
    generate_map = {}
    package_name, class_name, data_list = get_context_info(file_context=source_code)

    for _, data in enumerate(data_list):
        # data_map = {}
        class_name = data.get("class_name")
        method_name = data.get("method_name")
        new_class_name = "_".join([class_name, method_name])
        test_info = test_case_info(data['package'], new_class_name, method_name)
        if generate_mode == "SourceCodeOnly":
            test_prompt = instruct_prompt_large_1(source_code=data.get("source_code"), test_info=test_info)
        elif generate_mode == "SourceCode&Full":
            test_prompt = instruct_prompt_large_2(source_code=data.get("source_code", ""), test_info=test_info,
                                                  context=data.get("full_context", ""))
        elif generate_mode == "SourceCode&Simple":
            test_prompt = instruct_prompt_large_2(source_code=data.get("source_code", ""), test_info=test_info,
                                                  context=data.get("simple_context", ""))
        # 不可能发生的情况
        else:
            test_prompt = ""
            raise ValueError("wrong mode")
        instructions = [{"role": "user", "content": test_prompt}]
        res = chat_client_openai(env=env, messages=instructions, model=model)
        res = extract_java_code(text=res)
        # data_map["generated_test"] = [res]
        # generate_map[method_name] = data_map
        generate_map[method_name] = res

    # final_result = formatter(methods_info=generate_map, test_frame=test_pre)
    return generate_map


def test_case_info(package_name, class_name, method_name="named_method_name"):
    """
    Generate test case information(for prompt).
    """
    test_info = "package " + package_name + ";\n\n"
    test_info += "import org.junit.jupiter.api.*;\n"
    test_info += "import static org.junit.jupiter.api.Assertions.*;\n\n"
    test_info += "public class " + class_name + "Test {\n"
    test_info += "    @Test\n"
    test_info += "    public void " + method_name + "Test() {\n"
    test_info += "        <FILL>\n"
    test_info += "    }\n"
    test_info += "}"
    return test_info


def test_case_info_without_test(package_name, class_name):
    """
    Generate test case information(for prompt).
    """
    test_info = "package " + package_name + ";\n\n"
    test_info += "import org.junit.jupiter.api.*;\n"
    test_info += "import static org.junit.jupiter.api.Assertions.*;\n\n"
    test_info += "public class " + class_name + "Test {\n"
    test_info += "}"
    return test_info


# def process_item(item, i, path, number):
#     """处理单个测试项的函数，用于并行执行"""
#     source_code = item['source_code']
#     full_context = item['full_context']
#     simple_context = item['simple_context']
#     test_info = test_case_info(item['package'], item['class_name'], item['method_name'])
#
#     sub_dirs = ['SourceCodeOnly', 'SourceCode&Full', 'SourceCode&Simple']
#     prompts = [
#         instruct_prompt_large_1(source_code, test_info),
#         instruct_prompt_large_2(source_code, full_context, test_info),
#         instruct_prompt_large_2(source_code, simple_context, test_info)
#     ]
#
#     for j in range(3):
#         third_dir = sub_dirs[j]
#         third_path = os.path.join(second_path, third_dir)
#         os.makedirs(third_path, exist_ok=True)
#
#         txt_file = os.path.join(third_path, "result.txt")
#         json_file = os.path.join(third_path, "result.json")
#
#         record = []
#         data = prompts[j]
#
#         with open(txt_file, 'w', encoding='utf-8') as file:
#             file.write("Source code: \n\n")
#             file.write(source_code + "\n\n\n")
#
#             # 并行生成测试用例
#             results = generate_test_cases(data, number)
#             for k, output in enumerate(results):
#                 file.write(f"No.{k + 1} generated result --------------------------\n\n")
#                 file.write(output + "\n\n\n")
#                 record.append(output)
#
#         # 保存JSON结果
#         with open(json_file, 'w', encoding='utf-8') as file:
#             record_data = {
#                 "project_name": item['project_name'],
#                 "file_name": item['file_name'],
#                 "relative_path": item['relative_path'],
#                 "execute_path": item['execute_path'],
#                 "package": item['package'],
#                 "docstring": item['docstring'],
#                 "source_code": source_code,
#                 "class_name": item['class_name'],
#                 "method_name": item['method_name'],
#                 "arguments": item['argument_name'],
#                 "generate_test": record
#             }
#             all_records[sub_dirs[j]] = record_data
#             json.dump(record_data, file, indent=4, ensure_ascii=False)
#
#     return True


def get_context_info(file_context: str) -> tuple[str, str, list[dict[str, str]]]:
    data_list = []

    root = get_tree_root(content=file_context)
    package_name = ""
    docstring = ""
    class_name = ""
    fields = []
    simple_method = []
    simple_context_list = []

    if package_declaration_node := find_node_by_type(node=root, target_type=TreeSitterJava.package_declaration):
        if scoped_identifier_node := find_node_in_children(node=package_declaration_node,
                                                           target_type=TreeSitterJava.scoped_identifier):
            package_name = get_node_text(scoped_identifier_node)
        simple_context_list.append(get_node_text(package_declaration_node))
    if import_declaration_node_list := find_nodes_by_type(node=root,
                                                          target_type=TreeSitterJava.import_declaration):
        for import_declaration_node in import_declaration_node_list:
            simple_context_list.append(get_node_text(import_declaration_node))
    if block_comment := find_node_in_children(node=root, target_type=TreeSitterJava.block_comment):
        docstring = get_node_text(block_comment)

    if class_declaration_node := find_node_by_type(node=root, target_type=TreeSitterJava.class_declaration):
        class_component_list = []
        for class_component in class_declaration_node.children:
            if class_component.type not in [TreeSitterJava.class_body]:
                class_component_list.append(get_node_text(class_component))
        if class_name_node := find_node_in_children(node=class_declaration_node,
                                                    target_type=TreeSitterJava.identifier):
            class_name = get_node_text(class_name_node)
        if class_body_node := find_node_in_children(node=class_declaration_node,
                                                    target_type=TreeSitterJava.class_body):
            if field_declaration_node_list := find_nodes_in_children(node=class_body_node,
                                                                     target_type=TreeSitterJava.field_declaration):
                for field_declaration_node in field_declaration_node_list:
                    fields.append(get_node_text(field_declaration_node))
            if method_declaration_node_list := find_nodes_in_children(node=class_body_node,
                                                                      target_type=TreeSitterJava.method_declaration):
                for method_declaration_node in method_declaration_node_list:
                    simple_list = []
                    for component in method_declaration_node.children:
                        if component.type != TreeSitterJava.block:
                            simple_list.append(get_node_text(component))
                    func_signature = " ".join(simple_list)
                    simple_method.append(func_signature)
            class_component_list.extend(["{\n", "\n".join(fields), "\n", "\n".join(simple_method), "\n}"])
            class_str = " ".join(class_component_list)
            simple_context_list.append(class_str)
            simple_context = "\n".join(simple_context_list)
            if method_declaration_node_list := find_nodes_in_children(node=class_body_node,
                                                                      target_type=TreeSitterJava.method_declaration):
                for method_declaration_node in method_declaration_node_list:
                    data = {"package": package_name, "docstring": docstring, "class_name": class_name}
                    if method_name_node := find_node_in_children(node=method_declaration_node,
                                                                 target_type=TreeSitterJava.identifier):
                        method_name = get_node_text(method_name_node)
                        data["method_name"] = method_name
                    if argument_node := find_node_in_children(node=method_declaration_node,
                                                              target_type=TreeSitterJava.formal_parameters):
                        argument = get_node_text(argument_node)
                        data["argument_name"] = argument
                    source_code = get_node_text(method_declaration_node)
                    data["source_code"] = source_code
                    data["full_context"] = file_context
                    data["simple_context"] = simple_context
                    data_list.append(data)
    return package_name, class_name, data_list


def test_bench_method_analysis(file_path: str):
    """

    :param file_path:
    :return:
    """
    # 设置基础环境
    env = config.configs.EnvType.BAILIAN
    model = config.configs.Model.DeepSeekV3_BaiLian

    generated_result = {}

    with open(file_path, "r", encoding="utf-8") as file:
        source_code = file.read()

    fm_class_content = source_code

    root_node = get_tree_root(content=source_code)
    if not root_node:
        return

    package_name = extract_java_package_name(root_node=root_node)

    # 从语法树中提取class节点以及class中的method进行更具体的处理
    class_declaration_node_list = find_nodes_in_children(node=root_node,
                                                         target_type=TreeSitterJava.class_declaration)

    for class_node in class_declaration_node_list:
        # 获取class_name
        class_name = get_node_text(
            find_node_in_children(node=class_node, target_type=TreeSitterJava.identifier))

        import_info_list = extract_import_str_list(node=root_node)

        generated_test_class_dict = test_bench_generate(source_code=source_code, env=env, model=model)
        for method_name, item in generated_test_class_dict.items():
            FQDN = ".".join([package_name, class_name, method_name])
            new_class_name = "_".join([class_name, method_name])
            generated_test_class = repair_error(generate_content=item, package_name=package_name,
                                                class_name=new_class_name,
                                                import_info=import_info_list, method_name=method_name)
            generated_result[FQDN] = generated_test_class
    #     if not methods_info or not test_frame:
    #         continue
    #
    for k, v in generated_result.items():
        # 对于每一个类，去项目对应的地方创建空的java文件（如果之前不存在的话）
        class_name = extract_identifier_from_fqdn(k, Position.second)
        method_name = extract_identifier_from_fqdn(k, Position.first)
        cls_name = "_".join([class_name, method_name])
        # cls_name = extract_identifier_from_fqdn(k, Position.first)
        is_ok, test_path = generate_test_file_new(file_path=file_path, class_name=cls_name)

        with open(test_path, 'w', encoding='utf-8') as file:
            file.write(v)

    return

def generate_test_file_new(file_path: str, class_name: str):

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
    # 标准化路径为POSIX格式（统一使用/分隔符）
    normalized_path = file_path.replace(os.sep, '/')

    # 替换首个出现的src/main/java（不区分大小写）
    if 'src/main/java' in normalized_path:
        test_path = normalized_path.replace(
            'src/main/java',
            'src/testbench',
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
    test_path = os.path.join(test_dir, f"{class_name}Test.java")


    if create_test_file(test_path):
        return True, test_path
        # print(f"成功创建测试文件：{test_path}")
    else:
        return False, test_path
        # print(f"测试文件已存在：{test_path}")


def test_generator():

    # 替换为需要生成单元测试的项目的根目录
    project_path = r"xxx"
    files = find_java_files(path=project_path,
                            exact_match=True)

    with ThreadPoolExecutor(max_workers=16) as executor:
        # 使用列表推导式提交所有任务
        futures = [executor.submit(
            test_bench_method_analysis,
            file_path=file,
        ) for file in files]

        # 使用tqdm包装as_completed实现动态进度条
        for future in tqdm(concurrent.futures.as_completed(futures),
                           total=len(files),
                           desc="Analyzing Java files",
                           unit="file"):
            future.result()


if __name__ == '__main__':
    # 生成单元测试
    test_generator()

    # # 清除无法通过编译的单元测试
    # checker = JavaTestFileChecker(max_fix_round=0)
    # checker.handle_result_for_compile()

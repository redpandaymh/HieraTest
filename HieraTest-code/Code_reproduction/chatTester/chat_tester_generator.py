import concurrent
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Any

from tqdm import tqdm
from tree_sitter import Node

from config.configs import EnvConfig, env, model, EnvType
from generate.formalizer import formatter
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_java_package_name, find_nodes_by_type, TreeSitterJava, get_node_text, \
    find_node_in_children, extract_import_str_list, find_nodes_in_children
from utils.utils import get_tree_root


# -----------------------------------------
# 辅助函数
# -----------------------------------------
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

def process_files(files: List[str], root: str) -> List[str]:
    # 先简单的排除掉package-info.java
    default_excluded_java_file = ["package-info.java"]
    return [os.path.join(root, f) for f in files if f.endswith('.java') and f not in default_excluded_java_file]

def ordered_dedup(lst):
    return list(dict.fromkeys(lst))

def return_code(gen_cont):
    gen_cont = '\n'.join([line for line in gen_cont.split('\n') if "Below is " not in line])
    gen_cont = gen_cont.replace("(Fixed)", "").replace("java\r\n", "").replace("...", "").replace("java\n",
                                                                                                  "").replace(
        "Java\n", "")
    # find code

    pattern = r"```(.*?)```"
    matches = re.findall(pattern, gen_cont, re.DOTALL)
    matchCode = [match for match in matches if len(match) > 5 and " void " in match][-1]

    JavaCode_list = matchCode.split("\n")

    import_statements = []
    TAG = False
    for line_code in JavaCode_list:
        if "import " in line_code:
            TAG = True
            import_statements.append(line_code)
        elif TAG == True:
            break
    import_statement = "\n".join(import_statements)

    codeBlock = []
    left_brack_list = []
    right_brack_list = []
    Start_Tag = False
    for current_line_number, line in enumerate(JavaCode_list, start=1):
        if ("@Test" in line or " void " in line) and Start_Tag == False:
            Start_Tag = True
            if "@Test" not in line:  # 生成的代码当中可能没有 @Test 这个关键字
                line_str = "@Test\n" + line
                codeBlock.append(line_str)
            else:
                codeBlock.append(line)

            left_brack_count = line.count("{")
            left_brack_list.extend(["{"] * left_brack_count)
            right_brack_count = line.count("}")
            right_brack_list.extend(["}"] * right_brack_count)
            continue
        if Start_Tag:
            codeBlock.append(line)

            left_brack_count = line.count("{")
            left_brack_list.extend(["{"] * left_brack_count)
            right_brack_count = line.count("}")
            right_brack_list.extend(["}"] * right_brack_count)
            if len(left_brack_list) == len(right_brack_list):
                break
    codeBlock_str = "\n".join(codeBlock)

    return codeBlock_str, import_statement


def commentDelete(code):
    # comment delete
    regex = r"/\*(.|\\n)*?\*/"
    noMultilineComments = re.sub(regex, "", code)

    # remove single line comments (// ...)
    regex = r"//.*"
    non_comment_code = re.sub(regex, "", noMultilineComments)

    pattern = re.compile(r"(?s)/\*.*?\*/|//.*?[\r\n]")  # 匹配 /**...*/ 样式的注释
    codeWithoutComment = pattern.sub("", non_comment_code)  # 去除注释

    return codeWithoutComment


def class_content_assemble(test_method, TestCodeShell, Test_Import_info) -> str:
    # package_name = [code for code in TestCodeShell.split("\n") if "package " in code and ";" in code][0].replace(
    #     "package ", "").replace(";", "").strip()

    codeShell_1 = TestCodeShell.replace("\nimport ", Test_Import_info + "\nimport ", 1)
    # codeShell_2 = codeShell_1.replace("//TOFILLL", test_method)
    return codeShell_1


def replace_test_class_name(java_code: str, old_name: str, new_name: str, rename_references=True) -> str:
    """
    替换Java代码中的类名（支持泛型、多行匹配和引用替换）

    参数:
        java_code: Java代码字符串
        old_name: 原类名（需完全匹配）
        new_name: 新类名
        rename_references: 是否同时替换类引用（构造函数/静态方法）

    返回:
        替换后的Java代码字符串
    """
    # 增强版正则表达式（支持泛型/多行/排除注释）
    class_decl_pattern = re.compile(
        r'(?<!\w)(class|interface|enum)(\s+)'  # 类型关键字和空白
        r'(\b' + re.escape(old_name) + r'\b)'  # 原类名（精确匹配）
                                       r'(\s*<[\w\s,<>?]*>)?'  # 泛型声明（可选）
                                       r'(?=\s*[^{]*\{)'  # 前瞻断言
    )

    # 类声明替换（保留原始空白和泛型）
    def decl_replacer(match):
        return match.group(1) + match.group(2) + new_name + (match.group(4) or '')

    # 类引用替换（构造函数和静态方法）
    reference_patterns = [
        (re.compile(r'\bnew\s+' + re.escape(old_name) + r'\s*\('), f'new {new_name}('),  # 构造函数
        (re.compile(r'\b' + re.escape(old_name) + r'\s*\.'), f'{new_name}.')  # 静态方法
    ]

    # 执行类声明替换
    modified_code = class_decl_pattern.sub(decl_replacer, java_code)

    # 可选：替换类引用
    if rename_references:
        for pattern, replacement in reference_patterns:
            modified_code = pattern.sub(replacement, modified_code)

    return modified_code


# -----------------------------------------
# 文件操作函数
# -----------------------------------------

def generate_test_file(files_path: str, class_name: str):
    # 验证输入文件
    if not os.path.isfile(files_path) or not files_path.endswith('.java'):
        print(f"错误：'{files_path}' 不是有效的Java文件")
        sys.exit(1)

    # # 提取包名
    # package_name = get_package_name(files_path)
    # if not package_name:
    #     print("无法从路径中识别包名，请确认文件在src/main/java目录下")
    #     sys.exit(1)

    # 生成测试文件
    test_path = get_test_file_path(files_path, class_name)

    if create_test_file(test_path):
        return True, test_path
        # print(f"成功创建测试文件：{test_path}")
    else:
        return False, test_path
        # print(f"测试文件已存在：{test_path}")


def create_test_file(test_path):
    """创建测试文件"""
    if not os.path.exists(test_path):
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        return True
    return False


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
    else:
        raise ValueError("路径中未找到src/main/java目录结构")

    # 重组为系统路径格式
    test_path = test_path.replace('/', os.sep)
    test_dir = os.path.dirname(test_path)
    return os.path.join(test_dir, f"{class_name}.java")


# -----------------------------------------
# 主要流程函数
# -----------------------------------------

def chat_tester_generate(class_node: Node, env: EnvType, model: str,
                         Test_Import_info: str, TestCodeShell: str) -> dict[str,Any]:
    # generate_map = {}
    class_signature_comp_list = []
    field_list = []
    methods_info: dict[str,Any] = {}
    class_constructor_method = ""
    all_method_signature = []
    class_name = ""

    for class_component in class_node.children:
        if class_component.type != TreeSitterJava.class_body:
            class_signature_comp_list.append(get_node_text(class_component))
            if class_component.type == TreeSitterJava.identifier:
                class_name = get_node_text(class_component)
        else:
            for body_component in class_component.children:
                component_text = get_node_text(body_component)
                if body_component.type == TreeSitterJava.field_declaration:
                    field_list.append(component_text)
                elif body_component.type == TreeSitterJava.constructor_declaration:
                    class_constructor_method = component_text
                elif body_component.type == TreeSitterJava.method_declaration:
                    method_name = get_node_text(
                        find_node_in_children(node=body_component, target_type=TreeSitterJava.identifier))
                    method_signature_comp_list = []
                    for method_component in body_component.children:
                        if method_component.type != TreeSitterJava.block:
                            method_signature_comp_list.append(get_node_text(method_component))
                    method_signature = " ".join(method_signature_comp_list)
                    methods_info[method_name] = {"method_name": method_name, "method_text": component_text,
                                                 "method_signature": method_signature}
                    all_method_signature.append(method_signature)

    class_signature = " ".join(class_signature_comp_list)
    MethodContext = class_signature + " {" + "\n" + "\n".join(all_method_signature) + "\n}"
    for method_name, method_info in methods_info.items():
        PL_Focal_Method = (class_signature + " {" + "\n" + "\n".join(field_list) + "\n" + class_constructor_method +
                           '# Focal method\n' + commentDelete(method_info.get("method_text", "")) + "\n" + "}")
        PL_Focal_Method = '\n'.join(filter(lambda x: x.strip(), PL_Focal_Method.split('\n')))
        Intention_NL = f'''Please describe the overall intention of the
        {method_name} method in as much detail as possible in one sentence.'''
        ask_intention_prompt = PL_Focal_Method + '\n\n' + Intention_NL
        instruction_test_intention = [
            {"role": "system", "content": "I want you to play the role of a professional who infers method intention."},
            {"role": "user", "content": ask_intention_prompt}
        ]

        Method_intention = chat_client_openai(env=env, messages=instruction_test_intention, model=model)
        Composit_prompt = "# Import information\n" + Test_Import_info + "\n\n# Focal Method Context\n" + MethodContext + "\n\n# Method intention \n" + Method_intention + "\n\n" + PL_Focal_Method + \
                          (f'\n\n# Instruction\nPlease generate a test method for the \"{method_name}\" '
                           f'according to the given `Import information`, `Focal Method Context` and `Method '
                           f'intention (it is crucial)`. Ensure that the generated test method is compilable, '
                           f'and cannot use the private and undefined method in `Method Context`.\nThe generated code '
                           f'should be enclosed within ``` ```.')

        instruction_test = [
            {"role": "system",
             "content": "I want you to play the role of a professional who writes Java test method for the Focal method. The following is the Class, Focal method and Import information."},
            {"role": "user", "content": Composit_prompt},
        ]

        generated_content = chat_client_openai(env=env, messages=instruction_test, model=model)
        test_method, import_statement = return_code(generated_content)
        # 填充import信息
        if "\nimport " in TestCodeShell:
            TestCodeShell = TestCodeShell.replace("\nimport ", Test_Import_info + "\nimport ", 1)
        # final_generated_class = class_content_assemble(test_method=test_method, TestCodeShell=TestCodeShell,
        #                                                Test_Import_info=import_statement)
        final_generated_class = formatter(methods_info={"1": {"generated_test": [test_method]}},
                                          test_frame=TestCodeShell)
        test_class_name = "_".join([class_name, method_name, "Test"])
        final_generated_class = replace_test_class_name(java_code=final_generated_class,
                                                        old_name=class_name + "_ESTest",
                                                        new_name=test_class_name)
        methods_info[method_name]["generated_test"] = final_generated_class
        methods_info[method_name]["generated_class_name"] = test_class_name
        methods_info[method_name]["pl_focal_method"] = PL_Focal_Method
        # methods_info[method_name]["old_class_name"] = class_name

    return methods_info


def get_public_info(node: Node) -> str:
    package_name = ""
    docstring = ""
    class_name = ""
    fields = []
    simple_method = []
    simple_context_list = []
    simple_context = ""

    class_declaration_node = node
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
                field_text = get_node_text(field_declaration_node)
                if "public" in field_text:
                    fields.append(field_text)
        if method_declaration_node_list := find_nodes_in_children(node=class_body_node,
                                                                  target_type=TreeSitterJava.method_declaration):
            for method_declaration_node in method_declaration_node_list:
                method_context = get_node_text(method_declaration_node)
                if "public" in method_context:
                    simple_list = []
                    for component in method_declaration_node.children:
                        if component.type != TreeSitterJava.block:
                            simple_list.append(get_node_text(component))
                    simple_list.append(";")
                    func_signature = " ".join(simple_list)
                    simple_method.append(func_signature)
        class_component_list.extend(["{\n", "\n".join(fields), "\n", "\n".join(simple_method), "\n}"])
        class_str = " ".join(class_component_list)
        simple_context_list.append(class_str)
        simple_context = "\n".join(simple_context_list)

    return simple_context


def chat_tester_method_analysis(file_path: str) -> dict:
    # 需要从evosuite生成的测试文件中提取import信息和类框架
    # 这里需要将文件夹修改为evosuite生成的单元测试的文件夹地址，比如这里的.evosuite/best-tests
    evo_file_path = file_path.replace(os.path.join("src", "main", "java"), os.path.join(".evosuite", "best-tests"))
    evo_file_path = evo_file_path.replace(".java", "_ESTest.java")
    evo_scaffolding_file_path = evo_file_path.replace("_ESTest.java", "_ESTest_scaffolding.java")

    generated_result = {}
    import_in_test_list = []

    if not os.path.exists(evo_file_path) or not os.path.exists(evo_scaffolding_file_path):
        return generated_result

    with open(file_path, "r", encoding="utf-8") as file:
        source_code = file.read()

    with open(evo_file_path, "r", encoding="utf-8") as file:
        evo_source_code = file.read()
    with open(evo_scaffolding_file_path, "r", encoding="utf-8") as file:
        evo_scaffolding_source_code = file.read()

    evo_scaffolding = get_tree_root(evo_scaffolding_source_code)
    scaffolding_method_list = find_nodes_by_type(node=evo_scaffolding, target_type=TreeSitterJava.method_declaration)
    for scaffolding_method in scaffolding_method_list:
        if "private static void initializeClasses()" in get_node_text(scaffolding_method):
            string_literal_list = find_nodes_by_type(node=scaffolding_method,
                                                     target_type=TreeSitterJava.string_literal)
            for string_literal in string_literal_list:
                string_fragment_node = find_node_in_children(node=string_literal,target_type=TreeSitterJava.string_fragment)
                string_literal_text = get_node_text(string_fragment_node)
                if "$" not in string_literal_text:
                    import_in_test_list.append("import " + string_literal_text + ";")

    TestCodeShell = evo_source_code

    import_in_test = "\n".join(import_in_test_list)
    root_node = get_tree_root(content=source_code)
    if not root_node:
        return {}

    package_name = extract_java_package_name(root_node=root_node)

    # 从语法树中提取class节点以及class中的method进行更具体的处理
    class_nodes = find_nodes_by_type(root_node, target_type=TreeSitterJava.class_declaration)

    for class_node in class_nodes:
        # 获取class_name
        class_name = get_node_text(
            find_node_in_children(node=class_node, target_type=TreeSitterJava.identifier))
        FQDN = package_name + '.' + class_name

        generated_test_class = chat_tester_generate(class_node=class_node, env=env, model=model,
                                                    Test_Import_info=import_in_test, TestCodeShell=TestCodeShell)

        public_info = get_public_info(node=class_node)
        generated_test_class["public_info"] = public_info

        generated_result[FQDN] = generated_test_class

    for k, v in generated_result.items():
        # 对于每一个类，去项目对应的地方创建空的java文件（如果之前不存在的话）
        for method_name, method_info in v.items():
            # 这里如果为空就需要报出异常了
            if method_name == "public_info":
                continue
            class_name = method_info.get("generated_class_name")
            class_content = method_info.get("generated_test")
            is_ok, test_path = generate_test_file(files_path=file_path, class_name=class_name)
            try:
                with open(test_path, 'w', encoding='utf-8') as file:
                    file.write(class_content)

            except IOError as e:
                print(f"e:{e}")

    return generated_result


def copy_scaffolding_file(project_dir: str):
    """
    在指定目录下查找所有evo目录中的scaffolding.java文件，复制到对应的test目录中。

    参数:
    start_dir (str): 要开始搜索的目录的绝对路径。
    """
    # 检查输入目录是否存在
    if not os.path.isdir(project_dir):
        raise ValueError(f"提供的目录不存在：{project_dir}")

    target_relative_path_start = os.path.join('.evosuite', 'best-tests')

    for root, dirs, files in os.walk(project_dir):
        # 检查当前目录是否在 'src/test/java' 路径下
        # 为了跨平台兼容性，我们使用 os.path.normpath 来统一路径分隔符
        normalized_root = os.path.normpath(root)
        normalized_target_start = os.path.normpath(target_relative_path_start)

        # 确保当前目录是在目标路径内，或者就是目标路径本身
        # 使用 startswith 来检查
        if normalized_target_start not in normalized_root:
            # 如果不在目标路径下，跳过当前目录及其子目录
            continue

        for file in files:
            if file.endswith('scaffolding.java'):
                target_path = root.replace(target_relative_path_start, os.path.join("src", "test", "java"))
                os.makedirs(target_path, exist_ok=True)
                # 执行文件复制
                shutil.copy2(os.path.join(root, file), os.path.join(target_path, file))


def test_generator():

    generated_result = {}

    # 修改为需要生成单元测试的项目的根目录
    project_path = r"xxx"

    # 函数内部需修改生成的evosuite单元测试文件的位置
    copy_scaffolding_file(project_dir=project_path)

    files = find_java_files(path=project_path,
                            exact_match=True)

    with ThreadPoolExecutor(max_workers=16) as executor:
        # 使用列表推导式提交所有任务
        futures = [executor.submit(
            chat_tester_method_analysis,
            file_path=file,
        ) for file in files]

        # 使用tqdm包装as_completed实现动态进度条
        for future in tqdm(concurrent.futures.as_completed(futures),
                           total=len(files),
                           desc="Analyzing Java files",
                           unit="file"):
            result = future.result()
            generated_result.update(result)

    with open("generated_table.json", "w", encoding='utf-8') as f:
        json.dump(generated_result, f,
                  indent=4,
                  ensure_ascii=False,  # 保留非ASCII字符
                  )


if __name__ == '__main__':
    test_generator()

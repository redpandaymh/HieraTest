from check.check_result import JavaTestFileChecker
from config.configs import env, model
from generate.formalizer import formatter_one_for_one, integrate_error_list
from generate.generator import generate_unit_test
from generate.method_analysis import post_process_result
from generate.path_selection import path_selection
from locate.bug_locator import locate
from reappearance.TestBench.test_bench_generator import get_simple_context
from reappearance.defect4j.d4j_utils.utils import handle_compile_error_list
from templates.chat_prompt_template import system_role_prompt
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_class_name, extract_java_package_name, extract_import_str_list
from utils.utils import get_tree_root, remove_comments_and_docstrings, extract_java_code, ResultHandleMode


def bugWhisper_generate(class_content: str, fm_name: str, fm_method: str) -> str:
    # 获取类名称
    root_node = get_tree_root(content=class_content)
    class_name = extract_class_name(node=root_node)
    # 获取package name
    package_name = extract_java_package_name(root_node=root_node)
    # # 得到FQDN
    # FQDN = package_name + '.' + class_name
    # 得到原始的import信息
    import_list: list = extract_import_str_list(node=root_node)

    class_content = remove_comments_and_docstrings(
        source=class_content, lang="java")[0]
    methods_info: dict = {
        fm_name: {"trigger_fm": fm_method, "fm_name": fm_name}}
    methods_info, _ = locate(
        methods_info=methods_info, env=env, model=model)
    methods_info = path_selection(
        methods_info=methods_info, fm_class_content=class_content)
    methods_info, test_frame = generate_unit_test(methods_info=methods_info, model=model, env=env,
                                                  fm_class_content=class_content, class_name=class_name)

    generated_class_content = ""
    generated_test_class_dict = formatter_one_for_one(
        methods_info=methods_info, test_frame=test_frame)
    for method_name, generated_class in generated_test_class_dict.items():
        # method_FQDN = FQDN + "." + method_name
        new_class_name = class_name + "_" + method_name
        generated_test_class = post_process_result(symbol_table={}, source_code=generated_class,
                                                   package_name=package_name,
                                                   java_inner_table={},
                                                   class_name=new_class_name,
                                                   test_dependency_table={},
                                                   origin_import_list=import_list)
        if not generated_test_class:
            continue
        else:
            generated_class_content = generated_test_class

    return generated_class_content


def bugWhisper_repair(compile_error_list: list, origin_class_content: str,
                      unit_test_content: str, fm_method: str) -> str:

    compile_error = handle_compile_error_list(compile_error_list)
    simple_context = get_simple_context(file_context=origin_class_content)
    input_str = f"""
                # Task
                Here are some Java compilation error messages. 
                Please fix the content of the given Java unit test file based on these error messages. 
                You do not need to provide any explanation, just return the fixed code. 
                The returned code needs to be wrapped in ```java```.
                
                # Task Requirements
                1. Use JUnit 3 testing framework
                2. Only modify test function content
                3. Required imports must be placed before test functions
                4. Return complete fixed code only (no explanations)
                5. you should not change the name of the unit test function unless the error is Duplicate method
                6. If only one function needs to be repaired, then you should only generate one repaired function
                7. If the reason for the compilation error is that a private function was called, please test it using reflection
                
                # Simplified original class context
                {simple_context}
                
                # The focal method under test:
                {fm_method}
                
                # unit test content need to fix
                {unit_test_content}
                
                # compile error information
                {compile_error}

                """
    instructions = [
        {"role": "system", "content": system_role_prompt},
        {"role": "user", "content": input_str}]
    fixed_result = chat_client_openai(
        env=env, messages=instructions, model=model)
    fixed_result = extract_java_code(text=fixed_result)
    return fixed_result

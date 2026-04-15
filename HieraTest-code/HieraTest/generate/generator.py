from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from tree_sitter import Node
from utils.chat_client import chat_client_openai
# import sys
from config.configs import EnvType

from utils.utils import get_tree_root, extract_java_code
from utils.parse_utils import find_nodes_by_type, find_node_in_children, get_node_text, extract_class_name, \
    TreeSitterJava, extract_class_frame, extract_java_package_declare, extract_import_str_list
from templates.chat_prompt_template import special_prompt, controller_concrete_example, test_frame_generate_prompt, \
    system_role_prompt, test_generate_prompt, service_concrete_example, controller_special_guidelines


def check_fields(fm_class_content: str, generated_test_frame: str) -> bool:
    """
        作用是检查被测类的fields是否都在生成的单元测试框架里面被mock到了
        以及测试类的类型是否正确
    :param fm_class_content:
    :param generated_test_frame:
    :return:
    """
    fm_root = get_tree_root(content=fm_class_content)
    fm_fields_list = get_fields_type_list(node=fm_root)
    class_name = extract_class_name(node=fm_root)
    fm_fields_list.append(class_name)

    frame_root = get_tree_root(content=generated_test_frame)
    generated_fields_list = get_fields_type_list(node=frame_root)

    for field in fm_fields_list:
        if field not in generated_fields_list:
            return False
    return True


def get_fields_type_list(node: Node) -> list:
    """
        返回指定node下的field的变量类型list
    :param node:
    :return:
    """
    fields_list = []
    fields = find_nodes_by_type(node=node, target_type=TreeSitterJava.field_declaration)
    if fields:
        for field in fields:
            type_name = find_node_in_children(node=field, target_type=TreeSitterJava.type_identifier)
            if type_name:
                fields_list.append(get_node_text(type_name))
    return fields_list


def check_has_class(generated_test_frame: str) -> bool:
    fm_root = get_tree_root(content=generated_test_frame)
    if class_node := find_nodes_by_type(node=fm_root, target_type=TreeSitterJava.class_declaration):
        return True
    else:
        return False


def generate_unit_test(methods_info: dict, model: str, env: EnvType,
                       fm_class_content: str, class_name: str):
    methods_info_copy = methods_info.copy()
    fm_import_context = ""
    concrete_example = ""
    test_type: str = ""
    # 简单的对被测类进行分类
    if class_name.endswith("Controller"):
        concrete_example = controller_concrete_example
        test_type = "controller"
    elif class_name.endswith("ServiceImpl") or class_name.endswith("Service"):
        concrete_example = service_concrete_example
    else:
        concrete_example = "None"

    input_str0 = test_frame_generate_prompt.format(special_prompt=special_prompt,
                                                   concrete_example=concrete_example,
                                                   fm_class_content=fm_class_content)

    instructions_0 = [
        {"role": "system", "content": system_role_prompt},
        {"role": "user", "content": input_str0}
    ]

    # 检查test_pre是否生成成功
    check_num = 3
    cnt = 0
    is_ok = False
    test_pre: str = ""
    while cnt < check_num and not is_ok:
        test_pre = chat_client_openai(env=env, messages=instructions_0, model=model)
        test_pre = extract_java_code(text=test_pre)
        if not test_pre:
            print(f"fail to generate test framework:{cnt}")
        is_ok = check_has_class(generated_test_frame=test_pre)
        cnt += 1
    # 清理生成框架中的单元测试函数，减少对单元测试函数生成的干扰
    root = get_tree_root(content=test_pre)
    package_declaration_str = extract_java_package_declare(root)
    import_declaration_str_list = extract_import_str_list(node=root)
    import_declaration_str = "\n".join(import_declaration_str_list)
    class_frame = extract_class_frame(class_content=test_pre)
    test_pre = "\n\n".join([package_declaration_str, import_declaration_str, class_frame])

    with ThreadPoolExecutor(max_workers=16) as executor:  # Adjust max_workers as needed
        for k, v in methods_info_copy.items():
            new_item = v.copy()
            new_item["generated_test"] = []
            try:
                dependency_info: str = new_item.get("dependency_info_str", "")
                trigger_fm: str = new_item["trigger_fm"]
                if not fm_import_context:
                    fm_import_context = new_item["fm_import_context"]
                fm_field_context: str = new_item["fm_field_context"]
                # fm_class_content = new_item['fm_class_content'] # Removed because we are passing in
                # clean_fm_class_content = remove_comments_and_docstrings(fm_class_content, 'java') # Removed as well
                condition_constraints = new_item["condition_constraints"]
                fm_class_name = new_item["fm_class_name"]

                # Prepare arguments for _generate_test_for_constraint
                future_results = []
                for constraint in condition_constraints:
                    future = executor.submit(
                        generate_test_for_constraint_thread,
                        k,
                        constraint,
                        model,
                        env,
                        test_pre,
                        fm_class_content,
                        fm_field_context,
                        trigger_fm,
                        dependency_info,
                        test_type,
                    )
                    future_results.append(future)  # Store the Future objects

                # Process the results as they become available.
                for future in future_results:
                    result = future.result()
                    if result:
                        new_item["generated_test"].append(result)  # Append the generated test
                methods_info_copy[k] = new_item  # Update the item in the copy

            except Exception as e:
                print(f"Error processing method {k}: {e}")


    return methods_info_copy, test_pre


def generate_test_for_constraint_thread(
        k: str,
        constraint: str,
        model: str,
        env: EnvType,
        test_pre: str,
        fm_class_content: str,
        fm_field_context: str,
        trigger_fm: str,
        dependency_info: Optional[str],
        test_type: str,
) -> Optional[str]:
    """
    处理单元测试生成的线程任务
    """
    try:
        input_str: str = test_generate_prompt.format(special_prompt=special_prompt,
                                                     constraint=constraint,
                                                     test_pre=test_pre,
                                                     fm_class_content=fm_class_content,
                                                     fm_field_context=fm_field_context,
                                                     trigger_fm=trigger_fm,
                                                     dependency_info=dependency_info,
                                                     controller_special_guidelines=controller_special_guidelines if
                                                     test_type == "controller" else None
                                                     )

        input_instructions = [
            {"role": "system", "content": system_role_prompt},
            {"role": "user", "content": input_str},
        ]
        res = chat_client_openai(env=env, messages=input_instructions, model=model)
        res = extract_java_code(text=res)
        if res:
            return res  # 返回生成的代码
        else:
            print(f"method:{k} fail to generate response for constraint: {constraint}")
            return None
    except Exception as e:
        print(f"Error generating test for method {k}, constraint {constraint}: {e}")
        return None


if __name__ == "__main__":
    print("A")

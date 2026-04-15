from config.configs import env, model
from reappearance.chatTester.chat_tester_generator import commentDelete, return_code, get_public_info
from reappearance.defect4j.d4j_utils.utils import handle_compile_error_list, test_skeleton
from utils.chat_client import chat_client_openai
from utils.parse_utils import find_node_by_type, TreeSitterJava, get_node_text, find_node_in_children, \
    extract_import_str_list, repair_imports, repair_package, repair_class_name, extract_java_package_name, \
    extract_class_name, extract_method_name
from utils.utils import get_tree_root, extract_java_code


def chatTester_generate(class_content: str, fm_name: str, fm_method: str) -> str:

    root_node = get_tree_root(content=class_content)
    class_node = find_node_by_type(node=root_node, target_type=TreeSitterJava.class_declaration)
    if not class_node:
        return ""
    import_str_list = extract_import_str_list(node=class_node)
    Test_Import_info = "\n".join(import_str_list)
    class_signature_comp_list = []
    field_list = []
    methods_info: dict[str, dict] = {}
    class_constructor_method = ""
    all_method_signature = []
    class_name = ""

    package_name = extract_java_package_name(root_node=root_node)
    generate_result = ""

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
        if method_name != fm_name:
            continue
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
                           f'and cannot use the private and undefined method in `Method Context`.\n'
                           f"you could only use junit3, and @Test annotation is not allowed to use for it is the feature of junit4 and junit5,"
                           f"you cannot ues external mock libraries like mockito or easymock"
                           f"You should generate an independent unit test function and should not call any other (private or public)"
                            f"auxiliary functions, utility methods, or Lambda expressions within the generated unit test function."
                           f'The generated code should be enclosed within ``` ```.')

        instruction_test = [
            {"role": "system",
             "content": "I want you to play the role of a professional who writes Java test method for the Focal method. The following is the Class, Focal method and Import information."},
            {"role": "user", "content": Composit_prompt},
        ]

        generated_content = chat_client_openai(env=env, messages=instruction_test, model=model)
        test_method, import_statement = return_code(generated_content)
        # 以固定框架进行包裹

        test_content = test_skeleton + test_method + "}"
        new_class_name = "_".join([class_name, fm_name])
        test_content = repair_class_name(code=test_content, class_name=new_class_name + "Test")
        test_content = repair_package(code=test_content, package_name=package_name)
        test_content = repair_imports(code=test_content, import_list=[import_statement])
        generate_result = test_content
        break

    return generate_result


def chatTester_repair(compile_error_list: list, generated_class_content: str, fm_method: str,
                      origin_class_content: str, unit_test_content: str) -> str:
    error_info = handle_compile_error_list(compile_error_list)
    # error_info = "\n".join(compile_error_list)
    root_node = get_tree_root(content=origin_class_content)
    class_node = find_node_by_type(node=root_node,target_type=TreeSitterJava.class_declaration)
    class_name = extract_class_name(class_node)
    fm_method_root = get_tree_root(fm_method)
    fm_name = extract_method_name(fm_method_root)

    find_class_info = get_public_info(node=class_node)
    CompileError_fix_Prompt = find_class_info + "\n\n" + "# Test Method\n" + unit_test_content + "\n\n" + \
                              f"# Instruction\nThis test method has bug error  " \
                              f"{error_info}" \
                              f"\nPlease fix the buggy based on the given \"{class_name}\" class information (it is crucial) and return the complete and compilable class and after fix. \n" \
                              f"\nThe generated code should be enclosed within ```java ```."
    fix_prompt = CompileError_fix_Prompt

    instruction_test = [
        {"role": "system",
         "content": "I want you to play the role of a professional who repairs buggy lines of the test method. Unnecessary import statement can be removed."},
        {"role": "user", "content": fix_prompt},
    ]

    generated_content = chat_client_openai(env=env, messages=instruction_test, model=model)
    fixed_result = extract_java_code(generated_content)
    return fixed_result

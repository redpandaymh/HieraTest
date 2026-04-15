from config.configs import env, model
from reappearance.TestBench.content_repair import repair_error
from reappearance.TestBench.test_bench_generator import get_context_info, instruct_prompt_large_1, \
    instruct_prompt_large_2
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_import_str_list
from utils.utils import extract_java_code, get_tree_root

generate_mode = "SourceCode&Simple"

def test_case_info_d4j(package_name, class_name, method_name="named_method_name"):
    """
    Generate test case information(for prompt).
    """
    test_info = "package " + package_name + ";\n\n"
    test_info += "import junit.framework.TestCase;\n"
    test_info += "public class " + class_name + "Test extends TestCase {\n"
    test_info += "    public void " + method_name + "Test() {\n"
    test_info += "        <FILL>\n"
    test_info += "    }\n"
    test_info += "}"
    return test_info

def testBench_generate(class_content: str, fm_name: str, fm_method: str) -> str:
    root_node = get_tree_root(content=class_content)
    import_info_list = extract_import_str_list(node=root_node)

    package_name, class_name, data_list = get_context_info(file_context=class_content)

    for _, data in enumerate(data_list):
        class_name = data.get("class_name")
        method_name = data.get("method_name")
        if method_name != fm_name:
            continue
        new_class_name = "_".join([class_name, method_name])
        test_info = test_case_info_d4j(data['package'], new_class_name, method_name)
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

        # 直接进行修复
        FQDN = ".".join([package_name, class_name, method_name])
        new_class_name = "_".join([class_name, method_name])
        generated_test_class = repair_error(generate_content=res, package_name=package_name,
                                            class_name=new_class_name,
                                            import_info=import_info_list, method_name=method_name)
        return generated_test_class

    return ""
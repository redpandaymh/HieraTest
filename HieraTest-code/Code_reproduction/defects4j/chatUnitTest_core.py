import re

from reappearance.defect4j.d4j_utils.utils import find_method_list_signature, test_skeleton, handle_compile_error_list
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_class_name, extract_method_signature, find_nodes_by_type, TreeSitterJava, \
    repair_imports, repair_class_name, repair_package, extract_java_package_name
from utils.utils import get_tree_root, extract_java_code
from config.configs import env, model

generate_user_prompt_template = \
    """
    The focal method is {method_sig} in the focal class {class_name}.
    Information of the focal method is
    ```{full_fm}```.
    Information of the other method is
    {other_methods_str}
    """

generate_system_prompt = \
    """
    You are a senior tester in Java projects, your task is writting tests for a specific focal method in a focal 
    class with JUnit3, do not use mockito (A focal method means a method under test). I will provide the following 
    information of the focal method: 1. Required dependencies to import. 2. The focal class signature. 3. Source code 
    of the focal method. 4. Signatures of other methods and fields in the class. I will provide following brief 
    information if the focal method has dependencies: 1. Signatures of dependent classes. 2. Signatures of dependent 
    methods and fields in the dependent classes. You need to create a complete unit test using JUnit3, ensuring to 
    cover all branches. Compile without errors, and use reflection to invoke private methods or fields if needed. No 
    additional explanations required.        
    here is a simple example of junit3 test frame:
        import junit.framework.TestCase;
        public class CalculatorTest  extends TestCase {{ 
            protected void setUp() throws Exception {{
            calculator = new Calculator(); // 创建 Calculator 的实例
        }}   
            public void testAddPositiveNumbers() {{
            System.out.println("Testing testAddPositiveNumbers()");
            // 断言：验证实际结果是否等于预期结果
            // assertEquals(expected, actual)
            assertEquals(5, calculator.add(2, 3));
            assertEquals(10, calculator.add(5, 5));
            }}
        }}
    You should generate an independent unit test function and should not call any other (private or public)
        auxiliary functions, utility methods, or Lambda expressions within the generated unit test function.
    """

repair_user_prompt = \
    """
    I need you to fix an error in a unit test, an error occurred while compiling and executing

    The unit test is:
    ```
    {unit_test}
    ```
    
    The error chatMessage is:
    ```
    {error_message}
    ```
    
    The unit test is testing the method `{method_sig}` in the class `{class_name}`,
    the source code of the method under test and its class is:
    ```
    {full_fm}
    ```
    
    ```
    The signatures of other methods in its class are `{other_method_sigs}`
    ```
    
    Please fix the error and return the whole fixed unit test. You can use Junit and reflection. No explanation is needed.
    """


def check_method_correct(code: str) -> bool:
    """
    检测是否为一个有效的函数声明

    Args:
        code: 要检查的代码字符串（期望是一个 Java 方法声明）。

    Returns:
        如果代码成功解析为 Java 方法声明，则返回 True，否则返回 False。
    """
    try:
        # 如果代码就是单个方法，可能会解析为 MethodDeclaration
        tree = get_tree_root(content=code)

        error_node_list = find_nodes_by_type(node=tree, target_type=TreeSitterJava.ERROR)
        if not error_node_list and tree.type == TreeSitterJava.method_declaration:
            return True
        else:
            return False

    except Exception as e:
        # 捕获其他可能的异常，例如解析器本身的问题，也视为方法不正确
        print(f"An unexpected error occurred during parsing: {e}")
        return False


def is_test(code: str) -> bool:
    """
    判断给定的代码字符串是否包含 JUnit 的 @Test 或 @ParameterizedTest 注解。

    Args:
        code: 要检查的代码字符串。

    Returns:
        如果代码包含 "@Test" 或 "@ParameterizedTest"，则返回 True，否则返回 False。
    """
    return "@Test" in code or "@ParameterizedTest" in code


def is_test_method(code: str) -> bool:
    """
    检查给定的代码字符串是否是一个测试方法。
    它首先调用 is_test() 来确认是否包含测试注解，
    然后（如果需要）调用 check_method_correct() 进行进一步的验证。

    Args:
        code: 要检查的代码字符串。

    Returns:
        如果代码是一个测试方法（通过 is_test() 和 check_method_correct() 的检查），
        则返回 True，否则返回 False。
    """
    # 同样，假设 is_test 和 check_method_correct 已定义
    return is_test(code) and check_method_correct(code)


def is_syntactic_correct(code: str) -> bool:
    """
    一个示例性的 isSyntacticCorrect 函数。
    请注意：这是一个非常简化的实现，仅用于演示。
    您需要根据实际需求替换为更健壮的语法检查逻辑。

    Args:
        code: 要检查的代码字符串。

    Returns:
        如果代码在基本语法上（例如，括号匹配）看起来正确，则返回 True。
    """
    # 简单的检查：平衡的花括号
    # 也可以考虑使用 javalang 进行更严格的解析，如 check_method_correct 中所示
    # 这里为了展示 syntacticCheck 的逻辑，我们先用一个简单的。
    try:
        root = get_tree_root(content=code)
        error_node_list = find_nodes_by_type(node=root, target_type=TreeSitterJava.ERROR)
        if not error_node_list:
            return True
        else:
            return False
    except Exception:
        # 捕获其他潜在的解析问题，例如不是方法声明
        return False


def contains_char(string: str, char_to_find: str) -> bool:
    """检查字符串是否包含指定的字符（作为单个字符）。"""
    return char_to_find in string


def count_occurrences(string: str, char_to_count: str) -> int:
    """计算字符串中某个字符出现的次数。"""
    return string.count(char_to_count)


def syntactic_check(code: str) -> str:
    """
    尝试修复不完整的 Java 代码片段的语法。
    如果代码在首次检查时是正确的，则返回原样。
    否则，尝试通过回溯、添加闭合括号和调整带有@符号的片段来修复，
    直到代码变得语法正确，或者达到尝试修复的终点。

    Args:
        code: 可能不完整的 Java 代码字符串。

    Returns:
        经过尝试修复后，语法正确的代码片段，或者一个空字符串如果修复失败。
    """
    stop_points = [";", "}", "{", " "]  # Stop point

    # 1. 第一次检查：如果代码本身就是正确的
    if is_syntactic_correct(code):
        return code
    else:
        # 2. 尝试从末尾回溯，找到第一个停止点并截断
        temp_code = code  # 使用临时变量，避免直接修改原始传入的 code
        for idx in range(len(temp_code) - 1, -1, -1):
            if temp_code[idx] in stop_points:  # Python 中可以直接用 in 检查列表中的元素
                temp_code = temp_code[:idx + 1]
                break

        # 3. 计算不匹配的花括号，并尝试添加缺失的闭合括号
        left_bracket_count = count_occurrences(temp_code, "{")
        right_bracket_count = count_occurrences(temp_code, "}")

        # 添加缺失的闭合花括号
        for _ in range(left_bracket_count - right_bracket_count):
            temp_code += "}\n"

        # 4. 第二次检查：经过回溯和添加括号后是否正确
        if is_syntactic_correct(temp_code):
            return temp_code

        # 5. 尝试使用正则表达式查找 "@" 之前的代码片段
        # Pattern: (?<=\\})[^\\}]+(?=@)  -> 查找在 '}' 之后，'@' 之前的非 '}' 字符序列
        # Python 对应：(?<=\\})[^}]*(?=@)  (注意：Java 的 \\} 在 Python 是 })
        try:
            # 使用 re.search 查找第一个匹配项，然后使用 re.findall 查找所有匹配项
            # Java 代码中的逻辑是找到所有匹配，然后取最后一个。
            # 这里的 regex 匹配的是一个 "组"，需要仔细处理。
            # Java 的 Pattern.compile("(?<=\\})[^\\}]+(?=@)") 查找的是：
            # 1. (?<=\\}): positive lookbehind for '}' - 必须在 '}' 之后
            # 2. [^\\}]+: one or more characters that are NOT '}'
            # 3. (?=@): positive lookahead for '@' - 必须在 '@' 之前
            # 它的目的是找到在某个 '}' 和 '@' 之间的代码，例如 "someCode /* comment */ @another" -> "someCode /* comment */ "

            # 重新审视 Java 的意图：
            # "code = code.substring(0, endIdx).trim();"
            # "if (isSyntacticCorrect(code)) { return code; } else { return ""; }"
            # 这里的逻辑是：找到最后一个 `@` 之前，且在最后一个 `}` 之后的非 `}` 字符。
            # 如果存在 `@`，并且 `@` 之前有 `}`，那么就截断到 `@` 之前（如果 `}` 之后有内容）。

            # 更直接的理解是：寻找以 `@` 结尾，且在 `@` 之前的最后一段“完整的”代码块。
            # 那么，我们先找到所有 `@` 的位置。
            at_indices = [m.start() for m in re.finditer("@", temp_code)]

            if at_indices:
                last_at_index = at_indices[-1]
                # 尝试从 last_at_index 开始回溯，找到第一个停止点，截断。
                # 这部分逻辑与前面的回溯类似，但限制在 @ 之前。
                segment_to_check = temp_code[:last_at_index]

                for idx in range(len(segment_to_check) - 1, -1, -1):
                    if segment_to_check[idx] in stop_points:
                        segment_to_check = segment_to_check[:idx + 1]
                        break

                # 再次计算括号并添加
                left_count = count_occurrences(segment_to_check, "{")
                right_count = count_occurrences(segment_to_check, "}")
                for _ in range(left_count - right_count):
                    segment_to_check += "\n}"

                # 6. 第三次检查：经过 @ 相关的处理后是否正确
                if is_syntactic_correct(segment_to_check):
                    return segment_to_check
                else:
                    # 如果通过 @ 相关的回溯和括号添加后仍然不正确，则返回空字符串
                    return ""
            else:
                # 如果没有找到 @ 符号，并且前面几步都失败了，则返回空字符串
                return ""

        except Exception as e:
            # 捕获任何解析错误，例如在处理 @ 符号时
            print(f"Error during @ processing: {e}")
            return ""


def extract(text: str) -> str:
    """
    Extracts and potentially fixes Java code snippets from a given text.

    Args:
        text: The input string potentially containing Java code.

    Returns:
        The extracted and potentially fixed Java code snippet, or an empty string if none found or fixable.
    """
    ec = ""  # Extracted Code

    # Initialize flags from the input lists.
    # It's crucial to ensure these lists are mutable (like list) and have at least one element.
    # The original code implicitly assumes list[0] is the flag.

    # --- Step 1: Check if the entire input text is valid code ---
    if is_syntactic_correct(text):
        ec = text
        return ec  # Exit early if the whole input is valid code.

    # If not syntactically correct as a whole, reset the error flag initially.
    # The original logic has `has_syntactic_error_ref[0] = False` in the `else` block.
    # This seems to imply that if the whole input is *not* correct, we start with the assumption of no detected error *yet*.
    # Errors will be detected during extraction/fixing.
    found_code_block_flag = False  # Local flag to track if we found and processed a code block

    # --- Step 2: Search for ```java code blocks ---
    pattern_java_block = re.compile(r"```java\n?([\s\S]*?)```", re.IGNORECASE)

    # Use finditer directly - this is the corrected part.
    for match in pattern_java_block.finditer(text):
        match_content = match.group(1).strip()

        if not match_content:
            continue

        if is_test(match_content):
            syntactic_checked_match = syntactic_check(match_content)

            if syntactic_checked_match:
                ec = syntactic_checked_match
                found_code_block_flag = True
                return ec  # Return the first valid, test-related, potentially fixed block.

    # --- Step 3: If ```java blocks were not fruitful, search for general ``` code blocks ---
    if not found_code_block_flag:
        pattern_general_block = re.compile(r"```([\s\S]*?)```", re.IGNORECASE)

        # Use finditer directly for general blocks as well.
        for match in pattern_general_block.finditer(text):
            match_content = match.group(1).strip()

            if not match_content or match_content.lower().startswith("java"):
                continue

            if is_test(match_content):
                syntactic_checked_match = syntactic_check(match_content)

                if syntactic_checked_match:
                    ec = syntactic_checked_match
                    found_code_block_flag = True
                    return ec  # Return the first valid general test block.

    # --- Step 4: If no markdown code blocks were found/processed, search for inline code ---
    # This section handles code that isn't enclosed in triple backticks.
    if not found_code_block_flag:
        allowed_starts = {"import", "package", "@"}

        code_lines = text.split('\n')

        # Data structures to mimic Java's state tracking for brace counting and line analysis
        # We need to track these across the loop, similar to how Java might use instance variables or local arrays.
        # Using lists as mutable containers for these states.
        # These lists are not directly passed in, so they are local to this function scope.
        # The original Java code might have used instance variables. For this function, we simulate it with local variables.

        left_brace_counts = [0] * len(code_lines)
        right_brace_counts = [0] * len(code_lines)
        anchor_line_idx = -1  # Index of a line that looks like a test class declaration

        # First pass: analyze lines and find anchor
        for i, line in enumerate(code_lines):
            left_brace_counts[i] = count_occurrences(line, '{')
            right_brace_counts[i] = count_occurrences(line, '}')

            # Check for test class anchor (e.g., `public class ...Test`)
            # Using a more robust regex for "public class ...Test"
            if anchor_line_idx == -1 and re.search(r"^\s*public\s+class\s+.*\bTest\b", line):
                anchor_line_idx = i

        # If a potential test class anchor was found
        if anchor_line_idx != -1:
            # Find the actual start of the code block by going upwards from the anchor
            code_start_line_idx = anchor_line_idx
            while code_start_line_idx > 0:
                # Heuristic: consider lines that start with allowed keywords or annotations as part of the code block preamble.
                # If a line is not an allowed start and not an annotation, it might be the boundary.
                # The original Java logic was complex here. Let's try a simpler approach:
                # find the first line going up that *looks like* code (e.g., starts with import, package, @) or is empty.
                prev_line_stripped = code_lines[code_start_line_idx - 1].strip()
                if prev_line_stripped and not (
                        prev_line_stripped.startswith(tuple(allowed_starts)) or prev_line_stripped.startswith("@")):
                    # If the previous line is not an allowed start and not an annotation, it's likely not part of the block.
                    # We stop looking upwards.
                    break
                code_start_line_idx -= 1

            # Find the end of the code block by going downwards, balancing braces.
            code_end_line_idx = anchor_line_idx
            left_sum_for_end = 0
            right_sum_for_end = 0

            # Start from the anchor line and scan downwards
            for i in range(anchor_line_idx, len(code_lines)):
                left_sum_for_end += left_brace_counts[i]
                right_sum_for_end += right_brace_counts[i]

                # The original Java logic `leftSum >= 1 && rightSum >= 1` when balance is 0.
                # This implies we need at least one pair of braces within the block.
                if left_sum_for_end > 0 and left_sum_for_end == right_sum_for_end:
                    code_end_line_idx = i  # Found the end line
                    break
                # If we reach the end of lines without balancing, the last line is the end.
                if i == len(code_lines) - 1:
                    code_end_line_idx = i

            # Extract the potential code segment
            if code_start_line_idx <= code_end_line_idx:  # Ensure valid range
                potential_code_lines = code_lines[code_start_line_idx: code_end_line_idx + 1]
                potential_code_snippet = "\n".join(potential_code_lines)

                if potential_code_snippet:  # Ensure it's not an empty block
                    syntactic_checked_match = syntactic_check(potential_code_snippet)

                    if syntactic_checked_match:
                        ec = syntactic_checked_match
                        found_code_block_flag = True  # Mark that we found a block
                        return ec  # Return the first valid inline code block found.

    # If after all checks, no code was found or extracted, return empty string.
    # The flags `has_code_ref` and `has_syntactic_error_ref` will reflect the last state.
    # If `found_code_block_flag` is False, `has_code_ref[0]` should also be False.

    return ec


def extract_text_from_info(text: str) -> str:
    """
    Args:
        text: The input string potentially containing <INFO> and code blocks.

    Returns:
        The processed string, or the result of a general extract call.
    """
    if "<INFO>" in text:
        # Split text by "<INFO>". infoList[0] is text before <INFO>, infoList[1] is text after.
        infoList = text.split("<INFO>")

        # Ensure there's content after <INFO>
        if len(infoList) > 1:
            imports_info_section = infoList[1]

            # Find imports within ```java ... ``` blocks in the imports_info_section
            # Java: Pattern pattern = Pattern.compile("```[java]*([\\s\\S]*?)```");
            # Python equivalent: ```java (.*?)``` or ```(.*?)```.
            # The original Java uses `[java]*` which means optional "java".
            # Let's stick to the interpretation of ````java` or ````.
            # For this specific Java method, it seems to be looking for ````java` or ```` specifically.
            # Let's refine the regex to match the Java intent more closely:
            # It seems the intention might be to match blocks that *start with* `java` OR are general ` ``` `.
            # However, the `[java]*` in Java regex would usually be `java?` or `(?:java)?` in Python for optional.
            # Given the `matcher.group(1).trim().split("\n")` suggests the *content* is imports,
            # the pattern itself might be matching the block delimiters and the language tag.
            # Let's use ````java` and then fallback to general ` ``` `.

            # Pattern 1: Specifically ```java blocks
            pattern_java_block = re.compile(r"```java\n?([\s\S]*?)```", re.IGNORECASE)

            import_list_candidates = []

            # Use finditer for iterative matching
            for match in pattern_java_block.finditer(imports_info_section):
                matched_content = match.group(1).strip()
                if matched_content:
                    # Split the content by newline and add to our candidate list.
                    # The Java code uses split("\n"), so we do the same.
                    import_list_candidates.extend(matched_content.split("\n"))
                # Original Java `break;` means it only takes the *first* ```java block.
                break

                # If we didn't find a ```java block, try general ``` blocks.
            if not import_list_candidates:
                pattern_general_block = re.compile(r"```([\s\S]*?)```", re.IGNORECASE)
                for match in pattern_general_block.finditer(imports_info_section):
                    matched_content = match.group(1).strip()
                    if matched_content:
                        import_list_candidates.extend(matched_content.split("\n"))
                    break  # Take the first general block if no ```java block was found.

            # Now, iterate backwards through the original split parts of the text.
            # The Java code iterates `for (int i = infoList.size() - 1; i >= 0; i--)`
            # Python equivalent of this reverse iteration.
            for i in range(len(infoList) - 1, -1, -1):
                info_part = infoList[i]

                # If the current part contains ```, this is our target for extraction and repair.
                if "```" in info_part:
                    # Extract the code from this part (assuming it contains a code block).
                    # The Java code calls `extract(info)`. We use our Python `extract` function.
                    extracted_code_part = extract(info_part)

                    # Now, repair imports.
                    # Java: text = AbstractRunner.repairImports(extract(info), importList);
                    # Python: call our static method and pass the extracted code and imports.
                    # We need to ensure `import_list_candidates` are in a format `repairImports` expects.
                    # For now, we assume they are already formatted as needed by `repairImports`.
                    processed_text = repair_imports(extracted_code_part, import_list_candidates)

                    return processed_text  # Return the repaired text.

            # If we iterated through all parts and didn't find a ``` block to repair with the extracted imports.
            # This scenario seems unlikely if the original text had both <INFO> and ```.
            # If `import_list_candidates` were found but no ` ``` ` block was found for repair,
            # the Java code would implicitly fall through.

    # If `<INFO>` was not found, or if `<INFO>` was found but no suitable ``` block was processed for repair,
    # fall back to a general extract call on the original text.
    return extract(text)


def chatUnitTest_generate(class_content: str, fm_name: str, fm_method: str):
    # 获取类名称
    root_node = get_tree_root(content=class_content)
    package_name = extract_java_package_name(root_node=root_node)
    class_name = extract_class_name(node=root_node)

    fm_method_node = get_tree_root(content=fm_method)
    fm_method_signature = extract_method_signature(node=fm_method_node)
    other_method_signature_list = find_method_list_signature(node=root_node, fm_method_signature=fm_method_signature)
    other_methods_str = "\n".join(other_method_signature_list)
    generate_input = generate_user_prompt_template.format(method_sig=fm_method_signature,
                                                          class_name=class_name,
                                                          full_fm=fm_method,
                                                          other_methods_str=other_methods_str)

    instructions = [
        {"role": "system", "content": generate_system_prompt},
        {"role": "user", "content": generate_input}]

    generate_test_content = chat_client_openai(
        env=env, messages=instructions, model=model)
    generate_test_content = extract_java_code(text=generate_test_content)
    # generate_test_content = extract_text_from_info(generate_test_content)
    # 逻辑是如果生成的是单一的函数，就包裹到框架中，如果生成的是一个完整的文件，那么就对这个文件进行修复
    new_class_name = "_".join([class_name, fm_name])
    # 单一函数
    if is_test_method(generate_test_content):
        # 以固定框架进行包裹

        test_content = test_skeleton + generate_test_content + "}"
        test_content = repair_class_name(code=test_content, class_name=new_class_name + "Test")
        test_content = repair_package(code=test_content, package_name=package_name)
        test_content = repair_imports(code=test_content, import_list=[])
    # 完整内容
    else:
        # 修复保证整个框架的正确性
        test_content = repair_class_name(code=generate_test_content, class_name=new_class_name + "Test")
        test_content = repair_package(code=test_content, package_name=package_name)
        test_content = repair_imports(code=test_content, import_list=[])

    return test_content


def chatUnitTest_repair(compile_error_list: list, origin_class_content: str,
                        fm_method: str, unit_test_content: str):
    # compile_error = "\n".join(compile_error_list)
    compile_error = handle_compile_error_list(compile_error_list)

    # 获取类名称
    root_node = get_tree_root(content=origin_class_content)
    # package_name = extract_java_package_name(root_node=root_node)
    class_name = extract_class_name(node=root_node)

    fm_method_node = get_tree_root(content=fm_method)
    fm_method_signature = extract_method_signature(node=fm_method_node)
    other_method_signature_list = find_method_list_signature(node=root_node, fm_method_signature=fm_method_signature)
    other_methods_str = "\n".join(other_method_signature_list)
    repair_input = repair_user_prompt.format(unit_test=unit_test_content,
                                             error_message=compile_error,
                                             method_sig=fm_method_signature,
                                             class_name=class_name,
                                             full_fm=fm_method,
                                             other_method_sigs=other_methods_str)
    instructions = [
        {"role": "system", "content": generate_system_prompt},
        {"role": "user", "content": repair_input}]

    fix_result = chat_client_openai(
        env=env, messages=instructions, model=model)
    fixed_result = extract_java_code(text=fix_result)
    return fixed_result

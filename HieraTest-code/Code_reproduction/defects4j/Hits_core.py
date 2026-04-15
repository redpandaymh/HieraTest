import json

from json_repair import repair_json

from config.configs import env, model
from reappearance.defect4j.d4j_utils.utils import find_method_list_signature, test_skeleton, handle_compile_error_list
from utils.chat_client import chat_client_openai
from utils.parse_utils import extract_method_signature, extract_java_package_name, extract_class_name, \
    find_nodes_by_type, TreeSitterJava, get_node_text, extract_import_str_list, repair_class_name, repair_package, \
    repair_imports, extract_method_name
from utils.utils import get_tree_root, extract_json_code, extract_java_code

prompt_template_hits_gen_slice = \
    """

    {method_sig} within the focal class {class_name}
    
    {full_fm}
    
    {other_methods_str}
    
    """

prompt_template_hits_gen_slice2 = \
    """
    ### Instructions on Decomposing the Method under Test into Slices
    
    1. Summarize the focal method.
    2. List the test environment settings required for running the focal method, including:
    - Enumerate all input parameters and object/class fields invoked in the focal method that need to be set .
    - Enumerate all object/class methods invoked in the focal method that need to be set.
    3. Important Note! Please decompose the solution program into multiple problem-solving steps according to the semantics. Each step should represent a slice of the method under test and accomplish a subtask.
    - Slices can be hierarchical.
    - Your analysis has two parts:
    a. Describe the subtask of the slice.
    b. Replicate the corresponding original code statements.
    4. Organize the hierarchical slices into a reformatted structure.
    - For example, if we have 4 slices A, B, C, and D. Slice A contains slice B and slice C, and slice D are siblings of slice A. Reformat them as follows:
    {slice A}.{slice B}: {description of the subtask to accomplish in the reformat} {corresponding original code statements}
    {slice A}.{slice C}: {description of the subtask to accomplish in the reformat} {corresponding original code statements}
    {slice D}: {description of the subtask to accomplish in the reformat} {corresponding original code statements}
    
    ### Format of the Output
    
    The output must strictly adhere to the following JSON format:
    
    ```json
    {
    "summarization": "...",
    "//": "Local variables defined in the focal method should not be reported.",
    "invoked_outside_vars": [
    "input_str: string, input parameter, the input string to handle",
    "code.format: public string, public class field of object 'code' of class Encoding, representing the format to encode the input string",
    "..."
    ],
    "invoked_outside_methods": [
    "parser.norm(string): public member method of object 'parser' of class 'Parser', responsible for normalizing the input string",
    "..."
    ],
    "steps": [
    {
    "desp": "Initialization and setup\n    - Initialize an empty list of tokens.\n    - Initialize a boolean flag `eatTheRest` to false.",
    "code": "    ArrayList&lt;String&gt; tokens = new List();\n boolean eatTheRest = false;\n"
    },
    {
    "desp": "...",
    "code": "..."
    },
    ...
    ]
    }
    ```
    """

prompt_template_hits_sys_gen = \
    """
    You, a professional Java programmer & tester, the co-worker with the user in the pair-programming, are going to write a Java unit test for a method following the user's instructions. You'll be provided with:

    1. The implementation of the method-to-test
    2. The fields and method signatures of all classes that the method-to-test replies on.
    3. The package name and the imports of the file contains the method-to-test.
    
    The instructions will be in detail in each phase's user prompt.
    
    The basic information of your workarounds are:
    1. The Programming Langauge: Java
    2. The Tools for Unit Tests: JUnit3
    3. Do not use mockito
    
    The basic requirements for your responses are:
    
    1. Complete all required tasks as outlined in the user's message in a SINGLE response.
    2. Adhere meticulously to all instructions provided by the user.
    3. Deliver precise and accurate responses, getting straight to the point.
    
    
    Now you're going to be shown to the user. You're going to follow the user's instructions on executing the plan. We expect your excellent performance.
    """

prompt_template_hits_gen = \
    """
    Greetings! Thank you for assisting me in crafting the unit test. Your expertise is invaluable in generating test cases targeting specific segments of the method-under-test. 
    Let's begin by introducing the method to be tested along with its dependencies. Then, detailed instructions will follow for generating the test case. 
    Finally, examples will illustrate how to utilize the method-under-test and compose corresponding test cases.

    ### Method-to-test && Dependencies
    
    **Introduction of method-to-test ({method_sig}) and Focal Class ({class_name})**
    
    The method-to-test, {method_sig}, resides in the focal class {class_name}.
    
    Here is the source code of the focal class, including member methods and fields. The full implementation of the method-to-test will be provided, along with summarizations and signatures of other member methods.
    
    The complete code provided here is for reference only and is not intended for generating unit tests.
    ```java
    {full_fm}
    ```
    
    Based on the information provided above, generate unit tests for code {step_code}. The description of this code is {step_desp}
    
    Now please generate a whole unit test file for the method-to-test.
    
    #### Requirements and Attention for the Unit Test to Generate:
    
    - Ensure that the unit tests are executable: they should run without any compilation errors, runtime errors, or timeouts.
    - Aim for comprehensive coverage: the unit tests should encompass a significant portion of the codebase, including instructions and branches within the method under test.
    - Avoid altering the method under test.
    - Generate a complete unit test file, including the package declaration and all imports.
    - Import all dependent libraries used in the unit test file.
    - Name the test class as {class_name}_Test.
    - Ensure that the unit test methods do test the method under test:
    - Target the method under test as {class_name}.{method_name}.
    - Utilize appropriate tools and adhere to the language style guidelines:
    - Utilize JUnit3  for testing. Do not use @Test for it is the feature of junit4 and junit5.
    - You should generate an independent unit test function and should not call any other (private or public)
        auxiliary functions, utility methods, or Lambda expressions within the generated unit test function.
    - The type of the generated unit test function should be public
    
    ### Reference Template
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
    
    
    ### Output Format:
    
    Here are my requirements for your output format:
    
    <generate>
        The whole unit test file is:
        ```java
        ...
        ```
    </generate>
    
    Now, armed with this information, please proceed with the generation following my instructions.
    You MUST finish all generation in ONE RESPONSE!
    You MUST FULLY write ALL test methods!
    You shouldn't leave any spare work for the human! Finish everything!
    ```
    """

prompt_template_hits_repair = \
    """
    Hello! Thank you for reaching out for assistance in fixing the unit test. I'll provide you with the failed unit test, 
    the error report, and then guide you through the steps to fix the issues. Finally, I'll share examples of well-structured unit tests.

    # Unit Test to Fix
    
    Here's the unit test that needs fixing. To help you locate the error statements, I provide the line numbers.
    
    ```java
    {unit_test}
    ```
    The error encountered when running this unit test is:
    
    ```
    {error_message}
    ```
    
    # Procedures for Fixing the Unit Test:
    Let's proceed step by step:
    
    1. Pick out the statements that the errors occur.
    2. Explain the causes of the errors.
    3. Give solutions on how to fix the errors.
    4. Provide the complete fixed unit test, utilizing JUnit3 .
    
    # Requirements and Considerations for the Unit Test Fix:
    - Ensure the unit tests are executable without compile errors, runtime errors, or timeouts.
    - Aim for high coverage scores, covering as many instructions and branches of the method under test as possible.
    - Avoid modifying the method under test.
    - Generate the entire unit test file, including package declaration and imports.
    - Ensure correct testing of the method under test:
    - The method under test is defined in {class_name}.
    - The method under test is ${class_name}.{method_name}.
    - Utilize correct tools and adhere to Java 6/7 language style:
    - You can use JUnit3 .
    - The language style should follow Java 6/7 conventions.
    - DO NOT generate line numbers.
    - Use reflection to invoke private methods or fields if needed.
    
    # Output Format
    To facilitate generating the desired unit test, follow these instructions:
    
    < Generation Begin >
    ## 1. Pick out the statements with errors:
    ...
    
    ## 2. Explain the causes of the errors
    ...
    
    ## 3. Give solutions to the errors
    ...
    
    ## 4. Provide the complete fixed unit test File
    
    ```java
    ...
    ```
    < Generation Over >
    
    Please proceed with generating the fixed unit test.
    Ensure all generations are provided in a single response.
    Ensure your generation contains NO line numbers!
    ```
    """


def hits_generate(class_content: str, fm_name: str, fm_method: str) -> str:
    root_node = get_tree_root(content=class_content)
    package_name = extract_java_package_name(root_node=root_node)
    class_name = extract_class_name(node=root_node)

    fm_method_node = get_tree_root(content=fm_method)
    fm_method_signature = extract_method_signature(node=fm_method_node)
    other_method_signature_list = find_method_list_signature(node=root_node, fm_method_signature=fm_method_signature)
    other_methods_str = "\n".join(other_method_signature_list)
    generate_slice_input = prompt_template_hits_gen_slice.format(method_sig=fm_method_signature,
                                                                 full_fm=fm_method,
                                                                 class_name=class_name,
                                                                 other_methods_str=other_methods_str,
                                                                 )
    instructions = [
        {"role": "system", "content": prompt_template_hits_sys_gen + prompt_template_hits_gen_slice2},
        {"role": "user", "content": generate_slice_input}]
    slice_json_str = chat_client_openai(
        env=env, messages=instructions, model=model)
    slice_json_str = extract_json_code(text=slice_json_str)
    slice_json_str = repair_json(slice_json_str)

    method_slice_info: dict = json.loads(slice_json_str)
    generated_method_list = []
    generated_import_list = []
    if method_slice_info:
        steps = method_slice_info.get("steps", [])
        for item in steps:
            step_desp = item.get("desp", "")
            step_code = item.get("code", "")
            generate_test_input = prompt_template_hits_gen.format(method_sig=fm_method_signature,
                                                                  class_name=class_name,
                                                                  full_fm=fm_method,
                                                                  step_code=step_code,
                                                                  step_desp=step_desp,
                                                                  method_name=fm_name)
            instructions_1 = [
                {"role": "system", "content": prompt_template_hits_sys_gen},
                {"role": "user", "content": generate_test_input}]
            generated_method_content = chat_client_openai(env=env, messages=instructions_1, model=model)
            generated_method_content = extract_java_code(generated_method_content)
            root = get_tree_root(content=generated_method_content)
            method_declaration_node_list = find_nodes_by_type(node=root, target_type=TreeSitterJava.method_declaration)
            generated_method_list.extend(
                [get_node_text(method_declaration_node) for method_declaration_node in method_declaration_node_list])
            generated_import_list.extend(extract_import_str_list(node=root_node))


    generate_test_content = "\n".join(generated_method_list)
    test_content = test_skeleton + generate_test_content + "\n}"
    new_class_name = "_".join([class_name, fm_name])
    test_content = repair_class_name(code=test_content, class_name=new_class_name + "Test")
    test_content = repair_package(code=test_content, package_name=package_name)
    test_content = repair_imports(code=test_content, import_list=generated_import_list)
    return test_content


def hits_repair(compile_error_list: list, generated_class_content: str, origin_class_content: str,
                fm_method: str,unit_test_content:str) -> str:
    compile_error = handle_compile_error_list(compile_error_list)

    class_root = get_tree_root(origin_class_content)
    class_name = extract_class_name(class_root)
    fm_method_root = get_tree_root(fm_method)
    fm_name = extract_method_name(fm_method_root)
    repair_input = prompt_template_hits_repair.format(unit_test=unit_test_content,
                                                      error_message=compile_error,
                                                      method_name=fm_name,
                                                      class_name=class_name)
    instructions = [
        {"role": "system", "content": prompt_template_hits_sys_gen},
        {"role": "user", "content": repair_input}]

    fix_result = chat_client_openai(env=env, messages=instructions, model=model)
    fixed_result = extract_java_code(text=fix_result)
    # new_class_name = "_".join([class_name, fm_name])
    # test_content = repair_class_name(code=fixed_result, class_name=new_class_name + "Test")
    return fixed_result



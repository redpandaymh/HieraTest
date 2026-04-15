## 使用流程
### 模型服务密钥配置
可以在`bugWhisper/config/token_configs.json`中配置相应服务商的密钥  
也可以将对应密钥设置在环境变量中，避免直接的明文保存。
<details>
    <summary>token_configs.json文件示例</summary>

```json
{
    "tokens": {
        "siliconFlow": "xxx",
        "bailian": "xxx",
    }
}
```
</details>

### 预处理阶段
##### 生成相关符号表以供后续使用。

进入 ```bugWhisper/pre_process```文件夹下，运行  `symbol_table_generator.py` 和 `test_and_jdk_symbol_table_generator.py` 文件，以生成符号表。  
符号表将输出到`BUILDING_DATA_AND_LOG_STORE_PATH`所设置的位置。  

### 生成阶段
##### 与LLM交互，生成具体的单元测试文件并放置到指定项目的对应目录下。  
进入到 `bugWhisper/generate`文件夹下，调用`method_analysis.py`的main函数。  

### 编译修复阶段
##### 使用项目本身的环境，使用编译器对生成的单元测试代码进行编译，并根据编译反馈来进行修复，从而保证最终的单元测试文件可以通过编译
进入到 `bugWhisper/check`文件夹下，调用`check_compile_error.py`的`main_compile_wrapper`函数。 

### 运行修复阶段
##### 对运行时报错的单元测试函数，进行分类和修复
**注意** 进行这一步时，需要将顶层的pom文件恢复到原始的状态（一般来说即为编译器为javac的状态,同时需保留单元测试相关依赖）  
进入到 `bugWhisper/check`文件夹下，调用`check_test_error.py`中的`main_test_wrapper`函数  

### 运行日志
所有的日志记录都会输出到 BUILDING_DATA_AND_LOG_STORE_PATH属性所设置的目录下，以关键函数与时间戳作为文件名称。

## 项目结构

```
bugWhisper/
├── check/                                      // **关键流程入口** 核心功能:对Java项目进行编译、修复及运行。
│   ├── __init__.py
│   ├── ckeck_compile_error.py                  // 负责修复JAVA项目的编译错误
│   ├── check_test_error.py                     // 负责修复JAVA项目的运行错误
│   └── check_result.py                         // 错误修复具体的实现及相关工具函数
├── config/                                     // 项目配置相关。
│   ├── __init__.py
│   ├── configs.py                              // 设置可用的模型及模型服务商，以及一些可选的项目运行设置。
│   ├── token_configs.json                      // 可以保存不同服务商的token，以供与LLM交互时的身份验证
│   └── logging_config.py                       // 项目日志模块配置。
├── generate/                                   // 单元测试代码生成相关模块。
│   ├── __init__.py
│   ├── formalizer.py                           // 对LLM生成的单元测试代码进行规范化处理。
│   ├── generate_test_file.py                   // 在指定位置创建Java单元测试文件。
│   ├── generator.py                            // 与LLM交互，负责生成单元测试代码。
│   ├── method_analysis.py                      // **关键流程入口** 单元测试生成主入口：分析项目，多线程生成单元测试文件。
│   └── path_selection.py                       // 根据LLM定位的bug位置，获取特定的单元测试控制路径。
├── locate/                                     // Bug定位相关模块。
│   ├── __init__.py
│   └── bug_locator.py                          // 与LLM交互，定位最有可能发生bug的代码位置。
├── parser/                                     // 代码分析工具集，用于抽离代码执行路径，为单元测试生成提供条件限制。
│   ├── __init__.py
│   ├── DFG.py                                  // 数据流图分析工具。
│   ├── build.py                                // 历史遗留文件，可能与旧的构建过程相关。
│   ├── build.sh                                // 历史遗留文件，可能与旧的构建过程相关。
│   ├── my-languages.so                         // 历史遗留文件，可能是特定语言解析库的动态链接库。
│   └── utils.py                                // 代码分析所用到的辅助函数。
├── pre_process/                                // **关键流程入口** 项目预处理模块，生成关键的符号表，供后续生成及修复使用。
│   ├── __init__.py
│   ├── app.log                                 // 预处理过程中产生的日志文件。
│   ├── modify_inner_list.py                    // 暂未启用，可能用于特定数据结构修改。
│   ├── symbol_table_generator.py               // 生成项目的符号表。
│   └── test_and_jdk_symbol_table_generator.py  // 生成项目所依赖的单元测试以及JDK的符号表。
├── script/                                     // 辅助脚本和工具。
│   ├── __init__.py
│   ├── java_cfg.py                             // Java代码控制流图分析工具。
│   ├── server.sh                               // 历史遗留文件，可能与服务器启动或管理相关。
│   └── syntax_check.py                         // 历史遗留文件，可能用于语法检查。
├── templates/                                  // 模板文件，用于生成特定格式的内容。
│   ├── __init__.py
│   ├── chat_prompt_template.py                 // 与LLM交互的提示词模板。
│   └── pom_reference_template.py               // 用于修改pom文件的模板。
├── test/                                       // 项目的单元测试合集，用于验证各个模块的功能。
│   ├── check/                                  // 针对check模块的测试。
│   │   ├── __init__.py
│   │   ├── test4compile.py
│   │   ├── test4error_extract.py
│   │   ├── test4extract_eclipse_error.py
│   │   ├── test4extract_test_error.py
│   │   ├── test4modify_pom_sub.py
│   │   └── test4pomAnalyzer.py
│   ├── config/                                 // 针对config模块的测试。
│   │   ├── __init__.py
│   │   ├── test4env.py
│   │   └── test4model&env.py
│   ├── extract/                                // 针对extract模块的测试。
│   │   ├── __init__.py
│   │   └── test4jar.py
│   ├── generate/                               // 针对generate模块的测试。
│   │   ├── __init__.py
│   │   ├── test4escape_in_json.py
│   │   ├── test4extract&import.py
│   │   ├── test4formatter.py
│   │   ├── test4generate_func_table.py
│   │   ├── test4handle_dependency_in_class.py
│   │   ├── test4jsonload.py
│   │   ├── test4postprocess.py
│   │   ├── test4process_test_content.py
│   │   ├── test4resolve_type_identifier.py
│   │   ├── test4symbolTable.py
│   │   └── test4symbol_table_generate.py
│   ├── utils/                                  // 针对utils模块的测试。
│   │   ├── __init__.py
│   │   ├── test4calcToken.py
│   │   ├── test4chat.py
│   │   ├── test4defects4jcompile.py
│   │   ├── test4findjavafiles.py
│   │   ├── test4get_compiler_id.py
│   │   ├── test4pomFinder.py
│   │   ├── test4pomModify.py
│   │   ├── test4thinking.py
│   │   └── test4treesitter.py
│   └── __init__.py
├── utils/                                      // 通用工具函数和客户端。
│   ├── __init__.py
│   ├── chat_client.py                          // OpenAI 规范的LLM请求交互封装。
│   ├── parse_utils.py                          // tree-sitter 代码分析常用函数封装。
│   ├── filter_rules.py                         // 过滤运行错误的关键词规则库
│   └── utils.py                                // 通用公共函数合集。
│
├── .env                                        // 被测项目环境配置文件
├── readme.md                                   // 项目说明文档。
└── requirements.txt                            // bugWhisper项目依赖列表。                     
```


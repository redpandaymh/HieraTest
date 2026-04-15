import json
import os
import sys
import logging
from concurrent.futures import ThreadPoolExecutor

# 解决 PYTHONPATH 找不到包的问题
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 引入项目现有的工具类
from utils.utils import find_java_files, get_tree_root, create_directory
from utils.parse_utils import (
    TreeSitterJava,
    extract_java_package_name,
    find_nodes_by_type,
    find_node_in_children,
    get_node_text,
    extract_class_name
)

# 假设这些日志和环境配置可能在您的项目中定义了，这里做一下基础 fallback
try:
    from config.configs import BUILDING_DATA_AND_LOG_STORE_PATH
except ImportError:
    BUILDING_DATA_AND_LOG_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "build_data")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("symbol_table_generator")

class SymbolTableGenerator:
    def __init__(self, target_project_path: str):
        self.target_project_path = target_project_path
        self.symbol_table = {}

    def extract_method_info(self, method_node) -> dict:
        """从 Method_declaration 节点中提取方法的信息"""
        info = {
            "name": "",
            "return_type": "",
            "parameters": [],
            "modifiers": []
        }
        
        # 1. 提取方法名
        for child in method_node.children:
            if child.type == TreeSitterJava.identifier:
                info["name"] = get_node_text(child)
                break
                
        # 2. 提取修饰符 (如 public, static 等)
        modifiers_node = find_node_in_children(method_node, target_type=TreeSitterJava.modifiers)
        if modifiers_node:
            info["modifiers"] = [get_node_text(n) for n in modifiers_node.children]
            
        # 3. 提取返回值
        type_nodes = [n for n in method_node.children if n.type.endswith('type') or n.type == TreeSitterJava.type_identifier]
        if type_nodes:
            info["return_type"] = get_node_text(type_nodes[0])

        # 4. 提取参数
        params_node = find_node_in_children(method_node, target_type=TreeSitterJava.formal_parameters)
        if params_node:
            for param in params_node.children:
                if param.type == TreeSitterJava.formal_parameter:
                    # 简化的参数提取逻辑
                    info["parameters"].append(get_node_text(param))

        signature = f"{info['name']}({', '.join([p.split(' ')[0] if ' ' in p else p for p in info['parameters']])})"
        return signature, info

    def process_file(self, file_path: str):
        """解析单个 Java 文件，提取类、字段、方法并加入符号表"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            root_node = get_tree_root(content)
            if not root_node:
                return

            # 获取包名
            package_name = extract_java_package_name(root_node)

            # 获取类名
            classes = find_nodes_by_type(root_node, target_type=TreeSitterJava.class_declaration)
            for cls_node in classes:
                class_name = extract_class_name(cls_node)
                if not class_name:
                    continue
                
                fqdn = f"{package_name}.{class_name}" if package_name else class_name
                
                class_info = {
                    "class_name": class_name,
                    "package_name": package_name,
                    "fields": [],
                    "methods": {}
                }

                # 提取 Fields
                if class_body := find_node_in_children(cls_node, target_type=TreeSitterJava.class_body):
                    fields = find_nodes_by_type(class_body, target_type=TreeSitterJava.field_declaration)
                    for field in fields:
                        class_info["fields"].append(get_node_text(field))
                        
                    # 提取 Methods
                    methods = find_nodes_by_type(class_body, target_type=TreeSitterJava.method_declaration)
                    for method in methods:
                        signature, minfo = self.extract_method_info(method)
                        class_info["methods"][signature] = minfo

                self.symbol_table[fqdn] = class_info
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {e}")

    def generate(self) -> dict:
        """主执行流程：找出所有文件，多线程解析，并返回符号表字典"""
        java_files = find_java_files(self.target_project_path)
        logger.info(f"Target Project: {self.target_project_path}")
        logger.info(f"Found {len(java_files)} Java files for symbol table generation.")

        # 使用多线程进行 AST 解析以加速
        with ThreadPoolExecutor(max_workers=8) as executor:
            executor.map(self.process_file, java_files)
        
        return self.symbol_table

    def save_to_json(self, project_name: str):
        """保存至约定目录"""
        create_directory(BUILDING_DATA_AND_LOG_STORE_PATH)
        output_file = os.path.join(BUILDING_DATA_AND_LOG_STORE_PATH, f"{project_name}_symbol_table.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.symbol_table, f, indent=4, ensure_ascii=False)
            
        logger.info(f"Symbol table generated successfully! Saved to: {output_file}")


def main():
    # 演示：对当前某个被定位项目进行构建符号表 (示例项目路径可修改)
    target_project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "HieraTest-Bench", "ExampleProject"))
    if not os.path.exists(target_project_dir):
        # Fallback 到 HieraTest 本身以做测试运行
        target_project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
    generator = SymbolTableGenerator(target_project_path=target_project_dir)
    generator.generate()
    generator.save_to_json("demo_project")


if __name__ == '__main__':
    main()
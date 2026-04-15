import logging
from enum import Enum, auto, unique
from typing import Any, Optional, List

from tree_sitter import Node
from utils.utils import get_tree_root

# ------------ 常量 ---------------

possibleBasicIdentifierType = ["type_identifier", "boolean_type",
                               "integral_type", "floating_point_type"]
possibleIdentifierTypes = possibleBasicIdentifierType + ["array_type", "generic_type", "scoped_type_identifier"]
possibleReturnTypes = possibleIdentifierTypes + ["void_type"]

possibleModifiers = ["public", "private", "protected", "static", "final",
                     "abstract", "synchronized", "volatile", "transient", "native", "strictfp"]


@unique
class TreeSitterJava(str, Enum):
    def _generate_next_value_(name, *args):
        return name

    # 顶层结构声明
    package_declaration = auto()  # 包声明[4](@ref)
    import_declaration = auto()  # 导入声明[4](@ref)
    class_declaration = auto()  # 类声明[4,6](@ref)
    interface_declaration = auto()  # 接口声明[4](@ref)
    enum_declaration = auto()  # 枚举声明[4](@ref)

    # 类体结构
    class_body = auto()  # 类体[4](@ref)
    interface_body = auto()  # 接口体[4](@ref)
    enum_body = auto()  # 枚举体[4](@ref)
    enum_body_declarations = auto()  # 枚举内部声明[4](@ref)

    # 接口结构
    interface = auto()

    # 构造函数
    constructor_body = auto()

    # 成员声明
    method_declaration = auto()  # 方法声明[6,7](@ref)
    block = auto()  # 块结构
    local_variable_declaration = auto()
    constructor_declaration = auto()  # 构造函数[6,7](@ref)
    field_declaration = auto()  # 字段声明[6,7](@ref)
    constant_declaration = auto()  # 常量声明（接口）[4](@ref)
    enum_constant = auto()  # 枚举常量[4](@ref)
    method_invocation = auto() # 函数调用
    object_creation_expression = auto() # 构造函数调用

    # 继承和实现的扩展关系
    superclass = auto()  # 父类继承[4,6](@ref)
    super_interfaces = auto()  # 父接口实现[4](@ref)
    extends_interfaces = auto()  # 接口继承[4](@ref)
    type_parameters = auto()  # 泛型参数[4,6](@ref)
    extends = auto()
    implements = auto()

    # 参数与变量
    identifier = auto()
    formal_parameters = auto()  # 参数列表[4](@ref)
    formal_parameter = auto()  # 单个参数[4](@ref)
    spread_parameter = auto()  # 可变参数[4](@ref)
    variable_declarator = auto()  # 变量声明器[1,4](@ref)
    argument_list = auto()  # 方法调用参数列表[4](@ref)
    expression_statement = auto()  # 表达式
    string_literal = auto()  # 字符串
    string_fragment = auto()
    field_access = auto()

    # 类型标识与泛型相关
    type_identifier = auto()  # 类型标识符[4](@ref)
    scoped_identifier = auto()  # 带作用域的标识符[4](@ref)
    generic_type = auto()  # 泛型类型[4](@ref)
    type_arguments = auto()  # 泛型实参[4](@ref)
    array_type = auto()  # 数组类型[4](@ref)
    dimensions = auto()  # 数组维度[4](@ref)
    type_list = auto()  # 类型列表[4](@ref)
    void_type = auto()
    wildcard = auto()
    scoped_type_identifier = auto()
    annotated_type = auto()  # 带注解修饰的修饰符

    # 注解与修饰符
    modifiers = auto()  # 访问修饰符[6,7](@ref)
    marker_annotation = auto()  # 标记注解[4](@ref)
    annotation = auto()  # 普通注解[4](@ref)

    # 特殊语法结构
    ERROR = auto()

    # 其他语法元素
    assignment_expression = auto()  # 赋值表达式[4](@ref)
    block_comment = auto()  # 块注释[4](@ref)
    line_comment = auto()  # 行注释
    comment = auto()


# ==============================================================================
# 复用
# ==============================================================================

def extract_modifiers(modifiers: list, modifiers_node: Node) -> None:
    """
        提取传入的modifiers节点中的修饰符和注解
        添加到传入的列表中
    :param modifiers:
    :param modifiers_node:
    :return:
    """
    for child in modifiers_node.children:
        # 修饰符，如public、private等
        if child.type in possibleModifiers:
            modifiers.append(get_node_text(child).strip())
        # 注解，如@Autowired，包含有参数的注解和无参数的注解
        elif child.type in (TreeSitterJava.annotation, TreeSitterJava.marker_annotation):
            modifiers.append(get_node_text(child).strip())


def extract_inherits_name(node: Node) -> List:
    """
        目前的作用是从extends或者implement语句中提取出继承或者实现的类或者接口
        对于名称来说，要么直接就是type_identifier，要么就是泛型类或接口，那么
        应该是提取完整的generic_type
    :param node:
    :return:
    """

    inherits_name = []
    # 只针对extends_interfaces，也就是interface的extends
    if type_list := find_node_by_type(node, TreeSitterJava.type_list):
        # 如果存在泛型，则寻找泛型
        if generic_types := find_nodes_in_children(type_list, TreeSitterJava.generic_type):
            for item in generic_types:
                inherits_name.append(get_node_text(item))

        # 要不然就是常规的名称
        type_identifiers = find_nodes_in_children(type_list, TreeSitterJava.type_identifier)
        if type_identifiers:
            for item in type_identifiers:
                inherits_name.append(get_node_text(item))
    # 针对于类的extends
    else:
        for child in node.children:
            if child.type != TreeSitterJava.extends:
                inherits_name.append(get_node_text(child))
        # 暂时先忽略代码中可能存在的 scope修饰符
        # scoped_identifier = find_node_by_type(node, "scoped_identifier")
        # if scoped_identifier:
        #     return get_node_text(scoped_identifier).replace(".", "_")
    return inherits_name


def extract_type_identifier_str_list(node: Node) -> List:
    type_identifier_str_list = []
    if type_identifier_list := find_nodes_by_type(node=node, target_type=TreeSitterJava.type_identifier):
        for type_identifier in type_identifier_list:
            type_identifier_str_list.append(get_node_text(type_identifier))
    return type_identifier_str_list


def extract_import_str_list(node: Node) -> list:
    """
        给定tree-sitter节点，从节点中找到所有的import节点并提取text，
        以列表的形式返回所有的import节点text信息
    :param node:
    :return:
    """
    import_list = []
    if import_nodes := find_nodes_by_type(node, TreeSitterJava.import_declaration):
        for import_node in import_nodes:
            scoped_identifier = find_node_in_children(import_node, TreeSitterJava.scoped_identifier)
            if scoped_identifier:
                import_list.append(get_node_text(import_node))
    return import_list


def extract_import_str_list_scoped(node: Node) -> list:
    """
        给定tree-sitter节点，从节点中找到所有的import节点并提取text，
        以列表的形式返回所有的import节点text信息,不包含 import
    :param node:
    :return:
    """
    import_list = []
    if import_node_list := find_nodes_by_type(node, TreeSitterJava.import_declaration):
        for import_node in import_node_list:
            if scoped_identifier:= find_node_in_children(import_node, TreeSitterJava.scoped_identifier):
                import_list.append(process_import_string_sequential(get_node_text(import_node)))
    return import_list



def process_import_string_sequential(import_str) -> str:
    """
    按照指定逻辑处理 import 字符串：
    1. 如果以 'import ' 开头，则移除 'import '。
    2. 如果以 ';' 结尾，则移除 ';'.
    3. 去除所有剩余的空白字符。

    Args:
      import_str: 待处理的 import 字符串，例如 "import org.slf4j.Logger;"

    Returns:
      处理后的字符串，例如 "org.slf4j.Logger"。
    """
    processed_str = import_str

    # 1. 如果以 "import " 开头，则移除 "import "
    if processed_str.startswith("import "):
        processed_str = processed_str[len("import "):]

    # 2. 如果以分号结尾，则移除分号
    if processed_str.endswith(';'):
        processed_str = processed_str[:-1]

    # 3. 去除所有剩余的空白字符 (包括行首、行尾、中间的)
    # 使用 replace(' ', '') 来移除所有空格
    # 如果也想移除制表符、换行符等，可以使用 re.sub('\s+', '', processed_str)
    processed_str = processed_str.replace(' ', '')

    return processed_str

def extract_java_package_declare(root_node: Node) -> str:
    package_declare = ""
    package_node = find_node_by_type(root_node, TreeSitterJava.package_declaration)
    if package_node:
        package_declare = get_node_text(package_node)
    return package_declare


def extract_method_nodes(root_node: Node) -> List[Node]:
    """
        考虑两种可能的情况，第一种是传进来一个子节点就包含class的node，第二个是传进来一个子节点直接包含method的node
    :param root_node:
    :return:
    """
    method_node_list = []
    class_declaration = find_node_in_children(node=root_node, target_type=TreeSitterJava.class_declaration)
    if class_declaration:
        class_body = find_node_in_children(node=class_declaration, target_type=TreeSitterJava.class_body)
        if class_body:
            method_node_list = find_nodes_in_children(node=class_body, target_type=TreeSitterJava.method_declaration)
    else:
        method_node_list = find_nodes_in_children(node=root_node, target_type=TreeSitterJava.method_declaration)
    return method_node_list


def extract_method_name(root_node: Node) -> str:
    """
        仅考虑传入的为单纯的method_declaration
        从method_declaration中提取method_name
    :param root_node:
    :return:
    """
    method_name = ""
    method_name_node = extract_method_name_node(root_node=root_node)
    if method_name_node:
        method_name = get_node_text(method_name_node)
    return method_name


def extract_method_name_node(root_node: Node) -> Optional[Node]:
    """
        仅考虑传入的为单纯的method_declaration
    :param root_node:
    :return:
    """
    if root_node.type == TreeSitterJava.method_declaration:
        method_name_node = find_node_in_children(node=root_node, target_type=TreeSitterJava.identifier)
        return method_name_node
    else:
        method_declaration = find_node_in_children(node=root_node, target_type=TreeSitterJava.method_declaration)
        if method_declaration:
            method_name_node = find_node_in_children(node=method_declaration, target_type=TreeSitterJava.identifier)
            return method_name_node
        else:
            return None


def extract_block_comment_nodes_in_children(root_node: Node) -> list[Node]:
    """
        提取指定节点下的所有的块注释
    :param root_node:
    :return:
    """
    return find_nodes_in_children(node=root_node, target_type=TreeSitterJava.block_comment)


def extract_class_name(node: Node) -> str:
    """
    传入一个节点，从该节点的子节点中提取出类的名称
    仅提取第一个类的名称
    :param node:
    :return: 类名称字符串
    """
    class_name = ""
    class_declaration = find_node_by_type(node=node, target_type=TreeSitterJava.class_declaration)
    if class_declaration:
        class_name_node = find_node_in_children(node=class_declaration, target_type=TreeSitterJava.identifier)
        if class_name_node:
            class_name = get_node_text(class_name_node)
    return class_name


def extract_method_signature(node: Node) -> str:
    """
    认定传入的内容只能是method_declaration
    如果不是，那么就从中寻找method_declaration

    :param node:
    :return: 传入函数节点中函数签名的字符串
    """
    method_name = ""
    if node.type != TreeSitterJava.method_declaration:
        node = find_node_by_type(node=node, target_type=TreeSitterJava.method_declaration)
    if node.type == TreeSitterJava.method_declaration:
        signature_list = [find_node_in_children(node=node, target_type=TreeSitterJava.identifier),
                          find_node_in_children(node=node, target_type=TreeSitterJava.formal_parameters)]
        signature_list = [get_node_text(element) for element in signature_list]
        method_name = ''.join(signature_list)

    return method_name


def extract_class_frame(class_content: str) -> str:
    """
    从一个完整的java class字符串中，去除
    1、除了包含@Before注解的所有函数
    2、所有的block_comment(防止与test中所保留的block_comment形成大量重复)

    :param class_content:
    :return:处理后的class框架字符串
    """
    root = get_tree_root(content=class_content)
    class_comp_str_list: list = []
    if class_node := find_node_by_type(node=root, target_type=TreeSitterJava.class_declaration):
        for class_comp in class_node.children:
            if class_comp.type not in [TreeSitterJava.class_body]:
                class_comp_str_list.append(get_node_text(class_comp))
            else:
                class_comp_body_str_list: list = []
                for class_body_comp in class_comp.children:
                    class_body_comp_str = ""
                    if class_body_comp.type == TreeSitterJava.method_declaration:
                        if modifiers_node := find_node_in_children(node=class_body_comp,
                                                                   target_type=TreeSitterJava.modifiers):
                            modifiers_text = get_node_text(modifiers_node)
                            if "@Before" in modifiers_text:
                                class_body_comp_str = get_node_text(class_body_comp)
                    elif class_body_comp.type == TreeSitterJava.block_comment:
                        continue
                    else:
                        class_body_comp_str = get_node_text(class_body_comp)
                    if class_body_comp_str:
                        class_comp_body_str_list.append(class_body_comp_str)
                class_body_str = "\n".join(class_comp_body_str_list)
                class_comp_str_list.append(class_body_str)
    class_frame_str = " ".join(class_comp_str_list)
    return class_frame_str


# ==============================================================================
# tools func
# ==============================================================================
def find_node_by_type(node: Node, target_type: str) -> Optional[Node]:
    """
    递归的查找第一个符合type条件的node
    :param node:
    :param target_type:
    :return:
    """
    for child in node.children:
        if child.type == target_type:
            return child
        result = find_node_by_type(child, target_type)
        if result:
            return result
    return None


def find_node_in_children(node: Node, target_type: str) -> Optional[Node]:
    """
    从节点中找到第一个类型符合的子节点并返回
    如果未找到则返回none
    仅单层寻找（不考虑子节点的子节点等）
    :param node:
    :param target_type:
    :return:
    """
    for child in node.children:
        if child.type == target_type:
            return child
    return None


def find_nodes_in_children(node: Node, target_type: str) -> List[Node]:
    """
    从节点中找到所有符合类型的子节点并返回
    如果未找到则返回none
    仅单层寻找（不考虑子节点的子节点等）
    :param node:
    :param target_type:
    :return:
    """

    nodes = []
    for child in node.children:
        if child.type == target_type:
            nodes.append(child)
    return nodes


def find_nodes_by_type(node: Node, target_type: str) -> list:
    results = []
    if node.type == target_type:
        results.append(node)
    for child in node.children:
        results.extend(find_nodes_by_type(child, target_type))
    return results


def get_node_text(node: Node) -> str:
    """安全获取语法树节点的文本内容

    Args:
        node: 语法树节点对象,需包含text属性

    Returns:
        解码后的文本字符串，解码失败返回空字符串

    Raises:
        AttributeError: 当节点缺少text属性时抛出
    """
    raw_data = None
    try:
        # 优先检查节点是否包含text属性
        raw_data = node.text

        # 处理可能的空值情况
        if not raw_data:
            logging.warning("节点文本内容为空")
            return ""

        # 显式指定解码参数防止隐式错误
        return raw_data.decode("utf-8", errors="replace")

    except AttributeError as ae:
        logging.error("节点缺少text属性", exc_info=True)
        return ""
        # raise ValueError("无效的节点结构") from ae

    except UnicodeDecodeError as ude:
        logging.warning(f"解码异常：{str(ude)}")
        return ""

    except Exception as e:
        logging.exception("未知错误类型")
        return ""


def get_node_scope(node: Node) -> list[int]:
    """
    从给定的tree-sitter Node中获取指定节点的起始行和结束行
    :param node: 指定节点
    :return: 起始行和结束行形成的整型list
    """
    try:
        start_line = node.start_point.row
        end_line = node.end_point.row
        return [start_line, end_line]
    except AttributeError as ae:
        logging.error("节点缺少text属性", exc_info=True)
        raise ValueError("无效的节点结构") from ae

    except UnicodeDecodeError as ude:
        logging.warning(f"解码异常：{str(ude)}")
        return []

    except Exception as e:
        logging.exception("未知错误类型")
        return []


def extract_java_package_name(root_node: Node) -> str:
    """
        传入节点，找到并返回 java package的名称字符串
    :param root_node:
    :return:
    """
    # 提取包名
    package_name = ""
    if package_node := find_node_by_type(node=root_node, target_type=TreeSitterJava.package_declaration):
        if scoped_identifier_node := find_node_in_children(node=package_node,
                                                           target_type=TreeSitterJava.scoped_identifier):
            package_name = get_node_text(scoped_identifier_node)
    return package_name


def extract_initial_value(node: Node) -> Any:
    initializer = find_node_by_type(node, target_type=TreeSitterJava.assignment_expression)
    if initializer:
        return get_node_text(initializer.children[-1])
    return None


def check_class_existence(content: str) -> bool:
    root = get_tree_root(content=content)
    return root is not None and find_node_by_type(node=root, target_type=TreeSitterJava.class_declaration) is not None


# ==============================================================================
# Code replication related functions
# ==============================================================================

def generate_import_stmt(fqdn: str, is_static: bool, is_asterisk: bool) -> str:
    black_space = " "
    import_stmt = "import" + black_space
    if is_static:
        import_stmt += ("static" + black_space)
    import_stmt += fqdn
    if is_asterisk:
        import_stmt += ".*"
    import_stmt += ";"
    return import_stmt

    # if is_static:
    #     return "import" + " " + "static" + " " + fqdn + ";"
    # else:
    #     return "import" + " " + fqdn + ";"


def generate_package_stmt(pkg_name: str) -> str:
    return "package" + " " + pkg_name + ";"


def edit_str_in_byte(new_str: str, start_byte: int, end_byte: int, source_str: str) -> str:
    """
    以字节的方式修改原始字符串中的内容
    :return: 修改后的代码字符串
    """
    source_str_byte = bytearray(source_str.encode('utf-8'))
    source_str_byte[start_byte:end_byte] = new_str.encode()
    modified_str = bytes(source_str_byte).decode('utf-8')

    return modified_str


def repair_imports(code: str, import_list: list) -> str:
    """
    将指定的import信息加入到原始的java代码当中去
    :param import_list: 额外添加的import信息
    :param code: 原始java代码
    :return: 添加指定import之后的代码
    """
    test_import_info = \
        """
        import org.mockito.*;
        import org.junit.jupiter.api.*;
        import static org.mockito.Mockito.*;
        import static org.junit.jupiter.api.Assertions.*;
        import org.junit.jupiter.api.extension.ExtendWith;
        import org.mockito.junit.jupiter.MockitoExtension;
        """
    add_import_str = "\n".join(import_list)
    all_import_str = test_import_info + "\n" + add_import_str

    code = code.replace("\nimport ", all_import_str + "\nimport ", 1)
    return code


def repair_package(code: str, package_name: str) -> str:
    """
    设置package名称为指定内容
    :param code:
    :param package_name:
    :return:
    """
    root = get_tree_root(content=code)
    modified_code = code
    if package_declaration_node := find_node_by_type(node=root, target_type=TreeSitterJava.package_declaration):
        scoped_identifier_node = find_node_in_children(node=package_declaration_node,
                                                       target_type=TreeSitterJava.scoped_identifier)
        modified_code = edit_str_in_byte(new_str=package_name,
                                         start_byte=scoped_identifier_node.start_byte,
                                         end_byte=scoped_identifier_node.end_byte,
                                         source_str=code)
    # 传入的代码中不存在package_declaration
    else:
        modified_code = generate_package_stmt(pkg_name=package_name) + modified_code
    return modified_code


def repair_class_name(code: str, class_name: str) -> str:
    """
    设置class名称为指定内容
    :param code:
    :param class_name:
    :return:
    """
    root = get_tree_root(content=code)
    modified_code = code
    if class_declaration_node := find_node_by_type(node=root, target_type=TreeSitterJava.class_declaration):
        class_name_node = find_node_in_children(node=class_declaration_node, target_type=TreeSitterJava.identifier)
        modified_code = edit_str_in_byte(new_str=class_name,
                                         start_byte=class_name_node.start_byte,
                                         end_byte=class_name_node.end_byte,
                                         source_str=code)
    return modified_code

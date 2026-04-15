import ast
import gc

import networkx as nx
from itertools import islice


class JAVA_CFG():
    def __init__(self):
        self.finlineno = []
        self.firstlineno = 1
        self.loopflag = 0
        self.clean_code = ''

        self.func_name = dict()
        self.G = nx.DiGraph()
        self.DG = nx.DiGraph()
        self.circle = []
        self.dece_node = []

    def k_shortest_paths(self, G, source, target, k, weight=None):
        return list(islice(nx.shortest_simple_paths(G, source, target, weight=weight), k))

    # 单次贪心路径搜索
    def greedy_path_with_f(self, G, start, goal, f_subset, covered_f):
        current_node = start
        path = [current_node]
        new_covered_f = set()
    
        while current_node != goal:
            # 获取当前节点的邻居
            neighbors = list(G.neighbors(current_node))
    
            # 如果没有邻居，说明无法继续，算法失败
            if not neighbors:
                # print("无法找到路径")
                break
                # return None, new_covered_f
    
            # 选择下一步：优先覆盖 f 集合中的节点，同时尽量选择较短路径的节点
            next_node = min(neighbors, key=lambda neighbor: (
                G[current_node][neighbor]['weight'],  # 优先选择权重较小的边
                -1 if neighbor in f_subset and neighbor not in covered_f and neighbor not in new_covered_f else 0
            # 其次选择未覆盖的 f 集合中的节点
            ))
    
            # 更新当前节点，并加入路径
            current_node = next_node
            path.append(current_node)
    
            # 如果下一个节点在 f 集合中，且尚未被覆盖，将其加入新覆盖的集合
            if current_node in f_subset and current_node not in covered_f:
                new_covered_f.add(current_node)
    
        return path, new_covered_f

    # def greedy_path_with_f(self, G, start, goal, f_subset, covered_f):
    #     current_node = start
    #     new_covered_f = set()
    #     max_steps = 1000  # 最大步数限制
    #     step_count = 0

    #     # 使用位向量优化集合操作
    #     node_list = list(G.nodes)
    #     f_bitvector = [1 if node in f_subset else 0 for node in node_list]
    #     covered_bitvector = [1 if node in covered_f else 0 for node in node_list]
    #     new_covered_bitvector = [0] * len(node_list)

    #     path = []
    #     while current_node != goal and step_count < max_steps:
    #         step_count += 1
    #         path.append(current_node)
    #         neighbors = G.neighbors(current_node)  # 直接使用迭代器

    #         # 动态计算邻居的最小代价节点
    #         next_node = None
    #         min_cost = float('inf')
    #         for neighbor in neighbors:
    #             weight = G[current_node][neighbor]['weight']
    #             # 检查是否在f_subset且未覆盖
    #             is_f_covered = f_bitvector[node_list.index(neighbor)] and not covered_bitvector[
    #                 node_list.index(neighbor)]
    #             cost = weight - (1000 if is_f_covered else 0)  # 未覆盖节点优先级更高
    #             if cost < min_cost:
    #                 min_cost = cost
    #                 next_node = neighbor

    #         if next_node is None:
    #             break

    #         current_node = next_node
    #         # 更新覆盖状态
    #         idx = node_list.index(current_node)
    #         if f_bitvector[idx] and not covered_bitvector[idx]:
    #             new_covered_bitvector[idx] = 1
    #             new_covered_f.add(current_node)

    #         # 每100 步清理一次内存
    #         if step_count % 100 == 0:
    #             gc.collect()

    #     return path, new_covered_f

    def extract_allpath(self, f_subset, condition_nodes):
        all_paths = []
        self.finlineno = list(set(self.finlineno))
        self.finlineno.sort(reverse=False)  # sort from the small to big
        covered_nodes = set()
        # Extract the CFG paths with buggy statements
        covered_f = set()  # 存储已经覆盖的 f 集合中的节点
        for fno in self.finlineno:
            # path只包含一些 buggy statements，需要重新选择一些 buggy statements
            num_f_subset = len(f_subset)
            while covered_f != set(f_subset) and (num_f_subset > 0):
                num_f_subset -= 1
                # 调用贪心算法
                path, new_covered = self.greedy_path_with_f(self.G, self.firstlineno, fno, f_subset, covered_f)
                if path is not None:
                    # 更新已覆盖的节点和总路径
                    covered_f.update(new_covered)
                    all_paths.append(path)
                else:
                    break
                if len(all_paths) > 3:
                    break
        all_paths = [list(t) for t in set(tuple(lst) for lst in all_paths)]  # pre_process the CFG paths with buggy
        # statements
        # Extract the CFG paths with condition statements
        for node in all_paths:
            covered_nodes.update(node)
        uncovered_condition_nodes = set(condition_nodes) - covered_nodes
        if len(uncovered_condition_nodes) > 0:
            covered_f = set()
            condition_all_paths = []
            for fno in self.finlineno:
                num_condition_nodes = len(uncovered_condition_nodes)
                while covered_f != set(uncovered_condition_nodes) and (num_condition_nodes > 0):
                    num_condition_nodes -= 1
                    # 调用贪心算法
                    path, new_covered = self.greedy_path_with_f(self.G, self.firstlineno, fno,
                                                                uncovered_condition_nodes, covered_f)
                    if path is not None:
                        # 更新已覆盖的节点和总路径
                        covered_f.update(new_covered)
                        condition_all_paths.append(path)
                    else:
                        break
                    if len(condition_all_paths) > 3:
                        break
            if len(condition_all_paths) > 0:
                condition_all_paths = [list(t) for t in set(tuple(lst) for lst in condition_all_paths)]
                all_paths.extend(condition_all_paths)

        # Extract the CFG paths with uncovered statement nodes
        for path in all_paths:
            covered_nodes.update(path)
            for i in range(0, len(path) - 1):
                n1 = path[i]
                n2 = path[i + 1]
                if len(self.G.adj[n1]) > 1:
                    self.G[n1][n2]['weight'] = 100
        uncovered_condition_nodes = set(condition_nodes) - covered_nodes
        coverage = -1
        path3 = []
        for fno in self.finlineno:
            if nx.has_path(self.G, self.firstlineno, fno):
                paths = self.k_shortest_paths(self.G, self.firstlineno, fno, 100)
                for path in paths:
                    if len(set(path) & uncovered_condition_nodes) > coverage:
                        path3 = path
                        coverage = len(set(path3) & uncovered_condition_nodes)
        condition_node_uncover = uncovered_condition_nodes - set(path3)
        all_paths.append(path3)
        num_path = len(all_paths)
        all_nodes = set(self.G.nodes())
        node_cover = set()
        for path in all_paths:
            for node in path:
                node_cover.add(node)
        ratio = len(node_cover) / len(all_nodes)
        condition_node_cover = set(condition_nodes) & node_cover
        if len(condition_nodes) == 0:
            condition_ratio = 0
        else:
            condition_ratio = len(condition_node_cover) / len(condition_nodes)
        condition_node_uncover = set(condition_nodes) - condition_node_cover
        while condition_ratio < 0.75 and condition_ratio != 0 and len(all_paths) < 20:
            # Extract the CFG paths with uncovered statement nodes
            for path in all_paths:
                covered_nodes.update(path)
                for i in range(0, len(path) - 1):
                    n1 = path[i]
                    n2 = path[i + 1]
                    if len(self.G.adj[n1]) > 1:
                        self.G[n1][n2]['weight'] = 100
            uncovered_condition_nodes = set(condition_nodes) - covered_nodes
            coverage = -1
            path3 = []
            for fno in self.finlineno:
                if nx.has_path(self.G, self.firstlineno, fno):
                    paths = self.k_shortest_paths(self.G, self.firstlineno, fno, 100)
                    for path in paths:
                        if len(set(path) & uncovered_condition_nodes) > coverage:
                            path3 = path
                            coverage = len(set(path3) & uncovered_condition_nodes)
            condition_node_uncover = uncovered_condition_nodes - set(path3)
            all_paths.append(path3)
            num_path = len(all_paths)
            all_nodes = set(self.G.nodes())
            node_cover = set()
            for path in all_paths:
                for node in path:
                    node_cover.add(node)
            ratio = len(node_cover) / len(all_nodes)
            condition_node_cover = set(condition_nodes) & node_cover
            if len(condition_nodes) == 0:
                condition_ratio = 0
            else:
                condition_ratio = len(condition_node_cover) / len(condition_nodes)
            condition_node_uncover = set(condition_nodes) - condition_node_cover
        all_paths = [list(t) for t in
                     set(tuple(lst) for lst in all_paths)]  # pre_process the CFG paths with buggy statements
        return num_path, all_paths, ratio, condition_ratio, condition_node_uncover

    def run(self, root):
        # self.visit(root)
        self.clean_code = root
        self.finlineno.append(root.end_point[0] + 1)
        self.ast_visit(root)

    def parse_ast_file(self, ast_code):
        self.run(ast_code)
        return ast_code

    def parse_ast(self, source_ast):
        self.run(source_ast)
        return source_ast

    def get_source(self, fn):
        ''' Return the entire contents of the file whose name is given.
            Almost most entirely copied from stc. '''
        try:
            f = open(fn, 'r')
            s = f.read()
            f.close()
            return s
        except IOError:
            return ''

    def ast_visit(self, node):
        method = getattr(self, "visit_" + node.type)
        return method(node)

    def visit_program(self, node):
        # self.finlineno.append(node.end_point[0] + 1)
        self.finlineno.append(node.children[-1].end_point[0] + 1)
        for index, z in enumerate(node.children):
            for i in range(z.start_point[0] + 1, z.end_point[0] + 2):
                self.G.add_node(i)
            if self.firstlineno > z.start_point[0] + 1:
                self.firstlineno = z.start_point[0] + 1
            if z.type == "block":
                if index == len(node.children) - 1:
                    self.finlineno.append(z.end_point[0] + 1)
                self.ast_visit(z)
            if z.type == "local_variable_declaration":
                self.ast_visit(z)
            if z.type == "method_declaration":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_method_declaration(self, node):
        for index, z in enumerate(node.children):
            if z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_local_variable_declaration(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)

    def visit_labeled_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            self.visit_piece(z)

    def visit_method_invocation(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            self.ast_visit(z)

    def visit_translation_unit(self, node):
        self.finlineno.append(node.children[-1].end_point[0] + 1)
        # for i in range(node.start_point[0] + 1, node.end_point[0] + 2):
        #     self.G.add_edge(i, i + 1, weight=1)
        for index, z in enumerate(node.children):
            for i in range(z.start_point[0] + 1, z.end_point[0] + 2):
                self.G.add_node(i)
            if self.firstlineno > z.start_point[0] + 1:
                self.firstlineno = z.start_point[0] + 1
            if z.type == "function_definition":
                if index == len(node.children) - 1:
                    self.finlineno.append(z.end_point[0] + 1)
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_function_definition(self, node):
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_block(self, node):
        # self.G.add_edge(node.start_point[0]+1, node.end_point[0]+1)
        for index, z in enumerate(node.children):
            if z.type == "for_statement":
                self.ast_visit(z)
            elif z.type == "enhanced_for_statement":
                self.ast_visit(z)
            elif z.type == "while_statement":
                self.ast_visit(z)
            elif z.type == "do_statement":
                self.ast_visit(z)
            elif z.type == "try_with_resources_statement":
                self.ast_visit(z)
            elif z.type == "assert_statement":
                self.ast_visit(z)
            elif z.type == "switch_expression":
                self.ast_visit(z)
            elif z.type == "case_statement":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.ast_visit(z)
            elif z.type == "switch_block":
                self.ast_visit(z)
            elif z.type == "switch_block_statement_group":
                self.ast_visit(z)
            elif z.type == "continue_statement":
                self.ast_visit(z)
            elif z.type == "try_statement":
                self.ast_visit(z)
            elif z.type == "throw_statement":
                self.ast_visit(z)
            elif z.type == "if_statement":
                self.ast_visit(z)
            elif z.type == "synchronized_statement":
                self.ast_visit(z)
            elif z.type == "expression_statement":
                self.ast_visit(z)
            elif z.type == "local_variable_declaration":
                self.ast_visit(z)
            elif z.type == "labeled_statement":
                self.ast_visit(z)
            elif z.type == "return_statement":
                self.ast_visit(z)
            elif z.type == "block":
                self.ast_visit(z)
            elif z.type == "parenthesized_expression":
                self.ast_visit(z)
            elif z.type == "ERROR":
                self.ast_visit(z)
            elif z.type == "break_statement":
                self.G.add_edge(z.start_point[0] + 1, node.start_point[0] + 1, weight=1)
                self.ast_visit(z)
            elif z.type == "class_declaration":
                self.ast_visit(z)
            elif z.type == "declaration":
                self.ast_visit(z)
            elif z.type == "method_declaration":
                self.ast_visit(z)
            elif z.type == "}":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == "{":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == ";":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            else:
                self.visit_piece(z)
        if len(node.children) > 0 and node.children[0].type == "{":
            self.G.add_edge(node.children[0].start_point[0] + 1, node.children[0].start_point[0] + 2, weight=1)
        if len(node.children) > 0 and node.children[-1].type == "}":
            self.G.add_edge(node.children[-1].start_point[0], node.children[-1].start_point[0] + 1, weight=1)

    def visit_piece(self, node):
        # self.G.add_edge(node.start_point[0]+1, node.end_point[0]+1)
        if node.type == "for_statement":
            self.ast_visit(node)
        elif node.type == "enhanced_for_statement":
            self.ast_visit(node)
        elif node.type == "while_statement":
            self.ast_visit(node)
        elif node.type == "do_statement":
            self.ast_visit(node)
        elif node.type == "do":
            pass
        elif node.type == "while":
            pass
        elif node.type == "try_with_resources_statement":
            self.ast_visit(node)
        elif node.type == "assert_statement":
            self.ast_visit(node)
        elif node.type == "switch_expression":
            self.ast_visit(node)
        elif node.type == "switch_block":
            self.ast_visit(node)
        elif node.type == "switch_block_statement_group":
            self.ast_visit(node)
        elif node.type == "labeled_statement":
            self.ast_visit(node)
        elif node.type == "continue_statement":
            self.ast_visit(node)
        elif node.type == "try_statement":
            self.ast_visit(node)
        elif node.type == "throw_statement":
            self.ast_visit(node)
        elif node.type == "modifiers":
            self.ast_visit(node)
        elif node.type == "throws":
            self.ast_visit(node)
        elif node.type == "if_statement":
            self.ast_visit(node)
        elif node.type == "synchronized_statement":
            self.ast_visit(node)
        elif node.type == "expression_statement":
            self.ast_visit(node)
        elif node.type == "local_variable_declaration":
            self.ast_visit(node)
        elif node.type == "parenthesized_expression":
            self.ast_visit(node)
        elif node.type == "return_statement":
            self.ast_visit(node)
        elif node.type == "ERROR":
            self.ast_visit(node)
        elif node.type == "break_statement":
            self.ast_visit(node)
        elif node.type == "class_declaration":
            self.ast_visit(node)
        elif node.type == "declaration":
            self.ast_visit(node)
        elif node.type == "method_declaration":
            self.ast_visit(node)
        elif node.type == "block":
            self.ast_visit(node)
        elif node.type == "goto_statement":
            self.ast_visit(node)
        elif node.type == "preproc_if":
            self.ast_visit(node)
        elif node.type == "preproc_params":
            self.ast_visit(node)
        elif node.type == "pointer_declarator":
            self.ast_visit(node)
        elif node.type == "preproc_ifdef":
            self.ast_visit(node)
        elif node.type == "preproc_elif":
            self.ast_visit(node)
        elif node.type == "preproc_function_def":
            self.ast_visit(node)
        elif node.type == "preproc_call":
            self.ast_visit(node)
        elif node.type == "preproc_else":
            self.ast_visit(node)
        elif node.type == "preproc_def":
            self.ast_visit(node)
        elif node.type == "proproc_include":
            self.ast_visit(node)
        elif node.type == "preproc_defined":
            self.ast_visit(node)
        elif node.type == "function_definition":
            self.ast_visit(node)
        elif node.type == "formal_parameters":
            self.ast_visit(node)
        elif node.type == "}":
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        elif node.type == "{":
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        elif node.type == ";":
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        elif node.type == "\n":
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        else:
            pass

    def visit_class_declaration(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] + 1 > node.start_point[0] + 1:
            for i in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(i, i + 1, weight=1)

    def visit_pointer_declarator(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] + 1 > node.start_point[0] + 1:
            for i in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(i, i + 1, weight=1)

    def visit_for_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.next_sibling is not None:
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.circle.append((node.start_point[0] + 1, node.end_point[0] + 1))
        self.dece_node.append(node.start_point[0] + 1)
        # add the statement of 'For condiation'
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            elif z.type == "if_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "try_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "switch_expression":
                for j in z.children:
                    if j.type == "switch_block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
                    elif j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            else:
                self.visit_piece(z)
                self.G.add_edge(z.end_point[0] + 1, node.start_point[0] + 1, weight=1)
        self.loopflag = node.end_point[0] + 1

    def visit_enhanced_for_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.next_sibling is not None:
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.circle.append((node.start_point[0] + 1, node.end_point[0] + 1))
        self.dece_node.append(node.start_point[0] + 1)
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            elif z.type == "if_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "try_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "switch_expression":
                for j in z.children:
                    if j.type == "switch_block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
                    elif j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            else:
                self.visit_piece(z)
                self.G.add_edge(z.end_point[0] + 1, node.start_point[0] + 1, weight=1)
        self.loopflag = node.end_point[0] + 1

    def visit_do_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.next_sibling is not None:  # named_child_count
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        if node.end_point[0] + 1 != self.finlineno[0]:
            self.G.add_edge(node.children[-1].end_point[0] + 1, node.end_point[0] + 2, weight=1)
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_try_with_resources_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        body_node = {}
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
                body_node['bs'] = z.start_point[0] + 1
                body_node['be'] = z.end_point[0] + 1
            elif z.type == "finally_clause":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.dece_node.append(z.start_point[0] + 1)
                body_node['fs'] = z.start_point[0] + 1
                body_node['fe'] = z.end_point[0] + 1
                self.ast_visit(z)
            elif z.type == "catch_clause":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.dece_node.append(z.start_point[0] + 1)
                body_node['cs'] = z.start_point[0] + 1
                body_node['ce'] = z.end_point[0] + 1
                self.ast_visit(z)
            else:
                self.visit_piece(z)
        if 'be' in body_node and 'cs' in body_node:
            self.G.add_edge(body_node['be'], body_node['cs'], weight=1)
            # for i in range(body_node['bs'], body_node['be']+1):
            #    self.G.add_edge(i, body_node['cs'], weight=1)
        if 'ce' in body_node and 'fs' in body_node:
            self.G.add_edge(body_node['ce'], body_node['fs'], weight=1)
            # for i in range(body_node['cs'], body_node['ce']+1):
            #    self.G.add_edge(i, body_node['fs'], weight=1)

    def visit_assert_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] + 1 > node.start_point[0] + 1:
            for i in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(i, i + 1, weight=1)
        if node.end_point[0] + 1 not in self.finlineno:
            self.finlineno.append(node.end_point[0] + 1)

    def visit_switch_expression(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.circle.append((node.start_point[0] + 1, node.end_point[0] + 1))
        if node.next_sibling is not None:  # named_child_count
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        if node.end_point[0] + 1 != self.finlineno[0]:
            self.G.add_edge(node.children[-1].end_point[0] + 1, node.end_point[0] + 2, weight=1)
        for z in node.children:
            if z.type == "switch_block":
                self.dece_node.append(z.start_point[0] + 1)
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                for i in range(len(z.children)):
                    if node.start_point[0] != z.children[i].start_point[0]:
                        self.G.add_edge(node.start_point[0] + 1, z.children[i].start_point[0] + 1, weight=1)
                self.ast_visit(z)
            elif z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_case_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            self.visit_piece(z)

    def visit_switch_block(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)

        for z in node.children:
            if z.type == "switch_block_statement_group":
                self.ast_visit(z)

    def visit_switch_block_statement_group(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            if z.type == "switch_label":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_switch_label(self, node):
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_while_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.next_sibling is not None:
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.circle.append((node.start_point[0] + 1, node.end_point[0] + 1))
        # add the statement of 'While condiation'
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            elif z.type == "if_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "try_statement":
                for j in z.children:
                    if j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == "switch_expression":
                for j in z.children:
                    if j.type == "switch_block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
                    elif j.type == "block":
                        self.G.add_edge(j.end_point[0] + 1, node.start_point[0] + 1, weight=1)
            elif z.type == 'else':
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
            else:
                self.visit_piece(z)
        self.loopflag = node.end_point[0] + 1

    def visit_goto_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_continue_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if len(self.circle) > 0:
            init_no, end_no = self.circle[-1]
            self.G.add_edge(node.start_point[0] + 1, end_no, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)

    def visit_try_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        body_node = {}
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
                body_node['bs'] = z.start_point[0] + 1
                body_node['be'] = z.end_point[0] + 1
            elif z.type == "finally_clause":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.dece_node.append(z.start_point[0] + 1)
                body_node['fs'] = z.start_point[0] + 1
                body_node['fe'] = z.end_point[0] + 1
                self.ast_visit(z)
            elif z.type == "catch_clause":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.dece_node.append(z.start_point[0] + 1)
                body_node['cs'] = z.start_point[0] + 1
                body_node['ce'] = z.end_point[0] + 1
                self.ast_visit(z)
            else:
                self.visit_piece(z)
        if 'bs' in body_node and 'cs' in body_node:
            self.G.add_edge(body_node['be'], body_node['cs'], weight=1)
            # for i in range(body_node['bs'], body_node['be']+1):
            #    self.G.add_edge(i, body_node['cs'], weight=1)
        if 'cs' in body_node and 'fs' in body_node:
            self.G.add_edge(body_node['ce'], body_node['fs'], weight=1)
            # for i in range(body_node['cs'], body_node['ce']+1):
            #    self.G.add_edge(i, body_node['fs'], weight=1)

    def visit_catch_clause(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_finally_clause(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        for z in node.children:
            if z.type == "block":
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_throw_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        for z in node.children:
            if z.type == "object_creation_expression":
                self.ast_visit(z)
        if node.end_point[0] + 1 not in self.finlineno:
            self.finlineno.append(node.end_point[0] + 1)

    def visit_object_creation_expression(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_argument_list(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_if_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.next_sibling is not None:  # named_child_count
            self.G.add_edge(node.start_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        self.dece_node.append(node.start_point[0] + 1)
        if node.end_point[0] + 1 != self.finlineno[0]:
            self.G.add_edge(node.children[-1].end_point[0] + 1, node.end_point[0] + 2, weight=1)
        for z in node.children:
            if z.type == "else":
                self.dece_node.append(z.start_point[0] + 1)
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
            elif z.type == "block":
                if node.next_sibling is not None:
                    self.G.add_edge(z.end_point[0] + 1, node.next_sibling.start_point[0] + 1, weight=1)
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_preproc_if(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            if z.type == "#if":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == "preproc_else":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.visit_piece(z)
            elif z.type == "#endif":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == "preproc_elif":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.ast_visit(z)
            else:
                self.visit_piece(z)

    def visit_preproc_elif(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            self.visit_piece(z)

    def visit_preproc_else(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            self.visit_piece(z)

    def visit_preproc_ifdef(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            if z.type == "#ifdef":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == "#endif":
                self.G.add_edge(node.start_point[0] + 1, z.start_point[0] + 1, weight=1)
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            else:
                self.visit_piece(z)

    def visit_preproc_params(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for z in node.children:
            if z.type == "#define":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
            elif z.type == "preproc_arg":
                self.G.add_edge(z.start_point[0], z.start_point[0] + 1, weight=1)
                if node.start_point[0] != node.end_point[0]:
                    for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                        self.G.add_edge(j, j + 1, weight=1)
            else:
                self.visit_piece(z)

    def visit_preproc_function_def(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_preproc_call(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_preproc_def(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_preproc_defined(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_preproc_include(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_break_statement(self, node):
        if node.start_point[0] != 0:
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.start_point[0] + 2, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for i in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(i, i + 1, weight=1)
        if len(self.circle) > 0:
            init_no, end_no = self.circle[-1]
            self.G.add_edge(node.start_point[0] + 1, end_no, weight=1)
        else:
            self.G.add_edge(node.start_point[0] + 1, node.end_point[0] + 1, weight=1)
        if node.end_point[0] + 1 == self.finlineno[-1]:
            self.finlineno.append(node.end_point[0] + 1)

    def visit_ternary_expression(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_synchronized_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        for index, z in enumerate(node.children):
            if z.type == "block":
                self.ast_visit(z)

    def visit_expression_statement(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_local_variable_declaration(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_declaration(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_return_statement(self, node):
        if node.end_point[0] == self.finlineno[0]:
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        else:
            self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
            self.G.add_edge(node.start_point[0], node.end_point[0] + 1, weight=1)
        if node.end_point[0] > node.start_point[0]:
            for i in range(node.start_point[0] + 1, node.end_point[0] + 2):
                self.G.add_edge(i, i + 1, weight=1)
        if node.end_point[0] + 1 not in self.finlineno:
            self.finlineno.append(node.end_point[0] + 1)

    def visit_ERROR(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0], node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)
        for z in node.children:
            self.visit_piece(z)

    def visit_parenthesized_expression(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0], node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_generic_type(self, node):
        pass

    def visit_identifier(self, node):
        pass

    def visit_if(self, node):
        pass

    def visit_for(self, node):
        pass

    def visit_binary_expression(self, node):
        pass

    def visit_modifiers(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_void_type(self, node):
        pass

    def visit_formal_parameters(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)

    def visit_throws(self, node):
        self.G.add_edge(node.start_point[0], node.start_point[0] + 1, weight=1)
        if node.start_point[0] != node.end_point[0]:
            for j in range(node.start_point[0] + 1, node.end_point[0] + 1):
                self.G.add_edge(j, j + 1, weight=1)

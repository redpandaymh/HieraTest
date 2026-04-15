import pandas as pd
import javalang
from tree_sitter import Language, Parser
LANGUAGE = Language('../parser/my-languages.so', 'java')
parser = Parser()
parser.set_language(LANGUAGE)


def dfs(root_node):
    error_type = 'no'
    if (len(root_node.children)==0 or root_node.type=='string'):
        return error_type
    if root_node.type == 'ERROR':
        return 'yes'
    for child in root_node.children:
        error_type = dfs(child)
        if error_type == 'yes':
            return 'yes'
    return 'no'

df = pd.read_csv("../result/chatgpt35/chatgpt3.5_constraints_generate_processed.csv")
data = df.to_dict("records")
# print(type(data), data[0], type(data[0]), len(data))
print(len(data))
idx = 0
idx_1 = 0
for item in data:
    try:
        test_code = item['generated_test_process']     # generated_test_process, generated_test
        src_tree = parser.parse(bytes(test_code, 'utf8'))
        root_node = src_tree.root_node
        label = dfs(root_node)
        if label == 'yes':
            idx += 1
    except Exception as e:
        print(e)
        continue

rate = 1-float(idx/len(data))
print(idx, rate, (len(data)-idx))
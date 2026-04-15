import re

def remove_prefix(s: str) -> str:
    """
    从字符串的开头移除 '[javac]' 或 '[exec]' 前缀（及其后的一个空格）。

    Args:
        s: 输入的字符串。

    Returns:
        处理后的字符串，如果存在前缀则移除，否则返回原字符串。
    """
    stripped_s = s.strip() # 先处理字符串首尾空白

    if stripped_s.startswith('[javac]'):
        # 找到 '[javac]' 的结束位置，通常是 ']' 之后
        # 假设前缀后面紧跟着一个空格，例如 "[javac] message"
        # 如果前缀后没有空格，或者有多个空格，lstrip() 会处理
        try:
            # 找到 ']' 的索引，然后加1，确保跳过 ']'
            end_of_prefix_index = stripped_s.find(']') + 1
            # 从该索引开始，去除后面的所有空白字符
            return stripped_s[end_of_prefix_index:].lstrip()
        except ValueError: # 如果没有找到 ']', 理论上不应该发生，但以防万一
            return s # 返回原字符串

    elif stripped_s.startswith('[exec]'):
        try:
            end_of_prefix_index = stripped_s.find(']') + 1
            return stripped_s[end_of_prefix_index:].lstrip()
        except ValueError:
            return s

    else:
        return s # 如果不是以这两个前缀开头，返回原字符串

def extract_compile_errors(compile_log:str) -> list:
    # 改进后的正则表达式，匹配 error
    error_or_warning_pattern = re.compile(
        r"(?:^|\n|\s*)\[(?:javac|exec)] \s*(.*?):(\d+):\s*error:\s*(.*)"
    )

    # 集合所有报错信息
    error_blocks = []
    current_block_lines = []

    # 这是一个简单的按行分割方法，但没有很好地处理多行报错。
    # 更健壮的方法是查找 [javac] + 路径:行号:
    # 我们先用一个简单的逻辑来构建块，然后再精细化
    lines = compile_log.split("\n")
    for i, line in enumerate(lines):
        # 查找 [javac] 并且后面是文件路径和行号:的行
        # 这通常标志着一个新错误/警告的开始
        potential_start_match = error_or_warning_pattern.search(line)
        if potential_start_match:
            # 如果当前块非空，先保存起来
            if current_block_lines:
                error_blocks.append("\n".join(current_block_lines))
            # 开始新的块
            current_block_lines = [line]
        elif current_block_lines:
            # 如果不是新的开始，但当前有正在构建的块，则将该行添加到当前块
            # 只要它以 [javac] 开头，或者看起来是上一个报错的延续
            # （例如，它没有 [javac] 前缀但紧跟在一个报错行后面，且有缩进）
            # if line.strip().startswith('[javac]') or (
            #         not line.strip() and current_block_lines[-1].strip().startswith('[javac]')):
            #     current_block_lines.append(line)
            # elif line.strip().startswith(' ') and current_block_lines and current_block_lines[-1].strip().startswith(
            #         '[javac]'):
            #     # 尝试处理缩进的下一行，比如 ^ 或 symbol:
            #     current_block_lines.append(line)
            # elif current_block_lines and (line.startswith('  symbol:') or line.startswith('  location:')):
            #     # 专门处理 symbol/location 的情况
            #     current_block_lines.append(line)

            # 1. 检查以 '[javac]' 或 '[exec]' 开头
            if line.strip().startswith('[javac]') or line.strip().startswith('[exec]'):
                line = remove_prefix(line)
                current_block_lines.append(line)

            # 2. 检查空行，并且前一行是 '[javac]' 或 '[exec]' 开头
            #    注意：这里我假设了 'current_block_lines' 至少有一行
            #    如果 'current_block_lines' 为空，而当前行是空行，这里会出错，需要根据实际情况调整
            elif (not line.strip()) and current_block_lines and \
                    (current_block_lines[-1].strip().startswith('[javac]') or current_block_lines[
                        -1].strip().startswith('[exec]')):
                line = remove_prefix(line)
                current_block_lines.append(line)

            # 3. 检查以空格开头，并且前一行是 '[javac]' 或 '[exec]' 开头
            elif line.strip().startswith(' ') and current_block_lines and \
                    (current_block_lines[-1].strip().startswith('[javac]') or current_block_lines[
                        -1].strip().startswith('[exec]')):
                # 尝试处理缩进的下一行，比如 ^ 或 symbol:
                line = remove_prefix(line)
                current_block_lines.append(line)

            # 4. 专门处理 symbol/location 的情况，但同样要加上对 '[exec]' 的支持
            elif current_block_lines and \
                    (line.startswith('  symbol:') or line.startswith('  location:')) and \
                    (current_block_lines[-1].strip().startswith('[javac]') or current_block_lines[
                        -1].strip().startswith('[exec]')):
                line = remove_prefix(line)
                current_block_lines.append(line)


    # 添加最后一个块
    if current_block_lines:
        error_blocks.append("\n".join(current_block_lines))

    extracted_info = []

    for block in error_blocks:
        # 尝试使用改进后的模式匹配第一行（通常包含文件名、行号、类型）
        match = error_or_warning_pattern.search(block)
        if match:
            file_path = match.group(1)
            line_number = match.group(2)
            # 错误/警告的直接描述
            error_message_start = match.group(3).strip()

            # 处理多行信息，例如 symbol/location
            full_error_description = error_message_start
            # 查找块中剩余的部分，通常是错误信息的详细解释
            # 排除掉已经匹配过的行
            remaining_lines = block.split('\n')
            # 找到包含主要报错信息的那一行，然后取其之后的行
            main_error_line_index = -1
            for idx, l in enumerate(remaining_lines):
                if error_or_warning_pattern.search(l):
                    main_error_line_index = idx
                    break

            if main_error_line_index != -1:
                # 从主报错行之后的所有行中，去除 [javac] 前缀和缩进，并合并
                for next_line in remaining_lines[main_error_line_index + 1:]:
                    stripped_next_line = next_line.strip()
                    if stripped_next_line:  # 忽略空行
                        # 移除 [javac] 前缀，如果存在
                        if stripped_next_line.startswith('[javac]'):
                            stripped_next_line = stripped_next_line[len('[javac]'):].strip()
                        # 避免重复添加已经包含在 group(3) 中的内容，这有点棘手，
                        # 简单起见，我们直接将剩余的非空部分附加
                        full_error_description += "\n" + stripped_next_line

            extracted_info.append({
                "File": file_path,
                "Line": line_number,
                "Description": full_error_description,
            })
        else:
            # 如果首行不匹配，可能是一些其他信息，我们暂不处理
            pass

    return extracted_info

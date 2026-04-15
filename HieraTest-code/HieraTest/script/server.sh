#!/bin/bash

# 设置环境变量，指定使用特定的GPU
export CUDA_VISIBLE_DEVICES=4

# 运行Python脚本，使用上述设置的环境变量
python -m vllm.entrypoints.openai.api_server \
--port 8004 \
--model ./models/deepseekcoder/16B_instruct \
--dtype auto \
--api-key token-8004 \
--trust-remote-code \
--gpu-memory-utilization 0.95 \
--max-model-len 40960




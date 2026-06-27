# EchoSoul 项目命令（Windows 兼容）
# 用法：make <target>

.PHONY: help run test lint format clean

help:  ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

chroma:  ## 启动 ChromaDB（关闭鉴权）
	CHROMA_SERVER_AUTHN_PROVIDER="" chroma run --path ./chroma_data

run:  ## 启动开发服务器（热重载）
	python run.py

test:  ## 运行单元测试
	pytest tests/unit/ -v

test-all:  ## 运行全部测试
	pytest tests/ -v

lint:  ## 运行 Ruff 代码检查
	ruff check app/

format:  ## 运行 Ruff 自动格式化
	ruff format app/

typecheck:  ## 运行 mypy 类型检查
	mypy app/

clean:  ## 清理 __pycache__ 和 .pyc 文件
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

cov:  ## 运行测试并生成覆盖率报告
	pytest tests/ --cov=app --cov-report=term-missing

check: lint typecheck test  ## 完整检查（lint + 类型 + 测试）

# EchoSoul - 你的 AI 虚拟陪伴伙伴

EchoSoul 是一个基于大语言模型的智能陪伴系统，旨在为用户提供温暖、自然、无评判的对话体验。无论你是感到孤独、需要倾诉，还是只想找个有趣的 AI 聊聊天，EchoSoul 都会用心倾听，并给予真诚的回应。

## ✨ 特性
- 🧠 基于大语言模型，理解自然语言情感
- 🎨 可自定义性格、语气和陪伴风格
- 📝 支持对话记忆，提供连续、个性化的交流
- 💬 轻量部署，快速接入

chroma run --host localhost --port 8000 --path ./chroma_data

locust -f locustfile.py --host=http://127.0.0.1:8000

celery -A app.celery_app worker --loglevel=info -P threads

uvicorn app.main:create_app --factory --host 127.0.0.1 --port 9000 --reload

uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 2

# 使用清华源安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 使用阿里源安装
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/


New-Item -Path . -Name ".gitignore" -ItemType File -Value ".env`n"



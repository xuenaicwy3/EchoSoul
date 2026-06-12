import asyncio
import json
import os
import base64
import uuid
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope.api_key:
    raise ValueError("请在 .env 文件中设置 DASHSCOPE_API_KEY")

# ==================== 阿里百炼客户端 ====================
class BailianClient:
    def __init__(self):
        self.llm_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        self.connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)

    async def chat_and_emotion(self, user_text: str, persona: str, history: list) -> tuple[str, str]:
        system_prompt = f"""你是一个{persona}的AI虚拟伴侣，名字叫小薇。
        请对用户的消息做出温柔、贴心的回复，并在回复开头用方括号标注你的情绪状态。
        情绪必须是以下之一：[happy]、[sad]、[angry]、[gentle]、[neutral]
        
        示例：
        用户：今天好累啊
        回复：[gentle]辛苦了，要不要我给你讲个笑话放松一下？"""

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_text})

        headers = {"Authorization": f"Bearer {dashscope.api_key}"}
        payload = {
            "model": "deepseek-v4-pro",
            "messages": messages,
            "temperature": 0.8,
            "stream": False,
            "max_tokens": 200,
        }

        # 关键：connector_owner=False 防止 connector 被 session 关闭
        async with aiohttp.ClientSession(connector=self.connector, connector_owner=False) as session:
            async with session.post(
                self.llm_url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]

        emotion = "neutral"
        clean_text = content
        for tag in ["[happy]", "[sad]", "[angry]", "[gentle]", "[neutral]"]:
            if content.startswith(tag):
                emotion = tag[1:-1]
                clean_text = content[len(tag):].strip()
                break

        return emotion, clean_text

    def synthesize(self, text: str, voice: str = "longanhuan_v3") -> bytes:
        """使用 cosyvoice-v3-flash 合成语音，返回 MP3 字节"""
        synthesizer = SpeechSynthesizer(
            model="cosyvoice-v3-flash",
            voice=voice
        )
        audio_data = synthesizer.call(text)
        if audio_data is None:
            raise RuntimeError("语音合成返回空数据，请检查模型/音色/配额")
        return audio_data

    async def close(self):
        await self.connector.close()

# ==================== Lifespan 上下文管理器 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = BailianClient()
    app.state.client = client  # type: ignore
    yield
    await client.close()

# ==================== FastAPI 应用 ====================
app = FastAPI(title="AI语音伴侣测试", lifespan=lifespan)

VOICE_MAP = {
    "温柔姐姐": "longanhuan",
    "活泼妹妹": "longanhuan_v3",
    "豪放可爱": "longling_v3",
    "高冷御姐": "longxian_v3",
}

@app.get("/", response_class=HTMLResponse)
async def index():
    return get_html()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print("✅ WebSocket 连接已建立")
    await ws.send_json({"text": "连接成功！请输入你想说的话。", "emotion": "neutral", "audio": None, "error": None})
    print("📤 已发送欢迎消息")

    history = []
    client: BailianClient = app.state.client  # type: ignore

    try:
        while True:
            print("⏳ 等待用户消息...")
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=30)
            except asyncio.TimeoutError:
                print("⏰ 30秒未收到消息，发送心跳并继续等待")
                await ws.send_json({"text": "heartbeat", "emotion": "neutral", "audio": None, "error": None})
                continue

            user_text = data.get("text", "").strip()
            print(f"📨 收到消息: '{user_text}'")
            if not user_text:
                await ws.send_json({"text": "请输入内容", "emotion": "neutral", "audio": None, "error": None})
                continue

            persona = data.get("persona", "温柔姐姐")
            voice = VOICE_MAP.get(persona, "longanhuan")

            # 1. 调用 LLM
            try:
                emotion, reply_text = await asyncio.wait_for(
                    client.chat_and_emotion(user_text, persona, history),
                    timeout=15
                )
                print(f"🤖 回复: {reply_text}")
            except asyncio.TimeoutError:
                reply_text = "LLM 响应超时，请稍后再试。"
                emotion = "neutral"
                print("❌ LLM 超时")
            except Exception as e:
                reply_text = f"出错了: {str(e)}"
                emotion = "neutral"
                print(f"❌ LLM 出错: {e}")

            # 2. 调用 TTS（带超时和容错）
            audio_b64 = None
            error_msg = None
            try:
                audio_bytes = await asyncio.wait_for(
                    asyncio.to_thread(client.synthesize, reply_text, voice),
                    timeout=15
                )
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                print("🔊 语音合成成功")
            except asyncio.TimeoutError:
                error_msg = "语音合成超时，仅文字回复"
                print("❌ TTS 超时")
            except Exception as e:
                error_msg = f"语音合成失败: {str(e)}"
                print(f"❌ TTS 错误: {e}")

            # 3. 发送回复
            await ws.send_json({
                "text": reply_text,
                "emotion": emotion,
                "audio": audio_b64,
                "error": error_msg
            })

            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply_text})
            history = history[-20:]

    except WebSocketDisconnect:
        print("客户端断开连接")

def get_html():
    return """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>AI语音伴侣 - 百炼测试</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }
        .chat-box { border: 1px solid #ccc; height: 400px; overflow-y: auto; padding: 10px; margin-bottom: 20px; background: #fafafa; }
        .msg { margin: 8px 0; }
        .user { color: #0066cc; }
        .ai { color: #cc6600; }
        audio { width: 100%; margin-top: 5px; }
        select, input, button { font-size: 16px; padding: 8px; margin: 4px 0; }
    </style>
</head>
<body>
    <h2>🎧 AI语音伴侣 - 文字进 语音出</h2>
    <div>
        <label>AI性格：</label>
        <select id="persona">
            <option>温柔姐姐</option>
            <option>活泼妹妹</option>
            <option>豪放可爱</option>
            <option>高冷御姐</option>
        </select>
    </div>
    <div class="chat-box" id="chatBox"></div>
    <div>
        <input type="text" id="userInput" placeholder="输入你的心里话..." size="40" />
        <button id="sendBtn">发送</button>
    </div>

    <script>
        console.log("📡 正在连接 WebSocket...");
        const ws = new WebSocket("ws://" + location.host + "/ws");
        const chatBox = document.getElementById("chatBox");

        ws.onopen = () => {
            console.log("✅ WebSocket 已连接");
        };

        ws.onmessage = (event) => {
            console.log("📩 收到消息", event.data);
            const data = JSON.parse(event.data);
            // 忽略心跳消息（纯文字为 "heartbeat"）
            if (data.text === "heartbeat") return;
            addMessage("ai", data.text, data.audio);
        };

        ws.onerror = (e) => {
            console.error("❌ WebSocket 错误", e);
        };

        ws.onclose = (e) => {
            console.log("🔌 WebSocket 关闭", e.code, e.reason);
        };

        function addMessage(role, text, audioBase64) {
            const div = document.createElement("div");
            div.className = "msg " + role;
            div.innerHTML = `<strong>${role === 'user' ? '我' : 'AI'}:</strong> ${text}`;
            if (audioBase64) {
                const audio = document.createElement("audio");
                audio.controls = true;
                audio.src = "data:audio/mp3;base64," + audioBase64;
                div.appendChild(audio);
            }
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        function sendMessage() {
            const input = document.getElementById("userInput");
            const text = input.value.trim();
            if (!text) {
                console.log("⚠️ 消息为空，不发送");
                return;
            }
            const persona = document.getElementById("persona").value;
            console.log(`📤 发送消息: "${text}" persona: ${persona}`);
            addMessage("user", text);
            ws.send(JSON.stringify({ text, persona }));
            input.value = "";
        }

        document.getElementById("sendBtn").addEventListener("click", sendMessage);
        document.getElementById("userInput").addEventListener("keydown", (e) => {
            if (e.key === "Enter") sendMessage();
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
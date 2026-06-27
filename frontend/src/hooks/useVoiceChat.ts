import { useRef, useState, useCallback } from "react";
import { useAuthStore } from "../store/authStore";
import { useAudioPlayer } from "./useAudioPlayer";
import { setLive2DExpression } from "../components/live2d/Live2DCanvas";

interface VoiceState {
  isListening: boolean;
  isSpeaking: boolean;
  asrText: string;
}

export function useVoiceChat(): VoiceState & {
  startListening: () => Promise<void>;
  stopListening: () => void;
} {
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [asrText, setAsrText] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const token = useAuthStore((s) => s.token);
  const userId = useAuthStore((s) => s.userId);
  const { play, stop } = useAudioPlayer();
  const vadIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const vadStreamRef = useRef<MediaStream | null>(null);

  const stopVADMonitor = useCallback(() => {
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
  }, []);

  const startListening = useCallback(async () => {
    if (!token || !userId) throw new Error("未登录");

    // 如果 AI 正在说话，先发送打断信号
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
      stop(); // 停止音频播放
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${wsProtocol}//${location.host}/ws/voice/${userId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token }));
      ws.send(JSON.stringify({ type: "mic-audio-start" }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === "asr-result" || msg.type === "asr-final") {
          if (msg.text) setAsrText(msg.text);
        }

        if (msg.type === "speech-end") {
          setIsSpeaking(false);
          stopVADMonitor(); // AI 说完了，停止后台监听
          setLive2DExpression(4); // neutral
          // Close mouth + reset smoothing
          try {
            (window as any).__mouthCurrent = 0;
            const core = (window as any).__live2dModel?.internalModel?.coreModel;
            if (core) {
              core.setParameterValueById("ParamMouthOpenY", 0);
              ["ParamEyeLSmile","ParamEyeRSmile","ParamBrowLY","ParamBrowRY",
               "ParamBrowLAngle","ParamBrowRAngle","ParamMouthForm","ParamCheek",
               "ParamEyeLOpen","ParamEyeROpen"].forEach(p => core.setParameterValueById(p, 0));
            }
          } catch { /* */ }
        }

        if (msg.type === "audio-chunk" && msg.audio) {
          setIsSpeaking(true);
          startVADMonitor(); // AI 说话时后台监听用户声音
          stop(); // stop previous playback
          // Play audio with lip-sync volumes
          play(
            msg as any,
            (volume: number) => {
              // 商业级 Lip-Sync: Power Curve + Lerp + 参数范围校准
              try {
                const model = (window as any).__live2dModel;
                const core = model?.internalModel?.coreModel;
                if (!core) return;
                // 1. Power Curve: 幂函数拉高低音区细节
                const boosted = Math.pow(Math.min(1, volume * 3), 0.7);
                // 2. Lerp 平滑
                const current = (window as any).__mouthCurrent || 0;
                const smoothed = current + (boosted - current) * 0.4;
                (window as any).__mouthCurrent = smoothed;
                // 3. Live2D 参数范围 0~2（非 0~1），大幅张嘴
                core.setParameterValueById("ParamMouthOpenY", smoothed * 2);
              } catch { /* ignore */ }
            },
            (exprs: number[]) => {
              const idx = exprs[0] ?? 4;
              console.log("[Expr] set expression index:", idx);
              setLive2DExpression(idx);
            },
          );
        }
      } catch { /* */ }
    };

    ws.onerror = () => { stopListening(); };
    ws.onclose = () => { setIsListening(false); setIsSpeaking(false); };

    // 音频采集
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = async (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
        const buffer = await e.data.arrayBuffer();
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
        ws.send(JSON.stringify({ type: "mic-audio-data", data: base64 }));
      }
    };

    recorder.start(250);
    setIsListening(true);
    setAsrText("");
  }, [token, userId, play, stop]);

  const stopListening = useCallback(() => {
    mediaRecorderRef.current?.stop();
    // 保留 mic stream 用于 VAD 后台监听（AI 说话时检测打断）
    vadStreamRef.current = streamRef.current;
    stopVADMonitor();
    stop(); // stop TTS playback
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "mic-audio-end" }));
    }
    setIsListening(false);
    setIsSpeaking(false);
  }, [stop, stopVADMonitor]);

  // 后台 VAD 监听: AI 说话时检测用户声音 → 自动打断
  const startVADMonitor = useCallback(() => {
    stopVADMonitor();
    const stream = vadStreamRef.current;
    if (!stream) return;
    try {
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      vadIntervalRef.current = setInterval(() => {
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        if (avg > 30) {
          console.log("[VAD] 检测到用户声音, avg=", avg.toFixed(0), " → 自动打断");
          stopVADMonitor();
          audioCtx.close();
          startListening();
        }
      }, 200);
    } catch { /* 静默降级 */ }
  }, [startListening, stopVADMonitor]);

  return { isListening, isSpeaking, asrText, startListening, stopListening };
}

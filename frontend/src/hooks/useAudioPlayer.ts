import { useRef, useCallback } from "react";

interface AudioChunkMessage {
  type: "audio-chunk";
  audio: string;
  volumes: number[];
  slice_length_ms: number;
  text: string;
  expressions: number[];
}

interface QueuedChunk {
  chunk: AudioChunkMessage;
  onVolume?: (v: number) => void;
  onExpression?: (expressions: number[]) => void;
}

export function useAudioPlayer() {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const onVolumeRef = useRef<((v: number) => void) | null>(null);
  const onExpressionRef = useRef<((expr: number[]) => void) | null>(null);
  const playingRef = useRef(false);
  const queueRef = useRef<QueuedChunk[]>([]);

  const getAudioContext = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext({ sampleRate: 16000 });
    }
    return audioCtxRef.current;
  }, []);

  const playChunk = useCallback(
    async (
      chunk: AudioChunkMessage,
      onVolume?: (v: number) => void,
      onExpression?: (expressions: number[]) => void,
    ) => {
      onVolumeRef.current = onVolume || null;
      onExpressionRef.current = onExpression || null;

      const ctx = getAudioContext();

      // 解码 base64 WAV
      const raw = Uint8Array.from(atob(chunk.audio), (c) => c.charCodeAt(0));
      const audioBuffer = await ctx.decodeAudioData(raw.buffer.slice(0));

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      sourceRef.current = source;
      playingRef.current = true;

      // 播放完成后播队列中下一个
      source.onended = () => {
        playingRef.current = false;
        sourceRef.current = null;
        const next = queueRef.current.shift();
        if (next) {
          playChunk(next.chunk, next.onVolume, next.onExpression);
        }
      };

      // 口型同步
      if (chunk.volumes.length > 0 && onVolumeRef.current) {
        const sliceMs = chunk.slice_length_ms || 20;
        const totalFrames = audioBuffer.length;
        const totalDuration = totalFrames / audioBuffer.sampleRate;

        const startTime = ctx.currentTime;
        const checkVolume = () => {
          const elapsed = ctx.currentTime - startTime;
          const idx = Math.floor(elapsed * 1000 / sliceMs);
          if (idx < chunk.volumes.length && onVolumeRef.current) {
            onVolumeRef.current(chunk.volumes[idx]);
          }
          if (idx < Math.floor(totalDuration * 1000 / sliceMs)) {
            requestAnimationFrame(checkVolume);
          }
        };
        source.start();
        requestAnimationFrame(checkVolume);
      } else {
        source.start();
      }

      // 表情切换
      if (chunk.expressions.length > 0 && onExpressionRef.current) {
        onExpressionRef.current(chunk.expressions);
      }
    },
    [getAudioContext],
  );

  const play = useCallback(
    async (
      chunk: AudioChunkMessage,
      onVolume?: (v: number) => void,
      onExpression?: (expressions: number[]) => void,
    ) => {
      // 正在播放 → 入队，不打断
      if (playingRef.current && sourceRef.current) {
        queueRef.current.push({ chunk, onVolume, onExpression });
        return;
      }
      // 空闲 → 直接播放
      await playChunk(chunk, onVolume, onExpression);
    },
    [playChunk],
  );

  const stop = useCallback(() => {
    // 中止播放 + 清空队列（用户打断时用）
    sourceRef.current?.stop();
    sourceRef.current = null;
    playingRef.current = false;
    queueRef.current = [];
  }, []);

  return { play, stop };
}

import { useRef, useCallback } from "react";

interface AudioChunkMessage {
  type: "audio-chunk";
  audio: string;        // base64 WAV
  volumes: number[];
  slice_length_ms: number;
  text: string;
  expressions: number[];
}

export function useAudioPlayer() {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const onVolumeRef = useRef<((v: number) => void) | null>(null);
  const onExpressionRef = useRef<((expr: number[]) => void) | null>(null);

  const getAudioContext = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext({ sampleRate: 16000 });
    }
    return audioCtxRef.current;
  }, []);

  const play = useCallback(
    async (
      chunk: AudioChunkMessage,
      onVolume?: (v: number) => void,
      onExpression?: (expressions: number[]) => void,
    ) => {
      onVolumeRef.current = onVolume || null;
      onExpressionRef.current = onExpression || null;

      // Stop previous playback
      sourceRef.current?.stop();

      const ctx = getAudioContext();
      const raw = Uint8Array.from(atob(chunk.audio), (c) => c.charCodeAt(0));
      const audioBuffer = await ctx.decodeAudioData(raw.buffer.slice(0));

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      sourceRef.current = source;

      // Volumes → createScriptProcessor or use AudioWorklet for lip sync
      if (chunk.volumes.length > 0 && onVolumeRef.current) {
        const sliceMs = chunk.slice_length_ms || 20;
        const totalFrames = audioBuffer.length;
        const totalDuration = totalFrames / audioBuffer.sampleRate;
        const totalSlices = Math.floor(totalDuration * 1000 / sliceMs);

        const startTime = ctx.currentTime;
        const checkVolume = () => {
          const elapsed = ctx.currentTime - startTime;
          const idx = Math.floor(elapsed * 1000 / sliceMs);
          if (idx < chunk.volumes.length && onVolumeRef.current) {
            onVolumeRef.current(chunk.volumes[idx]);
          }
          if (idx < totalSlices) {
            requestAnimationFrame(checkVolume);
          }
        };
        source.onended = () => {};
        source.start();
        requestAnimationFrame(checkVolume);
      } else {
        source.start();
      }

      // Expressions
      console.log("[AudioPlayer] expr check:", chunk.expressions, "hasCB:", !!onExpressionRef.current);
      if (chunk.expressions.length > 0 && onExpressionRef.current) {
        console.log("[AudioPlayer] calling expression callback with:", chunk.expressions);
        onExpressionRef.current(chunk.expressions);
      }
    },
    [getAudioContext],
  );

  const stop = useCallback(() => {
    sourceRef.current?.stop();
  }, []);

  return { play, stop };
}

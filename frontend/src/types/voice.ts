export interface MicAudioStart {
  type: "mic-audio-start";
}

export interface MicAudioData {
  type: "mic-audio-data";
  data: string; // base64
}

export interface MicAudioEnd {
  type: "mic-audio-end";
}

export interface Interrupt {
  type: "interrupt";
}

export type ClientVoiceMessage = MicAudioStart | MicAudioData | MicAudioEnd | Interrupt;

export interface AsrResult {
  type: "asr-result";
  text: string;
}

export interface AsrFinal {
  type: "asr-final";
  text: string;
}

export interface LlmStream {
  type: "llm-stream";
  text: string;
}

export interface AudioChunk {
  type: "audio-chunk";
  audio: string;        // base64
  volumes: number[];    // RMS per slice
  slice_length_ms: number;
  text: string;         // subtitle
  expressions: number[];
}

export interface SpeechEnd {
  type: "speech-end";
}

export type ServerVoiceMessage =
  | AsrResult
  | AsrFinal
  | LlmStream
  | AudioChunk
  | SpeechEnd;

export interface Live2DModelConfig {
  name: string;
  url: string;
  kScale?: number;
  emotionMap: Record<string, number>;
  model_type: "live2d";
}

/** 8 角色 — Live2D 模型配置（4个角色用Live2D，4个用VRM见 vrm.ts） */
export const LIVE2D_MODELS: Record<string, Live2DModelConfig> = {
  "日系动漫型": { name: "hiyori_pro", url: "/live2d/hiyori/hiyori_pro/runtime/hiyori_pro_t11.model3.json", kScale: 0.18, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "高冷御姐型": { name: "hiyori_pro", url: "/live2d/hiyori/hiyori_pro/runtime/hiyori_pro_t11.model3.json", kScale: 0.18, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "傲娇辣妹型": { name: "miku_pro", url: "/live2d/hiyori/miku_pro/runtime/miku_sample_t04.model3.json", kScale: 0.36, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "甜美校花型": { name: "hiyori_pro", url: "/live2d/hiyori/hiyori_pro/runtime/hiyori_pro_t11.model3.json", kScale: 0.18, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "软萌可爱型": { name: "miku_pro", url: "/live2d/hiyori/miku_pro/runtime/miku_sample_t04.model3.json", kScale: 0.36, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "温柔贤淑型": { name: "hiyori_pro", url: "/live2d/hiyori/hiyori_pro/runtime/hiyori_pro_t11.model3.json", kScale: 0.18, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "元气少女型": { name: "miku_pro", url: "/live2d/hiyori/miku_pro/runtime/miku_sample_t04.model3.json", kScale: 0.36, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
  "清冷仙气型": { name: "miku_pro", url: "/live2d/hiyori/miku_pro/runtime/miku_sample_t04.model3.json", kScale: 0.36, emotionMap: { joy:0, sadness:1, surprise:2, anger:3, neutral:4 }, model_type: "live2d" },
};

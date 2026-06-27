export interface GLBModelConfig {
  name: string;
  path: string;
  scale?: number;
  format: "glb" | "vrm";
}

/** 4 个角色用 3D 模型（VRM 优先，带骨骼+BlendShape） */
export const GLB_MODELS: Record<string, GLBModelConfig> = {
  "傲娇辣妹型": { name: "vrm_a", path: "/vrm/model_a.vrm", format: "vrm" },
  "甜美校花型": { name: "vrm_b", path: "/vrm/model_b.vrm", format: "vrm" },
  "元气少女型": { name: "vrm_a", path: "/vrm/model_a.vrm", format: "vrm" },
  "清冷仙气型": { name: "vrm_b", path: "/vrm/model_b.vrm", format: "vrm" },
};

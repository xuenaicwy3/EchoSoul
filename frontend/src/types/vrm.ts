export interface GLBModelConfig {
  name: string;
  path: string;         // .glb 文件在 public/ 下的路径
  scale?: number;       // 模型缩放 (Live2D hiYori 等效 ≈ 2.2)
}

/** 4 个角色用 GLB 3D 模型 */
export const GLB_MODELS: Record<string, GLBModelConfig> = {
  "傲娇辣妹型": { name: "alice", path: "/glb/model_alice.glb", scale: 1.0 },
  "甜美校花型": { name: "julis", path: "/glb/model_julis.glb", scale: 1.0 },
  "元气少女型": { name: "alice", path: "/glb/model_alice.glb", scale: 1.0 },
  "清冷仙气型": { name: "julis", path: "/glb/model_julis.glb", scale: 1.0 },
};

export interface Role {
  name: string;
  persona: string;
  greeting: string;
  style: string;
  avatar: string;            // 缩略图
  live2d_model_path?: string; // Live2D .model3.json 路径
}

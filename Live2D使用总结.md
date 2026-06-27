# EchoSoul Live2D 虚拟角色渲染踩坑与解决
## 技术背景
- 项目后端 Python FastAPI，前端 React 19 + TypeScript + PixiJS v7，8 个日系角色共用 2 个 Live2D Cubism 3/4 模型，通过 Live2D Cubism Core + pixi-live2d-display 渲染。Live2D 模型需先加载 Core 运行库（WebAssembly），再通过 .model3.json 加载模型数据渲染。

## 问题一：Cubism Core 运行时加载失败
- 现象：Could not find Cubism 2/4 runtime，模型始终黑屏。
- 根因：pixi-live2d-display 被 import 时同步检查 window.Live2DCubismCore 全局对象。我在 React 组件内用 useEffect + 动态 <script> 标签异步加载 Core，加载时序晚于包 import → 库检查时全局不存在。
### 解决：在 index.html 用 <script> 标签同步加载 CDN 的 Cubism Core：

- <script src="https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"></script>
- 关键认知：第三方渲染库的运行时依赖必须有确定的加载顺序，不能依赖 React lifecycle。

## 问题二：React DOM 与 PIXI WebGL 冲突——最致命的架构问题
- 现象 1：切换角色会话 → NotFoundError: Failed to execute 'removeChild' on 'Node' → 页面卡死。
- 现象 2：隐藏角色再恢复 → 模型无法重新渲染。
- 根因分析：我最初让 React 管理 <canvas ref={canvasRef}> JSX 元素，PIXI 通过 view: canvasRef.current 接管同一个 DOM 节点。PIXI 销毁时 app.destroy(true) 从 DOM 移除 canvas，React 不知情，下次 virtual DOM diff 找不到节点 → crash。

### 解决——WebGL 与 Virtual DOM 分离：
- // ❌ 错误：React JSX canvas 给 PIXI 用 <canvas ref={canvasRef} />
- // ✅ 正确：PIXI 自己创建 canvas，React 只管 div 容器
- <div ref={containerRef} />
- → app = new PIXI.Application({ width, height })
- → containerRef.current.appendChild(app.view)
- 切换角色时 container.innerHTML = "" + app.destroy(true) 彻底重建 WebGL 上下文，React 无感知。

- 这个问题的本质是：Virtual DOM 和 WebGL 两种渲染范式不能共享 DOM 控制权。React 管理布局容器，WebGL 管理自己的 canvas 生命周期，这是所有 React + WebGL 集成的标准模式。

## 问题三：Cubism 3.1 老模型 Skinning 兼容性
- 现象：hiyori（Cubism 4）模型正常渲染，miku（Cubism 3.1, 2019, 带 Skinning）始终 getBoundingClientRect 报错然后空白。

- 排查过程：

- 先确认模型文件完整（.moc3 + .physics3.json + texture PNG 都在）
- 在浏览器 console 看到 Live2D Cubism SDK Core Version 5.1.0
- miku ReadMe 显示 "Cubism Editor 3.1, 2019" — 非常老
- 排除法：换回 pixi-live2d-display@0.4.0 原版 → 两个模型都正常
- 根因：pixi-live2d-display-lipsyncpatch 社区 fork 对 Cubism 3.1 的 Skinning 骨骼模型内部 view 初始化时序有 bug，不是 Cubism 5 Core 兼容问题。

### 解决：回退到 pixi-live2d-display@0.4.0 原版包。v0.4.0 虽然主 target 是 pixi.js v6，但在 v7 上核心渲染功能正常，只有 console 一个 cosmetic warning。

## 问题四：Vite 构建 vs FastAPI 静态托管
- 现象：Vite dev server 能跑，FastAPI 生产环境 404 找不到模型文件。
- 根因：Vite build 把 public/live2d/ 拷贝到 app/static/live2d/，但 FastAPI 只 mount 了 /assets 目录。

### 解决：FastAPI 增加 StaticFiles mount：
- app.mount("/live2d", StaticFiles(directory=str(_static_dir / "live2d")))
- 面试表达框架
- 如果要串成一个流畅的回答：

## "我们在 React 里集成 Live2D 遇到了四类典型问题。
- 第一是运行时加载时序——Cubism Core 必须在 React bundle 之前同步加载，直接放 index.html 的 script 标签解决。
- 第二也是最棘手的——React Virtual DOM 和 PIXI WebGL 的 DOM 控制权冲突，本质是两种渲染范式不能共享 DOM 节点，方案是 PIXI 自己创建 canvas，React 只管理容器 div，切换角色时彻底销毁 WebGL 上下文重建。
- 第三是 pixi-live2d-display 社区 fork 对 Cubism 3.1 skinning 老模型的兼容 bug，回退原版包解决。
- 第四是构建产物和 FastAPI 静态服务的路径映射问题，加一个 StaticFiles mount 就解决了。"

- 总结一句话：渲染库跟框架抢 DOM 是死穴，WebGL 跟 Virtual DOM 必须分治
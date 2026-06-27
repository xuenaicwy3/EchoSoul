import { useEffect, useRef, useState, useCallback, memo } from "react";
import * as PIXI from "pixi.js";
import { LIVE2D_MODELS } from "../../types/live2d";

(window as unknown as Record<string, unknown>).PIXI = PIXI;

interface Props {
  roleType: string;
  onModelReady?: (model: any) => void;
}

// 全局表达式状态（每帧持续应用的参数）
let _expressionParams: [string, number][] = [];

const EXPRESSION_MAP: Record<number, [string, number][]> = {
  0: [["ParamEyeLSmile",1],["ParamEyeRSmile",1],["ParamMouthForm",1],["ParamCheek",1]],                             // joy: 笑眼+嘴角+脸红
  1: [["ParamEyeLOpen",0.2],["ParamEyeROpen",0.2],["ParamBrowLY",1],["ParamBrowRY",1],["ParamMouthForm",-1]],      // sad: 眯眯眼+眉低+嘴角下拉
  2: [["ParamEyeLOpen",1],["ParamEyeROpen",1],["ParamEyeBallY",-1],["ParamMouthOpenY",0.6],["ParamBrowLY",-1],["ParamBrowRY",-1]], // surprise: 瞪眼+眼球上翻+张嘴+眉上扬
  3: [["ParamBrowLAngle",1],["ParamBrowRAngle",1],["ParamBrowLForm",1],["ParamBrowRForm",1],["ParamMouthForm",0.5]], // anger: 怒眉角度+皱眉+嘴角紧
  4: [],
};

export function setLive2DExpression(idx: number) {
  _expressionParams = EXPRESSION_MAP[idx] || [];
}

const CANVAS_W = 520;
const CANVAS_H = 640;

const Live2DCanvas = memo(function Live2DCanvas({ roleType, onModelReady }: Props) {
  // 容器 div — PIXI 内部创建 canvas，不跟 React 抢 DOM 控制权
  const containerRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<any>(null);
  const animRef = useRef(0);
  const [visible, setVisible] = useState(true);
  const [error, setError] = useState("");

  const posRef = useRef({ x: window.innerWidth - CANVAS_W - 16, y: 16 });
  const [pos, setPos] = useState(posRef.current);
  const draggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0, ox: 0, oy: 0 });

  const toggleVisible = useCallback(() => setVisible((v) => !v), []);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    dragStartRef.current = {
      x: e.clientX, y: e.clientY,
      ox: posRef.current.x, oy: posRef.current.y,
    };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      posRef.current = {
        x: dragStartRef.current.ox + e.clientX - dragStartRef.current.x,
        y: dragStartRef.current.oy + e.clientY - dragStartRef.current.y,
      };
      setPos(posRef.current);
    };
    const onUp = () => { draggingRef.current = false; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Live2D 渲染 — roleType 变化时完全重建
  useEffect(() => {
    const config = LIVE2D_MODELS[roleType] || LIVE2D_MODELS["日系动漫型"];
    if (!config) return;

    let destroyed = false;
    const container = containerRef.current;
    if (!container) return;

    // 清空容器（旧 PIXI canvas）
    cancelAnimationFrame(animRef.current);
    if (modelRef.current) { try { modelRef.current.destroy?.(); } catch { /* */ } modelRef.current = null; }
    if (appRef.current) {
      try { appRef.current.destroy?.(true, { children: true, texture: true }); } catch { /* */ }
      appRef.current = null;
    }
    container.innerHTML = "";

    const init = async () => {
      setError("");
      try {
        // PIXI 自己创建 canvas，不与 React JSX canvas 冲突
        const app = new PIXI.Application({
          width: CANVAS_W,
          height: CANVAS_H,
          backgroundAlpha: 0,
          antialias: false,
          resolution: window.devicePixelRatio || 1,
          autoDensity: true,
          preserveDrawingBuffer: true,
          powerPreference: "high-performance",
        });
        if (destroyed) { app.destroy(true); return; }
        // app.view 是 PIXI 内部创建的 canvas
        (app.view as HTMLCanvasElement).style.display = "block";
        container.appendChild(app.view as HTMLCanvasElement);
        appRef.current = app;

        const { Live2DModel } = await import("pixi-live2d-display/cubism4");
        const model = await Live2DModel.from(config.url, { autoInteract: false });
        if (destroyed) { model.destroy(); return; }

        model.scale.set(config.kScale || 0.18);
        model.anchor.set(0.5, 0.5);
        model.x = CANVAS_W / 2;
        model.y = CANVAS_H / 2;
        app.stage.addChild(model as any);
        modelRef.current = model;
        // 通知父组件模型就绪（用于 lip-sync 等外部控制）
        onModelReady?.(model);

        const onMouse = (e: MouseEvent) => {
          if (!modelRef.current) return;
          const rect = (app.view as HTMLCanvasElement).getBoundingClientRect();
          modelRef.current.x = CANVAS_W / 2 + ((e.clientX - rect.left) / CANVAS_W * 2 - 1) * 10;
          modelRef.current.y = CANVAS_H / 2 + ((e.clientY - rect.top) / CANVAS_H * 2 - 1) * 6;
        };
        window.addEventListener("mousemove", onMouse);

        const tick = () => {
          if (destroyed) return;
          // 每帧持续应用表情参数（对抗物理/呼吸动画的覆盖）
          if (modelRef.current && _expressionParams.length > 0) {
            try {
              const core = (modelRef.current as any).internalModel?.coreModel;
              if (core) {
                for (const [pid, val] of _expressionParams) {
                  core.setParameterValueById(pid, val);
                }
                // 每秒一次诊断日志
                if (Math.random() < 0.016) {
                  const samples = _expressionParams.slice(0,2).map(([p,v]) => `${p}=${v.toFixed(2)}`).join(" ");
                  console.log("[Expr tick]", samples);
                }
              }
            } catch { /* */ }
          }
          app.render();
          animRef.current = requestAnimationFrame(tick);
        };
        animRef.current = requestAnimationFrame(tick);

        return () => { window.removeEventListener("mousemove", onMouse); };
      } catch (err) {
        if (!destroyed) {
          console.error("[Live2D]", err);
          setError(err instanceof Error ? err.message : "模型加载失败");
        }
      }
    };

    init();
    return () => {
      destroyed = true;
      cancelAnimationFrame(animRef.current);
    };
  }, [roleType]);

  // 最终卸载
  useEffect(() => {
    return () => {
      cancelAnimationFrame(animRef.current);
      if (modelRef.current) { try { modelRef.current.destroy?.(); } catch { /* */ } }
      if (appRef.current) { try { appRef.current.destroy?.(true, { children: true, texture: true }); } catch { /* */ } }
    };
  }, []);

  return (
    <>
      <div
        style={{
          position: "fixed", right: 16, top: 16, zIndex: 9999,
          width: 40, height: 40, borderRadius: "50%",
          background: "rgba(255,255,255,0.9)", boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
          display: visible ? "none" : "flex",
          alignItems: "center", justifyContent: "center",
          fontSize: 20, cursor: "pointer",
        }}
        onClick={toggleVisible}
        title="显示角色"
      >
        🌸
      </div>

      <div
        style={{
          position: "fixed", left: pos.x, top: pos.y, zIndex: 9999,
          display: visible ? "block" : "none", userSelect: "none",
        }}
        onMouseDown={handleMouseDown}
      >
        <button
          onClick={(e) => { e.stopPropagation(); toggleVisible(); }}
          title="隐藏角色"
          style={{
            position: "absolute", top: 4, right: 4, zIndex: 10,
            width: 24, height: 24, borderRadius: "50%",
            border: "none", background: "rgba(0,0,0,0.35)", color: "#fff",
            fontSize: 14, cursor: "pointer", lineHeight: "24px", textAlign: "center",
            outline: "none", WebkitTapHighlightColor: "transparent",
          }}
        >
          ×
        </button>

        <div
          ref={containerRef}
          style={{
            width: CANVAS_W, height: CANVAS_H,
            background: error ? "rgba(0,0,0,0.05)" : "transparent",
            borderRadius: error ? 8 : 0,
          }}
        >
          {error && (
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              color: "#999", fontSize: 14,
            }}>
              <div style={{ fontSize: 48, marginBottom: 8 }}>🌸</div>
              <div>模型加载失败</div>
              <div style={{ fontSize: 12, marginTop: 4 }}>{error}</div>
            </div>
          )}
        </div>
      </div>
    </>
  );
});

export default Live2DCanvas;

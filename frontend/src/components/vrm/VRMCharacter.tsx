import { useEffect, useRef, useState, memo } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { GLB_MODELS } from "../../types/vrm";

const SIZE = 640;

const VRMCharacter = memo(function VRMCharacter({ roleType }: { roleType: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<HTMLDivElement>(null);  // Three.js canvas 容器
  const modelRef = useRef<THREE.Group | null>(null);
  const mixerRef = useRef<THREE.AnimationMixer | null>(null);
  const clockRef = useRef(new THREE.Clock());
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const [visible, setVisible] = useState(true);
  const [error, setError] = useState("");

  const posRef = useRef({ x: window.innerWidth - SIZE - 16, y: 16 });
  const [pos, setPos] = useState(posRef.current);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, ox: 0, oy: 0 });

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, ox: posRef.current.x, oy: posRef.current.y };
  };
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      posRef.current = { x: dragRef.current.ox + e.clientX - dragRef.current.startX, y: dragRef.current.oy + e.clientY - dragRef.current.startY };
      setPos(posRef.current);
    };
    const onUp = () => { dragRef.current.dragging = false; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  useEffect(() => {
    const config = GLB_MODELS[roleType];
    if (!config) return;

    let destroyed = false;
    const view = viewRef.current;
    if (!view) return;
    // 清空旧 canvas
    view.innerHTML = "";
    setError("");

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(SIZE, SIZE);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rendererRef.current = renderer;
    view.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const FOV = 30;
    const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 50);

    // 二次元角色灯光
    scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
    keyLight.position.set(1, 2, 3);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xffe8f0, 1.0);
    fillLight.position.set(-1, 0.5, 1);
    scene.add(fillLight);

    const loader = new GLTFLoader();
    loader.load(
      config.path,
      (gltf: any) => {
        if (destroyed) return;
        console.log("[VRM] 模型加载成功, meshes:", gltf.scene.children.length);
        const model = gltf.scene;

        // 诊断材质结构
        model.traverse((c: any) => { if (c.isMesh) { console.log("[VRM] material:", c.material?.type, "map:", !!c.material?.map, "color:", c.material?.color?.getHex()); }});

        // 自动适配：动态计算缩放 + 相机距离，确保完整可见
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const targetHeight = 6.0;
        const fitScale = targetHeight / Math.max(size.y, 0.01);
        model.scale.setScalar(fitScale);
        const halfFovRad = (FOV / 2) * (Math.PI / 180);
        const cameraZ = targetHeight / (2 * Math.tan(halfFovRad)) * 1.35;
        camera.position.set(0, 1.6, cameraZ);
        const center = box.getCenter(new THREE.Vector3());
        // 精确上移：脚底对齐相机可视底部
        const halfH = size.y * fitScale / 2;
        const camBottom = camera.position.y - cameraZ * Math.tan(halfFovRad);
        const shift = Math.max(0, camBottom + halfH) + halfH * 0.15;  // +5% 安全边距
        model.position.set(-center.x * fitScale, -center.y * fitScale + shift, -center.z * fitScale);
        scene.add(model);
        modelRef.current = model;

        // 查找下巴骨骼用于口型同步
        let jawBone: THREE.Bone | null = null;
        model.traverse((child: any) => {
          const c = child as any;
          if (c.isBone && /jaw|head/i.test(c.name)) {
            if (!jawBone || /jaw/i.test(c.name)) jawBone = c;
          }
        });
        if (jawBone) {
          (window as any).__glbJawBone = jawBone;
          console.log("[VRM] 下巴骨骼: %s", (jawBone as any).name);
        } else {
          (window as any).__glbJawBone = null;
          console.warn("[VRM] 未找到下巴骨骼");
        }

        if (gltf.animations.length > 0) {
          mixerRef.current = new THREE.AnimationMixer(model);
          gltf.animations.forEach((clip: THREE.AnimationClip) => {
            mixerRef.current!.clipAction(clip).play();
          });
        }
        // 暴露 morph targets 用于后续 lip-sync
        (window as any).__glbMorphTargets = model;
        (window as any).__glbModel = model;
      },
      (xhr: any) => { console.log("[VRM] 加载进度: %s", xhr?.loaded); },
      (err: any) => { console.error("[VRM] 加载失败:", err); if (!destroyed) setError(err?.message || "模型加载失败"); },
    );

    let animId = 0;
    const tick = () => {
      if (destroyed) return;
      const dt = clockRef.current.getDelta();
      if (mixerRef.current) mixerRef.current.update(dt);
      renderer.render(scene, camera);
      animId = requestAnimationFrame(tick);
    };
    animId = requestAnimationFrame(tick);

    return () => {
      destroyed = true;
      cancelAnimationFrame(animId);
      renderer.dispose();
      (window as any).__glbModel = null;
    };
  }, [roleType]);

  return (
    <>
      <div style={{ position: "fixed", right: 16, top: 16, zIndex: 9998, width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,0.9)", boxShadow: "0 2px 8px rgba(0,0,0,0.15)", display: visible ? "none" : "flex", alignItems: "center", justifyContent: "center", fontSize: 20, cursor: "pointer" }} onClick={() => setVisible(true)} title="显示角色">🌸</div>
      <div ref={containerRef} style={{ position: "fixed", left: pos.x, top: pos.y, zIndex: 9998, display: visible ? "block" : "none", userSelect: "none" }} onMouseDown={handleMouseDown}>
        <button onClick={(e) => { e.stopPropagation(); setVisible(false); }} title="隐藏角色"
          style={{ position: "absolute", top: 4, right: 4, zIndex: 10, width: 24, height: 24, borderRadius: "50%", border: "none", background: "rgba(0,0,0,0.35)", color: "#fff", fontSize: 14, cursor: "pointer", lineHeight: "24px", textAlign: "center", outline: "none" }}>×</button>
        {error ? (
          <div style={{ width: SIZE, height: SIZE, background: "rgba(0,0,0,0.05)", borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#999", fontSize: 14 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>🌸</div><div>3D 模型加载失败</div><div style={{ fontSize: 12, marginTop: 4 }}>{error}</div>
          </div>
        ) : (
          <div ref={viewRef} style={{ width: SIZE, height: SIZE, pointerEvents: "none" }} />
        )}
      </div>
    </>
  );
});

export default VRMCharacter;

import { useEffect, useRef, useState, memo } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { GLB_MODELS } from "../../types/vrm";

const SIZE = 640;

const VRMCharacter = memo(function VRMCharacter({ roleType }: { roleType: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<HTMLDivElement>(null);
  const vrmRef = useRef<any>(null);
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

    scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
    keyLight.position.set(1, 2, 3);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xffe8f0, 1.0);
    fillLight.position.set(-1, 0.5, 1);
    scene.add(fillLight);

    const loader = new GLTFLoader();
    loader.register((parser: any) => new VRMLoaderPlugin(parser));

    loader.load(
      config.path,
      (gltf: any) => {
        if (destroyed) return;
        const vrm = gltf.userData.vrm;
        if (!vrm) { setError("VRM 解析失败"); return; }
        // 自动适配大小 + 相机距离
        const box = new THREE.Box3().setFromObject(vrm.scene);
        const size = box.getSize(new THREE.Vector3());
        const targetHeight = 5.0;
        const fitScale = targetHeight / Math.max(size.y, 0.01);
        vrm.scene.scale.setScalar(fitScale);
        const halfFovRad = (FOV / 2) * (Math.PI / 180);
        const cameraZ = targetHeight / (2 * Math.tan(halfFovRad)) * 1.35;
        camera.position.set(0, 1.5, cameraZ);

        const halfH = size.y * fitScale / 2;
        const camBottom = camera.position.y - cameraZ * Math.tan(halfFovRad);
        const shift = Math.max(0, camBottom + halfH) + halfH * 0.15;
        const center = box.getCenter(new THREE.Vector3());
        vrm.scene.position.set(-center.x * fitScale, -center.y * fitScale + shift, -center.z * fitScale);

        // 手臂从 T-pose 下垂至约30° + 手指微弯
        vrm.scene.traverse((child: any) => {
          if (child.type !== "Bone") return;
          const n = child.name;
          if (n === "J_Bip_L_UpperArm") child.rotation.z = -1.0;
          if (n === "J_Bip_R_UpperArm") child.rotation.z = 1.0;
          if (n === "J_Bip_L_LowerArm") child.rotation.z = -0.15;
          if (n === "J_Bip_R_LowerArm") child.rotation.z = 0.15;
          // 手指弯曲（Z 轴正→手心方向，左手+ / 右手-）
          const isRight = n.includes("_R_");
          if (/Thumb0|Index0|Middle0|Ring0|Pinky0/.test(n)) child.rotation.z = isRight ? 0.4 : -0.4;
          if (/Thumb1|Index1|Middle1|Ring1|Pinky1/.test(n)) child.rotation.z = isRight ? 0.3 : -0.3;
        });
        vrm.humanoid.autoUpdateHumanBones = false;

        scene.add(vrm.scene);
        vrmRef.current = vrm;
        (window as any).__vrmModel = vrm;

        vrm.autoBlink = false;

        console.log("[VRM] 加载成功: %s", config.name, "blendShapes:", !!vrm.expressionManager);
      },
      (xhr: any) => { console.log("[VRM] 加载进度: %s", xhr?.loaded); },
      (err: any) => { console.error("[VRM] 加载失败:", err); if (!destroyed) setError(err?.message || "加载失败"); },
    );

    let animId = 0;
    const tick = () => {
      if (destroyed) return;
      const dt = clockRef.current.getDelta();
      if (vrmRef.current) vrmRef.current.update(dt);
      renderer.render(scene, camera);
      animId = requestAnimationFrame(tick);
    };
    animId = requestAnimationFrame(tick);

    return () => {
      destroyed = true;
      cancelAnimationFrame(animId);
      renderer.dispose();
      (window as any).__vrmModel = null;
    };
  }, [roleType]);

  return (
    <>
      <div style={{ position: "fixed", right: 16, top: 16, zIndex: 9998, width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,0.9)", boxShadow: "0 2px 8px rgba(0,0,0,0.15)", display: visible ? "none" : "flex", alignItems: "center", justifyContent: "center", fontSize: 20, cursor: "pointer" }} onClick={() => setVisible(true)} title="显示角色">🌸</div>
      <div ref={containerRef} style={{ position: "fixed", left: pos.x, top: pos.y, zIndex: 9998, display: visible ? "block" : "none", userSelect: "none" }} onMouseDown={handleMouseDown}>
        <button onClick={(e) => { e.stopPropagation(); setVisible(false); }} title="隐藏角色" style={{ position: "absolute", top: 4, right: 4, zIndex: 10, width: 24, height: 24, borderRadius: "50%", border: "none", background: "rgba(0,0,0,0.35)", color: "#fff", fontSize: 14, cursor: "pointer", lineHeight: "24px", textAlign: "center", outline: "none" }}>×</button>
        {error ? (
          <div style={{ width: SIZE, height: SIZE, background: "rgba(0,0,0,0.05)", borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#999", fontSize: 14 }}><div style={{ fontSize: 48, marginBottom: 8 }}>🌸</div><div>3D 模型加载失败</div><div style={{ fontSize: 12, marginTop: 4 }}>{error}</div></div>
        ) : (
          <div ref={viewRef} style={{ width: SIZE, height: SIZE, pointerEvents: "none" }} />
        )}
      </div>
    </>
  );
});

export default VRMCharacter;

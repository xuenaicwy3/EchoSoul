import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAffection } from "../api/client";
import { useRoleStore } from "../store/roleStore";

interface Task { id: number; name: string; description: string; completed: boolean; reward_intimacy: number; }
interface Achievement { id: number; name: string; description: string; progress: number; threshold: number; completed: boolean; }
interface Skin { id: number; name: string; description: string; role_type: string; equipped: boolean; }

export default function GamePage() {
  const navigate = useNavigate();
  const { selectedRole } = useRoleStore();

  const [intimacy, setIntimacy] = useState(0);
  const [trust, setTrust] = useState(0);
  const [fun, setFun] = useState(0);
  const [growth, setGrowth] = useState(0);
  const [level, setLevel] = useState(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [skins, setSkins] = useState<Skin[]>([]);

  useEffect(() => {
    const role = selectedRole || "日系动漫型";
    loadStatus(role);
    loadTasks(role);
    loadAchievements();
    loadSkins(role);
  }, [selectedRole]);

  const api = async (url: string, opts: RequestInit = {}) => {
    const token = localStorage.getItem("echosoul_token");
    return fetch(url, { ...opts, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...opts.headers } });
  };

  const loadStatus = async (role: string) => {
    try {
      const aff = await getAffection(role);
      setIntimacy(Math.round(aff.intimacy));
      setTrust(Math.round(aff.trust));
      setFun(Math.round(aff.fun));
      setGrowth(Math.round(aff.growth));
      setLevel(aff.level);
    } catch { /* ignore */ }
  };

  const loadTasks = async (role: string) => {
    try {
      const res = await api(`/game/daily-tasks?role_type=${encodeURIComponent(role)}`);
      if (res.ok) setTasks(await res.json());
    } catch { /* ignore */ }
  };

  const loadAchievements = async () => {
    try {
      const res = await api("/game/achievements");
      if (res.ok) setAchievements(await res.json());
    } catch { /* ignore */ }
  };

  const loadSkins = async (role: string) => {
    try {
      const res = await api(`/game/skins?role_type=${encodeURIComponent(role)}`);
      if (res.ok) setSkins(await res.json());
    } catch { /* ignore */ }
  };

  const completeTask = async (taskId: number) => {
    const role = selectedRole || "日系动漫型";
    try {
      await api(`/game/daily-tasks/${taskId}/complete?role_type=${encodeURIComponent(role)}`, { method: "POST" });
      loadTasks(role);
      loadStatus(role);
    } catch { /* ignore */ }
  };

  return (
    <div className="game-page">
      <div className="game-container">
        <div className="back-link">
          <a href="#" onClick={(e) => { e.preventDefault(); navigate("/chat"); }}>← 返回聊天</a>
        </div>

        {/* 养成状态 */}
        <div className="affection-status">
          <h3>💖 养成状态 {level > 0 && <span className="level-badge">Lv.{level}</span>}</h3>
          <p>亲密度：<span>{intimacy}</span></p>
          <p>信任度：<span>{trust}</span></p>
          <p>趣味度：<span>{fun}</span></p>
          <p>成长度：<span>{growth}</span></p>
        </div>

        {/* 每日任务 */}
        <div className="daily-tasks">
          <h3>📋 每日任务</h3>
          <ul>
            {tasks.length === 0 && <li className="empty-li">今日暂无任务</li>}
            {tasks.map((t) => (
              <li key={t.id}>
                <span>{t.name}{t.completed ? " ✅" : ""}</span>
                {!t.completed && (
                  <button onClick={() => completeTask(t.id)}>完成 +{t.reward_intimacy}💖</button>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* 成就 */}
        <div className="achievements">
          <h3>🏆 成就</h3>
          <ul>
            {achievements.length === 0 && <li className="empty-li">暂无成就</li>}
            {achievements.map((a) => (
              <li key={a.id}>
                <span>{a.name}{a.completed ? " ✅" : ""}</span>
                <progress value={a.progress} max={a.threshold} />
                <span className="progress-text">{a.progress}/{a.threshold}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* 角色皮肤 */}
        <div className="skins">
          <h3>🎨 角色皮肤</h3>
          <div className="skin-gallery">
            {skins.length === 0 && <p className="empty-text">暂无皮肤</p>}
            {skins.map((s) => (
              <div key={s.id} className={`skin-card ${s.equipped ? "equipped" : ""}`}>
                <p>{s.name}</p>
                <p className="skin-desc">{s.description}</p>
                {s.equipped ? <span className="equipped-tag">使用中</span> : <button>装备</button>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

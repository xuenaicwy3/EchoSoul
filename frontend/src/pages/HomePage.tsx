import { useNavigate } from "react-router-dom";
import { useRoleStore } from "../store/roleStore";
import { useAuthStore } from "../store/authStore";

const ROLES = [
  { type: "日系动漫型", name: "小樱", desc: "二次元少女，精通动漫，性格活泼。", emoji: "🌸", avatar: "avatar-sakura" },
  { type: "高冷御姐型", name: "雪乃", desc: "成熟冷静的职场精英，外表高冷内心细腻。", emoji: "❄️", avatar: "avatar-yukino" },
  { type: "傲娇辣妹型", name: "凛", desc: "嘴硬心软的傲娇少女，经常口是心非。", emoji: "🔥", avatar: "avatar-rin" },
  { type: "甜美校花型", name: "甜甜", desc: "温柔甜美的校园女神，善解人意。", emoji: "🍬", avatar: "avatar-tiantian" },
  { type: "软萌可爱型", name: "团子", desc: "软萌胆小，像小动物一样容易害羞。", emoji: "🐻", avatar: "avatar-dango" },
  { type: "温柔贤淑型", name: "结衣", desc: "温柔体贴的邻家大姐姐，善解人意。", emoji: "🌼", avatar: "avatar-ruolan" },
  { type: "元气少女型", name: "小葵", desc: "阳光开朗，活力四射的运动系少女。", emoji: "☀️", avatar: "avatar-genki" },
  { type: "清冷仙气型", name: "灵犀", desc: "出尘脱俗，不食人间烟火的仙气少女。", emoji: "🌙", avatar: "avatar-seisen" },
];

export default function HomePage() {
  const navigate = useNavigate();
  const { selectedRole, setRole } = useRoleStore();
  const { logout, username } = useAuthStore();

  const handleRoleClick = (roleType: string) => {
    setRole(roleType);
    if (selectedRole === roleType) navigate("/chat");
  };

  return (
    <div className="home-container">
      <div className="home-header">
        <span>{username}</span>
        <button onClick={logout}>退出</button>
      </div>

      <h1 className="home-title">💞 心流 EchoSoul</h1>
      <p className="home-subtitle">选择一位心流伴侣，开始你们的故事吧</p>

      <div className="role-cards">
        {ROLES.map((role) => (
          <div
            key={role.type}
            className={`role-card ${selectedRole === role.type ? "selected" : ""}`}
            onClick={() => handleRoleClick(role.type)}
          >
            <div className={`card-avatar ${role.avatar}`}>{role.emoji}</div>
            <div className="card-info">
              <div className="card-name">{role.name}</div>
              <div className="card-desc">{role.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <button
        className="enter-btn"
        disabled={!selectedRole}
        onClick={() => { if (selectedRole) navigate("/chat"); }}
      >
        {selectedRole ? "开始对话 →" : "↑ 请先点击上方角色卡片"}
      </button>

      <div className="home-nav">
        <a href="/game">游戏中心</a>
        <a href="/story">故事工坊</a>
      </div>
    </div>
  );
}

import { useNavigate } from "react-router-dom";

export default function MemoryPage() {
  const navigate = useNavigate();
  return (
    <div className="page-container">
      <div className="page-card">
        <h2>🧠 情感记忆</h2>
        <p>三层情感记忆查询 即将上线</p>
        <button onClick={() => navigate("/chat")}>返回聊天</button>
      </div>
    </div>
  );
}

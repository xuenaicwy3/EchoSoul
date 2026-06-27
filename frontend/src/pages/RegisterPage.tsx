import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { register } from "../api/client";
import { useAuthStore } from "../store/authStore";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 6) { setError("密码至少 6 位"); return; }
    setLoading(true);
    try {
      const data = await register(username, password);
      setAuth(data.access_token, data.user_id, username);
      navigate("/home");
    } catch {
      setError("注册失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h1 className="auth-title">💞 心流 EchoSoul</h1>
        <p className="auth-subtitle">创建你的账号</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="auth-form">
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名 (2-50 字符)" minLength={2} maxLength={50} required />
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码 (至少 6 位)" minLength={6} required />
            <button type="submit" disabled={loading}>{loading ? "注册中..." : "注 册"}</button>
          </div>
        </form>

        <div className="auth-toggle">
          <span>已有账号？</span>
          <Link to="/login">去登录</Link>
        </div>
      </div>
    </div>
  );
}

import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { login } from "../api/client";
import { useAuthStore } from "../store/authStore";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(username, password);
      setAuth(data.access_token, data.user_id, username);
      navigate("/home");
    } catch {
      setError("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h1 className="auth-title">💞 心流 EchoSoul</h1>
        <p className="auth-subtitle">登录你的账号</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="auth-form">
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名" required />
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" required />
            <button type="submit" disabled={loading}>{loading ? "登录中..." : "登 录"}</button>
          </div>
        </form>

        <div className="auth-toggle">
          <span>还没有账号？</span>
          <Link to="/register">立即注册</Link>
        </div>
      </div>
    </div>
  );
}

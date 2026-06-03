from locust import HttpUser, task, between

class ChatUser(HttpUser):
    wait_time = between(0.5, 2)  # 模拟用户思考时间

    def on_start(self):
        resp = self.client.post("/auth/login", json={
            "username": "天雾凌斗",
            "password": "123456"
        })
        data = resp.json()
        if "access_token" in data:
            self.token = data["access_token"]
        else:
            print(f"登录失败: {data}")
            self.token = None

    @task
    def send_message(self):
        if not self.token:
            return
        self.client.post(
            "/chat",
            json={"message": "测试消息", "role_type": "日系动漫型"},
            headers={"Authorization": f"Bearer {self.token}"}
        )
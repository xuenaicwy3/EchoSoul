import requests

# 先注册一个新用户
url_register = "http://127.0.0.1:8000/auth/register"
data = {"username": "demo", "password": "123456"}

resp = requests.post(url_register, json=data)
print("注册状态码:", resp.status_code)
try:
    print("注册结果:", resp.json())
except:
    print("注册失败，原始响应:", resp.text)

# 再尝试登录
url_login = "http://127.0.0.1:8000/auth/login"
resp2 = requests.post(url_login, json=data)
print("登录状态码:", resp2.status_code)
try:
    print("登录结果:", resp2.json())
except:
    print("登录失败，原始响应:", resp2.text)
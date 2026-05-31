"""
查看聊天历史工具
用法：python view_chat_history.py [user_id]
如果不提供 user_id，则显示所有用户的记录概览。
"""
import sys
from langchain_chroma import Chroma
from langchain_core.embeddings import FakeEmbeddings

def main():
    if len(sys.argv) < 2:
        print("请提供 user_id，例如: python view_chat_history.py  web_user_4gdajwcq 日系动漫型")
        return

    user_id = sys.argv[1]
    print("user_id: ", user_id)
    role_filter = sys.argv[2] if len(sys.argv) > 2 else None
    print("role_filter: ", role_filter)

    # 使用与 chat_history.py 相同的方式初始化（FakeEmbeddings + 已有集合）
    embeddings = FakeEmbeddings(size=1)
    store = Chroma(
        collection_name="chat_history",
        embedding_function=embeddings,
        persist_directory="./chroma_data",
    )
    collection = store._collection  # 获取底层 Chroma 集合

    where = {"user_id": user_id}
    if role_filter:
        where = {"$and": [{"user_id": user_id}, {"role_type": role_filter}]}
    else:
        all_meta = collection.get(where={"user_id": user_id}, include=["metadatas"])
        roles = set()
        if all_meta["metadatas"]:
            for meta in all_meta["metadatas"]:
                if meta:
                    roles.add(meta["role_type"])
        print(f"用户 {user_id} 拥有角色: {', '.join(roles) if roles else '无'}\n")
        where = {"user_id": user_id}

    results = collection.get(where=where, include=["documents", "metadatas"])

    if not results["ids"]:
        print("该用户/角色下暂无聊天记录。")
        return

    messages = []
    for doc, meta in zip(results["documents"] or [], results["metadatas"] or []):
        messages.append({
            "sender": meta["sender"],
            "message": doc,
            "timestamp": meta["timestamp"]
        })
    messages.sort(key=lambda x: x["timestamp"])

    if role_filter:
        print(f"用户 {user_id} 与 {role_filter} 的聊天记录：\n")
    else:
        print(f"用户 {user_id} 的所有聊天记录：\n")

    for msg in messages:
        sender_name = "用户" if msg["sender"] == "user" else "AI"
        time_str = msg["timestamp"][:19].replace("T", " ")
        print(f"[{time_str}] {sender_name}: {msg['message']}")


if __name__ == "__main__":
    main()

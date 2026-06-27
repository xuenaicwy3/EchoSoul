export default function MessageBubble({ message }: { message: { sender: string; text: string } }) {
  const isUser = message.sender === "user";
  return (
    <div className={`message ${isUser ? "user" : "ai"}`}>
      <div className={`bubble ${isUser ? "user" : "ai"}`}>{message.text}</div>
    </div>
  );
}

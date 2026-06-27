import { useState, type FormEvent, type KeyboardEvent } from "react";

interface Props { onSend: (text: string) => void; disabled?: boolean; }

export default function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(e as unknown as FormEvent); }
  };

  return (
    <form className="chat-input-area" onSubmit={submit}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown} placeholder="输入消息... (Enter 发送)" rows={1} disabled={disabled} />
      <button type="submit" disabled={disabled || !text.trim()}>发送</button>
    </form>
  );
}

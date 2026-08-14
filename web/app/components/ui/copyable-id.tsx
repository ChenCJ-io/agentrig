import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function CopyableId({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const short = value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value;

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }

  return (
    <button className="copyable-id" onClick={() => void copy()} title={`复制${label ?? "标识"}：${value}`} type="button">
      <code>{short}</code>
      {copied ? <Check size={12} /> : <Copy size={12} />}
      <span className="sr-only">复制{label ?? "标识"}</span>
    </button>
  );
}

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { useState } from "react";

function CodeBlock(props: any) {
  const [copied, setCopied] = useState(false);
  const text = String(props.children?.props?.children ?? "");
  return (
    <div className="group relative">
      <pre {...props} />
      <button className="btn-ghost absolute right-1 top-1 text-xs opacity-0 group-hover:opacity-100 focus:opacity-100"
        onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={{ pre: CodeBlock }}>{text}</ReactMarkdown>
    </div>
  );
}

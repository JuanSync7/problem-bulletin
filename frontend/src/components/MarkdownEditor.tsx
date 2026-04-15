import React from "react";
import "./MarkdownEditor.css";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minLength?: number;
  maxLength?: number;
}

/**
 * Simple regex-based markdown to HTML renderer.
 * Handles: headings, bold, italic, inline code, code blocks, links, lists, blockquotes.
 */
export function renderMarkdown(md: string): string {
  if (!md.trim()) return "";

  let html = md;

  // Escape HTML entities first
  html = html
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks (``` ... ```)
  html = html.replace(/```([\s\S]*?)```/g, (_match, code: string) => {
    return `<pre><code>${code.trim()}</code></pre>`;
  });

  // Inline code (`...`)
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Horizontal rule (---, ***, ___)
  html = html.replace(/^[-*_]{3,}\s*$/gm, "<hr />");

  // Headings (### h3, ## h2, # h1)
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, "<blockquote><p>$1</p></blockquote>");

  // Bold (**text**)
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Italic (*text*)
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Links [text](url)
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Unordered lists (lines starting with - or *)
  html = html.replace(/^(?:- |\* )(.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

  // Ordered lists (lines starting with 1. 2. etc.)
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  // Wrap consecutive <li> that aren't already inside <ul>
  html = html.replace(
    /(<li>.*<\/li>\n?)(?!<\/ul>)/g,
    (match) => {
      // If already wrapped in ul, skip
      return match;
    }
  );

  // Paragraphs: wrap remaining lines that aren't already wrapped
  const lines = html.split("\n");
  const result: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      result.push("");
      continue;
    }
    if (
      trimmed.startsWith("<h") ||
      trimmed.startsWith("<hr") ||
      trimmed.startsWith("<pre") ||
      trimmed.startsWith("<ul") ||
      trimmed.startsWith("<ol") ||
      trimmed.startsWith("<li") ||
      trimmed.startsWith("</") ||
      trimmed.startsWith("<blockquote")
    ) {
      result.push(trimmed);
    } else {
      result.push(`<p>${trimmed}</p>`);
    }
  }

  return result.join("\n");
}

export default function MarkdownEditor({
  value,
  onChange,
  placeholder = "Write your description...",
  minLength,
  maxLength,
}: MarkdownEditorProps) {
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = maxLength ? e.target.value.slice(0, maxLength) : e.target.value;
    onChange(next);
  };

  return (
    <div className="md-editor">
      <textarea
        className="md-editor__input"
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
        aria-label="Description editor"
      />
      <div className="md-editor__footer">
        <span className="md-editor__char-count">
          {value.length}
          {maxLength ? ` / ${maxLength}` : ""}
          {minLength && value.length < minLength
            ? ` (min ${minLength})`
            : ""}
        </span>
      </div>
    </div>
  );
}

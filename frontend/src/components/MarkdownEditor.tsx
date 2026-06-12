import React, { useRef, useState, useCallback } from "react";
import "./MarkdownEditor.css";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minLength?: number;
  maxLength?: number;
  minHeight?: string;
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
  minHeight,
}: MarkdownEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [redoStack, setRedoStack] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<"write" | "split" | "preview">("split");

  const pushHistory = useCallback((prev: string) => {
    setHistory((h) => [...h.slice(-99), prev]);
    setRedoStack([]);
  }, []);

  const commit = useCallback(
    (next: string) => {
      pushHistory(value);
      onChange(maxLength ? next.slice(0, maxLength) : next);
    },
    [value, maxLength, onChange, pushHistory],
  );

  const handleUndo = useCallback(() => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setRedoStack((r) => [...r, value]);
      onChange(prev);
      return h.slice(0, -1);
    });
  }, [value, onChange]);

  const handleRedo = useCallback(() => {
    setRedoStack((r) => {
      if (r.length === 0) return r;
      const next = r[r.length - 1];
      setHistory((h) => [...h, value]);
      onChange(next);
      return r.slice(0, -1);
    });
  }, [value, onChange]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const raw = maxLength ? e.target.value.slice(0, maxLength) : e.target.value;
    pushHistory(value);
    onChange(raw);
  };

  function wrapSelection(before: string, after: string = before, placeholder = "text") {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = value.slice(start, end) || placeholder;
    const next = value.slice(0, start) + before + selected + after + value.slice(end);
    commit(next);
    requestAnimationFrame(() => {
      ta.focus();
      const cursor = start + before.length;
      ta.setSelectionRange(cursor, cursor + selected.length);
    });
  }

  function prefixLines(prefix: string) {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const before = value.slice(0, lineStart);
    const target = value.slice(lineStart, end);
    const after = value.slice(end);
    const replaced = target
      .split("\n")
      .map((l) => (l.startsWith(prefix) ? l : prefix + l))
      .join("\n");
    const next = before + replaced + after;
    commit(next);
    requestAnimationFrame(() => ta.focus());
  }

  function insertLink() {
    const ta = textareaRef.current;
    if (!ta) return;
    const url = prompt("Enter URL:", "https://");
    if (!url) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = value.slice(start, end) || "link text";
    const insert = `[${selected}](${url})`;
    const next = value.slice(0, start) + insert + value.slice(end);
    commit(next);
    requestAnimationFrame(() => ta.focus());
  }

  return (
    <div className="md-editor">
      <div className="md-editor__toolbar" role="toolbar" aria-label="Formatting">
        <button
          type="button"
          className="md-editor__tool"
          title="Undo (Ctrl+Z)"
          onClick={handleUndo}
          disabled={history.length === 0}
        >
          ↶
        </button>
        <button
          type="button"
          className="md-editor__tool"
          title="Redo (Ctrl+Shift+Z)"
          onClick={handleRedo}
          disabled={redoStack.length === 0}
        >
          ↷
        </button>
        <span className="md-editor__sep" />
        <button type="button" className="md-editor__tool" title="Heading 1" onClick={() => prefixLines("# ")}>
          <strong>H1</strong>
        </button>
        <button type="button" className="md-editor__tool" title="Heading 2" onClick={() => prefixLines("## ")}>
          <strong>H2</strong>
        </button>
        <button type="button" className="md-editor__tool" title="Heading 3" onClick={() => prefixLines("### ")}>
          <strong>H3</strong>
        </button>
        <span className="md-editor__sep" />
        <button type="button" className="md-editor__tool" title="Bold (**text**)" onClick={() => wrapSelection("**")}>
          <strong>B</strong>
        </button>
        <button type="button" className="md-editor__tool" title="Italic (*text*)" onClick={() => wrapSelection("*")}>
          <em>I</em>
        </button>
        <button type="button" className="md-editor__tool" title="Strikethrough (~~text~~)" onClick={() => wrapSelection("~~")}>
          <span style={{ textDecoration: "line-through" }}>S</span>
        </button>
        <button type="button" className="md-editor__tool" title="Inline code (`code`)" onClick={() => wrapSelection("`")}>
          {"<>"}
        </button>
        <span className="md-editor__sep" />
        <button type="button" className="md-editor__tool" title="Bulleted list" onClick={() => prefixLines("- ")}>
          • List
        </button>
        <button type="button" className="md-editor__tool" title="Numbered list" onClick={() => prefixLines("1. ")}>
          1. List
        </button>
        <button type="button" className="md-editor__tool" title="Quote" onClick={() => prefixLines("> ")}>
          “”
        </button>
        <span className="md-editor__sep" />
        <button type="button" className="md-editor__tool" title="Link" onClick={insertLink}>
          🔗
        </button>
        <button type="button" className="md-editor__tool" title="Code block" onClick={() => wrapSelection("\n```\n", "\n```\n", "code")}>
          {"{ }"}
        </button>
        <span className="md-editor__sep" />
        <div className="md-editor__view-toggle" role="group" aria-label="View mode">
          <button
            type="button"
            className={`md-editor__tool${viewMode === "write" ? " md-editor__tool--active" : ""}`}
            title="Write only"
            onClick={() => setViewMode("write")}
          >
            Write
          </button>
          <button
            type="button"
            className={`md-editor__tool${viewMode === "split" ? " md-editor__tool--active" : ""}`}
            title="Split view"
            onClick={() => setViewMode("split")}
          >
            Split
          </button>
          <button
            type="button"
            className={`md-editor__tool${viewMode === "preview" ? " md-editor__tool--active" : ""}`}
            title="Preview only"
            onClick={() => setViewMode("preview")}
          >
            Preview
          </button>
        </div>
      </div>
      <div
        className={`md-editor__panes md-editor__panes--${viewMode}`}
        style={minHeight ? { minHeight } : undefined}
      >
        {viewMode !== "preview" && (
          <textarea
            ref={textareaRef}
            className="md-editor__input"
            value={value}
            onChange={handleChange}
            placeholder={placeholder}
            aria-label="Description editor"
            style={minHeight ? { minHeight } : undefined}
          />
        )}
        {viewMode !== "write" && (
          <div
            className={`md-editor__preview${!value.trim() ? " md-editor__preview--empty" : ""}`}
            style={minHeight ? { minHeight } : undefined}
            aria-label="Preview"
          >
            {value.trim() ? (
              <div dangerouslySetInnerHTML={{ __html: renderMarkdown(value) }} />
            ) : (
              "Nothing to preview yet."
            )}
          </div>
        )}
      </div>
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

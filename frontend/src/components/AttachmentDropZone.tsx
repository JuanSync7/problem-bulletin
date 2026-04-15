import React, { useState, useRef, useCallback, useEffect } from "react";
import "./AttachmentDropZone.css";

interface AttachmentFile {
  file: File;
  id: string;
}

interface AttachmentDropZoneProps {
  files: AttachmentFile[];
  onChange: (files: AttachmentFile[]) => void;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const ALLOWED_TYPES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/svg+xml",
  "application/pdf",
  "text/plain",
];

function isAllowedType(file: File): boolean {
  if (file.type.startsWith("image/")) return true;
  return ALLOWED_TYPES.includes(file.type);
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(type: string): string {
  if (type.startsWith("image/")) return "\u{1f5bc}";
  if (type === "application/pdf") return "\u{1f4c4}";
  return "\u{1f4c3}";
}

let attachmentIdCounter = 0;

export default function AttachmentDropZone({
  files,
  onChange,
}: AttachmentDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      setError(null);
      const newFiles: AttachmentFile[] = [];
      const errors: string[] = [];

      for (const file of Array.from(incoming)) {
        if (file.size > MAX_FILE_SIZE) {
          errors.push(`${file.name} exceeds 10MB limit`);
          continue;
        }
        if (!isAllowedType(file)) {
          errors.push(`${file.name} has an unsupported file type`);
          continue;
        }
        newFiles.push({
          file,
          id: `attachment-${++attachmentIdCounter}`,
        });
      }

      if (errors.length > 0) {
        setError(errors.join(". "));
      }

      if (newFiles.length > 0) {
        onChange([...files, ...newFiles]);
      }
    },
    [files, onChange]
  );

  const removeFile = (id: string) => {
    onChange(files.filter((f) => f.id !== id));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  };

  const handleClick = () => {
    inputRef.current?.click();
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
    }
    // Reset so the same file can be selected again
    e.target.value = "";
  };

  // Paste handler for clipboard images
  useEffect(() => {
    function handlePaste(e: ClipboardEvent) {
      const items = e.clipboardData?.items;
      if (!items) return;
      const pastedFiles: File[] = [];
      for (const item of Array.from(items)) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      if (pastedFiles.length > 0) {
        addFiles(pastedFiles);
      }
    }
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [addFiles]);

  return (
    <div>
      <div
        className={`dropzone${isDragOver ? " dropzone--dragover" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleClick();
          }
        }}
        aria-label="Upload attachments"
      >
        <span className="dropzone__label">
          Drag files here or click to upload
          <span className="dropzone__sublabel">
            Images, PDF, TXT — max 10MB each
          </span>
        </span>
        <input
          ref={inputRef}
          type="file"
          className="dropzone__input"
          multiple
          accept="image/*,.pdf,.txt"
          onChange={handleInputChange}
          tabIndex={-1}
        />
      </div>

      {error && <p className="dropzone__error">{error}</p>}

      {files.length > 0 && (
        <ul className="dropzone__file-list">
          {files.map((af) => (
            <li key={af.id} className="dropzone__file-item">
              <span className="dropzone__file-icon">
                {getFileIcon(af.file.type)}
              </span>
              <span className="dropzone__file-name">{af.file.name}</span>
              <span className="dropzone__file-size">
                {formatFileSize(af.file.size)}
              </span>
              <button
                type="button"
                className="dropzone__file-remove"
                onClick={() => removeFile(af.id)}
                aria-label={`Remove ${af.file.name}`}
              >
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

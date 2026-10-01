import { ImagePlus, X } from "lucide-react";
import { useRef } from "react";

export function FileDrop({
  label,
  file,
  onChange,
  storedUrl,
  storedName,
}: {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
  storedUrl?: string;
  storedName?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const previewUrl = file ? URL.createObjectURL(file) : storedUrl;
  const displayName = file?.name ?? storedName;
  return (
    <div
      className={`drop ${previewUrl ? "has-file" : ""}`}
      onClick={() => input.current?.click()}
    >
      <input
        ref={input}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      {previewUrl ? (
        <>
          <img src={previewUrl} alt={label} />
          <button
            aria-label="ลบภาพ"
            onClick={(event) => {
              event.stopPropagation();
              onChange(null);
            }}
          >
            <X size={18} />
          </button>
          <div className="file-meta">
            <strong>{label}</strong>
            <span>{displayName}</span>
          </div>
        </>
      ) : (
        <>
          <ImagePlus size={34} />
          <strong>{label}</strong>
          <span>ลากภาพมาวาง หรือคลิกเพื่อเลือก</span>
          <small>JPG, PNG, WebP สูงสุด 20 MB</small>
        </>
      )}
    </div>
  );
}

import { ImagePlus, X } from "lucide-react";
import { useRef } from "react";

export function FileDrop({ label, file, onChange }: { label: string; file: File | null; onChange: (file: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return <div className={`drop ${file ? "has-file" : ""}`} onClick={() => input.current?.click()}>
    <input ref={input} type="file" accept="image/*" hidden onChange={event => onChange(event.target.files?.[0] ?? null)}/>
    {file ? <>
      <img src={URL.createObjectURL(file)} alt={label}/>
      <button aria-label="ลบภาพ" onClick={event => { event.stopPropagation(); onChange(null); }}><X size={18}/></button>
      <div className="file-meta"><strong>{label}</strong><span>{file.name}</span></div>
    </> : <><ImagePlus size={34}/><strong>{label}</strong><span>ลากภาพมาวาง หรือคลิกเพื่อเลือก</span><small>JPG, PNG, WebP สูงสุด 20 MB</small></>}
  </div>;
}


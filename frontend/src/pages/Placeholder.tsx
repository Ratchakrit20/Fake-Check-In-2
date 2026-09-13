export function Placeholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">Image Relation Inspector</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>
      <div className="empty panel">
        <div className="empty-mark">IR</div>
        <h2>ยังไม่มีข้อมูล</h2>
        <p>ข้อมูลจะปรากฏที่นี่เมื่อมีการวิเคราะห์ภาพ</p>
      </div>
    </section>
  );
}

import { Images, LayoutDashboard, Layers3, ScanSearch, Settings } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const items = [
  ["/", "ภาพรวม", LayoutDashboard],
  ["/compare", "เปรียบเทียบภาพ", ScanSearch],
  ["/batch", "วิเคราะห์หลายภาพ", Images],
  ["/groups", "กลุ่มภาพสัมพันธ์", Layers3],
  ["/settings", "การตั้งค่า", Settings],
] as const;

export function Layout() {
  return <div className="shell">
    <aside>
      <div className="brand"><span className="brand-mark">FC</span><div><strong>Fake Check-In</strong><small>IMAGE FORENSICS</small></div></div>
      <nav>{items.map(([to, label, Icon]) => <NavLink key={to} to={to} end={to === "/"}><Icon size={19}/><span>{label}</span></NavLink>)}</nav>
      <div className="status"><span/><div><strong>ระบบพร้อมใช้งาน</strong><small>SSCD + geometry</small></div></div>
    </aside>
    <main><Outlet /></main>
  </div>;
}


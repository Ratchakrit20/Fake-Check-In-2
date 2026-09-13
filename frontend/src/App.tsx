import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Batch } from "./pages/Batch";
import { Compare } from "./pages/Compare";
import { Dashboard } from "./pages/Dashboard";
import { Groups } from "./pages/Groups";
import { Placeholder } from "./pages/Placeholder";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="compare" element={<Compare />} />
        <Route path="batch" element={<Batch />} />
        <Route path="groups" element={<Groups />} />
        <Route
          path="settings"
          element={
            <Placeholder
              title="การตั้งค่า"
              description="ตรวจสอบโมเดล เวอร์ชัน และเกณฑ์ที่ระบบกำลังใช้งาน"
            />
          }
        />
      </Route>
    </Routes>
  );
}

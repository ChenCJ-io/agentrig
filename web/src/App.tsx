import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CaseEditor from "./pages/CaseEditor";
import Overview from "./pages/Overview";
import Placeholder from "./pages/Placeholder";
import RunDetail from "./pages/RunDetail";
import TestCases from "./pages/TestCases";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/cases" element={<TestCases />} />
        <Route path="/cases/new" element={<CaseEditor />} />
        <Route path="/cases/:id" element={<CaseEditor />} />
        <Route path="/cases/:id/run" element={<RunDetail />} />
        <Route path="/runs" element={<Overview />} />
        <Route path="*" element={<Placeholder />} />
      </Route>
    </Routes>
  );
}

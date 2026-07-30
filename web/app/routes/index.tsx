import { Navigate } from "react-router";

// 单 agent：根路径直接进评测总览
export default function IndexRoute() {
  return <Navigate to="/evaluation/overview" replace />;
}

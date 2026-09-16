import { index, layout, route, type RouteConfig } from "@react-router/dev/routes";

export default [
  layout("layouts/app-layout.tsx", [
    index("routes/index.tsx"),
    route("*", "routes/workspace.tsx"),
  ]),
] satisfies RouteConfig;

import { Outlet } from "react-router";

import { AppShell } from "~/components/shell/app-shell";

export default function AppLayout() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { getCurrentUser } from "@/lib/server/api";

// Every page in this group needs a valid session; the role comes fresh from the API.
export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login?expired=1");
  return <AppShell user={user}>{children}</AppShell>;
}

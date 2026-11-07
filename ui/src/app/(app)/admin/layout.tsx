import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/server/api";

// Admin pages are checked on the server: non-admins never receive them (the API also
// refuses every /admin call with 403).
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (user.role !== "admin") redirect("/");
  return <>{children}</>;
}

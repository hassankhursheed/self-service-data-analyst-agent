import { PageHeader } from "@/components/app-shell";
import { UsersAdmin } from "@/components/admin/users-admin";

export default function UsersPage() {
  return (
    <>
      <PageHeader title="Users" description="Create accounts, assign roles and regions, disable access and reset passwords." />
      <UsersAdmin />
    </>
  );
}

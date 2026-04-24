import { redirect } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { fetchBackend } from "@/lib/api-server";
import type { User } from "@/lib/types";

async function loadUser(): Promise<User | null> {
  try {
    const res = await fetchBackend("/auth/me");
    if (!res.ok) return null;
    const data = (await res.json()) as User;
    if (!data || typeof data.user_id !== "number") return null;
    return data;
  } catch {
    return null;
  }
}

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await loadUser();
  if (!user) redirect("/login");
  return <AppShell user={user}>{children}</AppShell>;
}

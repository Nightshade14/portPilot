"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AUTH_COOKIE_NAME, checkPasscode, signPasscode } from "@/lib/auth";

export async function loginAction(formData: FormData): Promise<void> {
  const passcode = String(formData.get("passcode") ?? "");
  const next = String(formData.get("next") ?? "/");

  if (!checkPasscode(passcode)) {
    redirect(`/login?next=${encodeURIComponent(next)}&error=1`);
  }

  const cookieStore = await cookies();
  cookieStore.set(AUTH_COOKIE_NAME, await signPasscode(passcode), {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });

  redirect(next.startsWith("/") ? next : "/");
}

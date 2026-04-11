import { getSupabaseClient } from "./supabase";

export async function ensureAuthenticatedOrRedirect(
  redirectTo = "/login"
): Promise<boolean> {
  const supabase = getSupabaseClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    if (typeof window !== "undefined") {
      window.location.href = redirectTo;
    }
    return false;
  }

  return true;
}

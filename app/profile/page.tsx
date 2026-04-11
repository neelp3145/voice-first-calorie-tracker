"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ensureAuthenticatedOrRedirect } from "../../lib/auth";
import { getAccessToken, getSupabaseClient } from "../../lib/supabase";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ProfileSnapshot = {
  name: string;
  email: string;
  dailyCalories: string;
  proteinGoal: string;
  carbGoal: string;
  fatGoal: string;
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

export default function ProfilePage() {
  const [name, setName] = useState("Dev Bollam");
  const [email, setEmail] = useState("dev@example.com");
  const [dailyCalories, setDailyCalories] = useState("2300");
  const [proteinGoal, setProteinGoal] = useState("180");
  const [carbGoal, setCarbGoal] = useState("220");
  const [fatGoal, setFatGoal] = useState("70");
  const [goal, setGoal] = useState("Lean Bulk");
  const [diet, setDiet] = useState("High Protein");
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [snapshot, setSnapshot] = useState<ProfileSnapshot | null>(null);

  useEffect(() => {
    const init = async () => {
      const isAuthenticated = await ensureAuthenticatedOrRedirect();
      if (!isAuthenticated) return;

      try {
        const accessToken = await getAccessToken();
        if (!accessToken) {
          window.location.href = "/login";
          return;
        }

        const supabase = getSupabaseClient();
        const {
          data: { user },
        } = await supabase.auth.getUser();

        const response = await fetch(`${API_BASE_URL}/api/profile`, {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        });

        if (!response.ok) {
          throw new Error(`Failed to load profile (${response.status})`);
        }

        const data = await response.json();
        const loadedName = data.full_name ?? user?.user_metadata?.full_name ?? "";
        const loadedEmail = user?.email ?? "";
        const loadedDailyCalories = String(data.daily_calorie_goal ?? 2300);

        setName(loadedName || "User");
        setEmail(loadedEmail || "");
        setDailyCalories(loadedDailyCalories);
        setProteinGoal(String(data.protein_goal_g ?? 180));
        setCarbGoal(String(data.carb_goal_g ?? 220));
        setFatGoal(String(data.fat_goal_g ?? 70));

        setSnapshot({
          name: loadedName || "User",
          email: loadedEmail || "",
          dailyCalories: loadedDailyCalories,
          proteinGoal: String(data.protein_goal_g ?? 180),
          carbGoal: String(data.carb_goal_g ?? 220),
          fatGoal: String(data.fat_goal_g ?? 70),
        });
      } catch (error: unknown) {
        setStatusMessage(getErrorMessage(error, "Failed to load profile."));
      } finally {
        setIsLoading(false);
      }
    };

    init();
  }, []);

  const handleCancel = () => {
    if (snapshot) {
      setName(snapshot.name);
      setEmail(snapshot.email);
      setDailyCalories(snapshot.dailyCalories);
      setProteinGoal(snapshot.proteinGoal);
      setCarbGoal(snapshot.carbGoal);
      setFatGoal(snapshot.fatGoal);
    }
    setGoal("Lean Bulk");
    setDiet("High Protein");
    setIsEditing(false);
    setStatusMessage("");
  };

  const handleSave = async () => {
    setStatusMessage("");
    setIsSaving(true);

    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        throw new Error("Your session has expired. Please sign in again.");
      }

      const response = await fetch(`${API_BASE_URL}/api/profile`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          full_name: name,
          daily_calorie_goal: Number.parseInt(dailyCalories, 10) || 2300,
          protein_goal_g: Number.parseInt(proteinGoal, 10) || 0,
          carb_goal_g: Number.parseInt(carbGoal, 10) || 0,
          fat_goal_g: Number.parseInt(fatGoal, 10) || 0,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail ?? `Failed to save profile (${response.status})`);
      }

      const saved = await response.json();
      const nextSnapshot = {
        name: saved.full_name ?? name,
        email,
        dailyCalories: String(saved.daily_calorie_goal ?? dailyCalories),
        proteinGoal: String(saved.protein_goal_g ?? proteinGoal),
        carbGoal: String(saved.carb_goal_g ?? carbGoal),
        fatGoal: String(saved.fat_goal_g ?? fatGoal),
      };

      setName(nextSnapshot.name);
      setDailyCalories(nextSnapshot.dailyCalories);
      setProteinGoal(nextSnapshot.proteinGoal);
      setCarbGoal(nextSnapshot.carbGoal);
      setFatGoal(nextSnapshot.fatGoal);
      setSnapshot(nextSnapshot);
      setIsEditing(false);
      setStatusMessage("Profile saved.");
    } catch (error: unknown) {
      setStatusMessage(getErrorMessage(error, "Failed to save profile."));
    } finally {
      setIsSaving(false);
    }
  };

  const handleLogout = async () => {
    const supabase = getSupabaseClient();
    await supabase.auth.signOut();
    window.location.href = "/login";
  };

  return (
    <main className="relative min-h-screen overflow-x-hidden bg-gradient-to-b from-[#0b1220] via-[#0b1220] to-[#07121a] text-white">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-20 left-1/2 h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-emerald-500/15 blur-[140px]" />
        <div className="absolute top-40 left-0 h-[360px] w-[360px] rounded-full bg-sky-500/10 blur-[120px]" />
        <div className="absolute bottom-10 right-0 h-[420px] w-[420px] rounded-full bg-emerald-500/10 blur-[140px]" />
      </div>

      {/* Navbar */}
      <header className="relative z-20 mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Link href="/" className="flex items-center gap-3">
          <Image
            src="/vocalorie-icon.PNG"
            alt="Vocalorie"
            width={150}
            height={150}
            className="object-contain drop-shadow-[0_0_14px_rgba(16,185,129,0.45)]"
            priority
          />
          <div className="leading-tight">
            <p className="text-sm text-white/70">Voice-first calorie tracking</p>
            <p className="text-lg font-semibold tracking-tight text-white">
              Vocalorie
            </p>
          </div>
        </Link>

        <nav className="hidden items-center gap-6 text-sm text-white/70 md:flex">
          <Link href="/" className="hover:text-white">
            Home
          </Link>
          <Link href="/logger" className="hover:text-white">
            Logger
          </Link>
          <Link href="/journal" className="hover:text-white">
            Journal
          </Link>
          <Link href="/profile" className="text-emerald-300">
            Profile
          </Link>
        </nav>

        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="rounded-full bg-white/10 px-4 py-2 text-sm text-white ring-1 ring-white/15 hover:bg-white/15"
          >
            Sign in
          </Link>
        </div>
      </header>

      {/* Page Content */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 pb-20 pt-8">
        <div className="mb-10 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-emerald-300/80">
              Profile
            </p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight md:text-5xl">
              Your account
            </h1>
            <p className="mt-4 max-w-2xl text-lg text-white/70">
              Manage your goals, nutrition targets, and personal preferences.
            </p>
          </div>

          <div className="flex gap-3">
            {!isEditing ? (
              <button
                onClick={() => setIsEditing(true)}
                className="rounded-full bg-emerald-500 px-5 py-3 text-sm font-semibold text-[#08131a] transition hover:bg-emerald-400"
                disabled={isLoading}
              >
                Edit Profile
              </button>
            ) : (
              <>
                <button
                  onClick={handleSave}
                  className="rounded-full bg-emerald-500 px-5 py-3 text-sm font-semibold text-[#08131a] transition hover:bg-emerald-400 disabled:opacity-60"
                  disabled={isSaving}
                >
                  {isSaving ? "Saving..." : "Save Changes"}
                </button>
                <button
                  onClick={handleCancel}
                  className="rounded-full bg-white/10 px-5 py-3 text-sm font-semibold text-white ring-1 ring-white/15 transition hover:bg-white/15"
                  disabled={isSaving}
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </div>

        {statusMessage ? (
          <p className="mb-6 rounded-2xl bg-black/20 px-4 py-3 text-sm text-white/80 ring-1 ring-white/10">
            {statusMessage}
          </p>
        ) : null}

        <div className="grid gap-8 lg:grid-cols-[0.9fr_1.1fr]">
          {/* Left side */}
          <div className="space-y-6">
            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <div className="flex items-center gap-4">
                <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-500/15 ring-1 ring-emerald-500/20">
                  <span className="text-2xl font-semibold text-emerald-300">
                    {name.charAt(0)}
                  </span>
                </div>
                <div>
                  <p className="text-sm text-white/60">Account holder</p>
                  <h2 className="mt-1 text-2xl font-semibold">{name}</h2>
                  <p className="mt-1 text-sm text-white/60">{email}</p>
                </div>
              </div>
            </div>

            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <p className="text-sm text-white/60">Quick overview</p>
              <div className="mt-6 grid grid-cols-2 gap-4">
                <StatCard label="Daily goal" value={`${dailyCalories} kcal`} />
                <StatCard label="Protein goal" value={`${proteinGoal}g`} />
                <StatCard label="Goal type" value={goal} />
                <StatCard label="Diet style" value={diet} />
              </div>
            </div>

            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <p className="text-sm text-white/60">Account actions</p>
              <div className="mt-5 space-y-3">
                <button className="w-full rounded-2xl bg-white/10 px-4 py-3 text-left text-sm text-white ring-1 ring-white/10 transition hover:bg-white/15">
                  Notification settings
                </button>
                <button className="w-full rounded-2xl bg-white/10 px-4 py-3 text-left text-sm text-white ring-1 ring-white/10 transition hover:bg-white/15">
                  Connected devices
                </button>
                <button
                  onClick={handleLogout}
                  className="w-full rounded-2xl bg-red-500/10 px-4 py-3 text-left text-sm text-red-300 ring-1 ring-red-500/20 transition hover:bg-red-500/15"
                >
                  Log out
                </button>
              </div>
            </div>
          </div>

          {/* Right side */}
          <div className="space-y-6">
            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <p className="text-sm text-white/60">Personal info</p>
              <h2 className="mt-1 text-2xl font-semibold">Basic details</h2>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <Field
                  label="Full name"
                  value={name}
                  editable={isEditing}
                  onChange={setName}
                />
                <Field
                  label="Email"
                  value={email}
                  editable={isEditing}
                  onChange={setEmail}
                />
              </div>
            </div>

            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <p className="text-sm text-white/60">Nutrition targets</p>
              <h2 className="mt-1 text-2xl font-semibold">Daily goals</h2>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <Field
                  label="Calories"
                  value={dailyCalories}
                  editable={isEditing}
                  onChange={setDailyCalories}
                />
                <Field
                  label="Protein (g)"
                  value={proteinGoal}
                  editable={isEditing}
                  onChange={setProteinGoal}
                />
                <Field
                  label="Carbs (g)"
                  value={carbGoal}
                  editable={isEditing}
                  onChange={setCarbGoal}
                />
                <Field
                  label="Fats (g)"
                  value={fatGoal}
                  editable={isEditing}
                  onChange={setFatGoal}
                />
              </div>
            </div>

            <div className="rounded-[32px] bg-white/5 p-6 ring-1 ring-white/10 backdrop-blur">
              <p className="text-sm text-white/60">Lifestyle preferences</p>
              <h2 className="mt-1 text-2xl font-semibold">Profile settings</h2>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <Field
                  label="Fitness goal"
                  value={goal}
                  editable={isEditing}
                  onChange={setGoal}
                />
                <Field
                  label="Diet preference"
                  value={diet}
                  editable={isEditing}
                  onChange={setDiet}
                />
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function Field({
  label,
  value,
  editable,
  onChange,
}: {
  label: string;
  value: string;
  editable: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="rounded-2xl bg-black/20 p-4 ring-1 ring-white/10">
      <p className="text-xs uppercase tracking-wide text-white/50">{label}</p>

      {editable ? (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="mt-3 w-full rounded-xl bg-white/10 px-3 py-3 text-sm text-white outline-none ring-1 ring-white/10 placeholder:text-white/40"
        />
      ) : (
        <p className="mt-3 text-base font-medium text-white">{value}</p>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl bg-black/20 p-4 ring-1 ring-white/10">
      <p className="text-xs uppercase tracking-wide text-white/50">{label}</p>
      <p className="mt-2 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}
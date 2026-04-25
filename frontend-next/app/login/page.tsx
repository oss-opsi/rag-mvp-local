"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api-client";
import { BrandMark } from "@/components/brand-logo";

export const dynamic = "force-dynamic";

/**
 * Hero illustration : trois documents convergeant vers une sphère vectorielle
 * (métaphore de l'indexation). 100 % SVG inline, pas d'asset externe.
 */
function HeroIllustration() {
  return (
    <svg
      viewBox="0 0 480 360"
      role="img"
      aria-label="Documents convergeant vers une sphère de connaissance"
      className="w-full max-w-md"
    >
      <defs>
        <linearGradient id="tm-grad-accent" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2E6BE6" />
          <stop offset="100%" stopColor="#14B8A6" />
        </linearGradient>
        <radialGradient id="tm-grad-sphere" cx="0.4" cy="0.4" r="0.7">
          <stop offset="0%" stopColor="#5B8DEF" stopOpacity="0.95" />
          <stop offset="60%" stopColor="#2E6BE6" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#0B1B2B" stopOpacity="0.3" />
        </radialGradient>
        <linearGradient id="tm-grad-doc" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#E4E9F2" stopOpacity="0.85" />
        </linearGradient>
      </defs>

      {/* Halo arrière */}
      <circle cx="340" cy="180" r="130" fill="url(#tm-grad-accent)" opacity="0.12" />
      <circle cx="340" cy="180" r="90" fill="url(#tm-grad-accent)" opacity="0.18" />

      {/* Sphère vectorielle */}
      <circle cx="340" cy="180" r="70" fill="url(#tm-grad-sphere)" />
      {/* Lignes vectorielles sur la sphère */}
      <ellipse cx="340" cy="180" rx="70" ry="22" fill="none" stroke="#FFFFFF" strokeOpacity="0.35" strokeWidth="1" />
      <ellipse cx="340" cy="180" rx="70" ry="44" fill="none" stroke="#FFFFFF" strokeOpacity="0.25" strokeWidth="1" />
      <line x1="270" y1="180" x2="410" y2="180" stroke="#FFFFFF" strokeOpacity="0.35" strokeWidth="1" />
      <line x1="340" y1="110" x2="340" y2="250" stroke="#FFFFFF" strokeOpacity="0.25" strokeWidth="1" />

      {/* Points / nœuds */}
      <circle cx="305" cy="155" r="3" fill="#14B8A6" />
      <circle cx="370" cy="200" r="3" fill="#FFFFFF" />
      <circle cx="345" cy="140" r="2.5" fill="#FFFFFF" opacity="0.8" />
      <circle cx="320" cy="215" r="2.5" fill="#14B8A6" opacity="0.9" />

      {/* Documents source (trois cartes empilées) */}
      <g transform="translate(60 90)">
        <rect width="120" height="150" rx="10" fill="url(#tm-grad-doc)" stroke="#E4E9F2" />
        <rect x="14" y="18" width="60" height="6" rx="3" fill="#0B1B2B" opacity="0.8" />
        <rect x="14" y="32" width="92" height="4" rx="2" fill="#6B7A90" opacity="0.6" />
        <rect x="14" y="42" width="78" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="56" width="92" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="66" width="64" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="86" width="92" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="96" width="50" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="116" width="36" height="14" rx="3" fill="#2E6BE6" opacity="0.8" />
      </g>

      <g transform="translate(110 60)" opacity="0.7">
        <rect width="120" height="150" rx="10" fill="url(#tm-grad-doc)" stroke="#E4E9F2" />
        <rect x="14" y="18" width="50" height="6" rx="3" fill="#0B1B2B" opacity="0.7" />
        <rect x="14" y="32" width="84" height="4" rx="2" fill="#6B7A90" opacity="0.5" />
        <rect x="14" y="42" width="70" height="4" rx="2" fill="#6B7A90" opacity="0.4" />
      </g>

      {/* Lignes de flux documents → sphère */}
      <g stroke="#14B8A6" strokeWidth="1.5" fill="none" strokeDasharray="4 4" opacity="0.7">
        <path d="M 180 165 Q 240 130 270 175" />
        <path d="M 180 200 Q 240 200 275 195" />
        <path d="M 180 235 Q 240 235 275 215" />
      </g>

      {/* Petit indicateur "indexé" */}
      <g transform="translate(395 110)">
        <circle r="14" fill="#14B8A6" />
        <path d="M -5 0 L -1 4 L 5 -4" stroke="#FFFFFF" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/documents";

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(username, password);
      router.push(nextPath);
      router.refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Identifiants invalides";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-2">
      {/* Hero (gauche) — visible à partir de lg */}
      <aside
        className="relative hidden flex-col justify-between overflow-hidden bg-ink p-10 text-ink-foreground lg:flex"
        style={{
          background:
            "radial-gradient(ellipse at top right, hsl(var(--accent) / 0.25) 0%, hsl(var(--ink)) 60%)",
        }}
      >
        <div className="flex items-center gap-3">
          <BrandMark size={44} />
          <span className="text-lg font-semibold tracking-tight">Tell me</span>
        </div>

        <div className="flex flex-col items-center gap-6">
          <HeroIllustration />
          <div className="max-w-md text-center">
            <h2 className="text-2xl font-semibold tracking-tight">
              Vos documents, prêts à répondre.
            </h2>
            <p className="mt-3 text-sm text-white/70">
              Indexez vos cahiers des charges, interrogez votre base et mesurez
              la qualité des réponses — en un seul espace.
            </p>
          </div>
        </div>

        <p className="text-xs text-white/50">
          Pipeline RAG · bge-m3 · BM25 · Reranker
        </p>
      </aside>

      {/* Formulaire (droite) */}
      <main className="flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex flex-col items-center text-center lg:hidden">
            <BrandMark size={44} />
            <h1 className="mt-4 text-xl font-semibold tracking-tight">Tell me</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Plateforme RAG
            </p>
          </div>

          <div className="hidden lg:mb-8 lg:block">
            <h1 className="text-2xl font-semibold tracking-tight">
              Connexion
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Accédez à votre espace Tell me.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="username">Nom d&apos;utilisateur</Label>
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Mot de passe</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
              />
            </div>

            {error ? (
              <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </div>
            ) : null}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Connexion..." : "Se connecter"}
            </Button>
          </form>

          <p className="mt-8 text-center text-xs text-muted-foreground lg:hidden">
            Pipeline RAG · bge-m3 · BM25 · Reranker
          </p>
        </div>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={<div className="min-h-dvh" />}>
      <LoginForm />
    </React.Suspense>
  );
}

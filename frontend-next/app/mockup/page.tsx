"use client";

import { useState } from "react";
import {
  Sparkles,
  MessageCircle,
  FileSearch,
  ArrowRight,
  Send,
  ThumbsUp,
  ThumbsDown,
  FileText,
  ExternalLink,
  ChevronDown,
  CheckCircle2,
  AlertCircle,
  Clock,
  TrendingUp,
  Search,
  Filter,
  Plus,
  Calculator,
  Calendar,
  BookOpen,
  Users,
  Wand2,
  Activity,
  Database,
  Layers,
} from "lucide-react";

type View = "overview" | "chat" | "analyse" | "scheduler";

const VIEWS: { id: View; label: string; icon: typeof Sparkles }[] = [
  { id: "overview", label: "Tokens & composants", icon: Sparkles },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "analyse", label: "Analyse d'écarts", icon: FileSearch },
  { id: "scheduler", label: "Planificateur", icon: Activity },
];

export default function MockupPage() {
  const [view, setView] = useState<View>("overview");

  return (
    <div className="m-root min-h-screen">
      <MockupStyles />

      <header className="sticky top-0 z-20 border-b border-[hsl(var(--m-border-soft))] bg-white/70 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[hsl(var(--m-accent))] to-[hsl(var(--m-success))] text-base font-bold text-white shadow-[0_4px_12px_rgba(46,107,230,0.25)]">
              Ω
            </div>
            <div>
              <div className="text-sm font-semibold tracking-tight">Tell me — Maquette UI v4</div>
              <div className="text-[11px] text-[hsl(var(--m-muted))]">
                Proposition de modernisation · branche <code className="font-mono">feat/ui-modern-v4</code>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 rounded-full bg-[hsl(var(--m-accent-soft))] px-2.5 py-1 text-xs font-medium text-[hsl(var(--m-accent))]">
            <Sparkles className="h-3 w-3" />
            Maquette interactive
          </div>
        </div>
      </header>

      <nav className="border-b border-[hsl(var(--m-border-soft))] bg-white/40">
        <div className="mx-auto flex max-w-[1400px] gap-1 overflow-x-auto px-6">
          {VIEWS.map(({ id, label, icon: Icon }) => {
            const isActive = view === id;
            return (
              <button
                key={id}
                onClick={() => setView(id)}
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-[hsl(var(--m-accent))] text-[hsl(var(--m-ink))]"
                    : "border-transparent text-[hsl(var(--m-muted))] hover:text-[hsl(var(--m-ink))]"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            );
          })}
        </div>
      </nav>

      <main key={view} className="m-fade-in mx-auto max-w-[1400px] px-6 py-10">
        {view === "overview" && <Overview />}
        {view === "chat" && <ChatMockup />}
        {view === "analyse" && <AnalyseMockup />}
        {view === "scheduler" && <SchedulerMockup />}
      </main>

      <footer className="mx-auto max-w-[1400px] px-6 pb-16 pt-4 text-xs text-[hsl(var(--m-muted))]">
        Maquette statique — aucune donnée réelle. Les pages de production restent inchangées.
      </footer>
    </div>
  );
}

/* ============================================================
   OVERVIEW : tokens, profondeur, comparaisons avant / après
   ============================================================ */

function Overview() {
  return (
    <div className="space-y-12">
      <section className="grid gap-6 md:grid-cols-[1.4fr_1fr]">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Une refonte qui modernise{" "}
            <span className="bg-gradient-to-r from-[hsl(var(--m-accent))] to-[hsl(var(--m-violet))] bg-clip-text text-transparent">
              sans réinventer
            </span>
          </h1>
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-[hsl(var(--m-muted))]">
            Étape 1 — affiner les tokens (rayons, ombres tintées, dégradés très subtils, dark
            mode complet). Étape 2 — refondre le chat (la page la plus utilisée). Le reste suit
            par incréments sans risque, branche par branche, taggable.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Pill tone="accent" icon={Layers}>Étape 1 · Tokens</Pill>
            <Pill tone="success" icon={MessageCircle}>Étape 2 · Chat</Pill>
            <Pill tone="muted" icon={FileSearch}>Étape 3 · Analyse</Pill>
            <Pill tone="muted" icon={Activity}>Étape 4 · Data viz</Pill>
            <Pill tone="muted" icon={Wand2}>Étape 5 · Animations</Pill>
          </div>
        </div>
        <div className="m-card-elevated p-5">
          <div className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--m-muted))]">
            Inspirations
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[13px]">
            <div className="rounded-lg border border-[hsl(var(--m-border-soft))] bg-white p-3">
              <div className="font-medium">Linear</div>
              <div className="text-xs text-[hsl(var(--m-muted))]">Densité aérée</div>
            </div>
            <div className="rounded-lg border border-[hsl(var(--m-border-soft))] bg-white p-3">
              <div className="font-medium">Vercel</div>
              <div className="text-xs text-[hsl(var(--m-muted))]">Profondeur subtile</div>
            </div>
            <div className="rounded-lg border border-[hsl(var(--m-border-soft))] bg-white p-3">
              <div className="font-medium">Notion AI</div>
              <div className="text-xs text-[hsl(var(--m-muted))]">Streaming fluide</div>
            </div>
            <div className="rounded-lg border border-[hsl(var(--m-border-soft))] bg-white p-3">
              <div className="font-medium">Cursor</div>
              <div className="text-xs text-[hsl(var(--m-muted))]">Prompts visibles</div>
            </div>
          </div>
        </div>
      </section>

      {/* Tokens */}
      <section>
        <SectionHeader
          eyebrow="Étape 1"
          title="Tokens — palette, rayons, ombres"
          subtitle="Mêmes couleurs sémantiques, mais déclinées avec des variantes ‘soft’ et des ombres tintées qui apportent de la profondeur."
        />

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="m-card p-5">
            <div className="text-sm font-medium">Couleurs sémantiques</div>
            <div className="mt-4 space-y-3">
              {[
                { name: "Accent", v: "var(--m-accent)", soft: "var(--m-accent-soft)", hex: "#2E6BE6" },
                { name: "Success", v: "var(--m-success)", soft: "var(--m-success-soft)", hex: "#14B8A6" },
                { name: "Warning", v: "var(--m-warning)", soft: "var(--m-warning-soft)", hex: "#F59E0B" },
                { name: "Danger", v: "var(--m-danger)", soft: "var(--m-danger-soft)", hex: "#E11D48" },
                { name: "Violet", v: "var(--m-violet)", soft: "var(--m-violet-soft)", hex: "#7C3AED" },
              ].map((c) => (
                <div key={c.name} className="flex items-center gap-3">
                  <div
                    className="h-8 w-8 rounded-lg shadow-sm"
                    style={{ background: `hsl(${c.v})` }}
                  />
                  <div
                    className="h-8 w-8 rounded-lg"
                    style={{ background: `hsl(${c.soft})` }}
                  />
                  <div className="flex-1">
                    <div className="text-[13px] font-medium">{c.name}</div>
                    <div className="font-mono text-[11px] text-[hsl(var(--m-muted))]">
                      {c.hex} · soft pour bg subtle
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="m-card p-5">
            <div className="text-sm font-medium">Rayons & espacement</div>
            <div className="mt-4 space-y-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 rounded-md border-2 border-dashed border-[hsl(var(--m-border))]" />
                <div className="flex-1 text-[13px]">
                  <div className="font-medium">10 px</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">Boutons, inputs, badges</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 rounded-[14px] border-2 border-dashed border-[hsl(var(--m-border))]" />
                <div className="flex-1 text-[13px]">
                  <div className="font-medium">14 px</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">
                    Cartes standard <span className="text-[hsl(var(--m-accent))]">(+2px)</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 rounded-[20px] border-2 border-dashed border-[hsl(var(--m-border))]" />
                <div className="flex-1 text-[13px]">
                  <div className="font-medium">20 px</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">Cartes hero / dialogs</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 rounded-full border-2 border-dashed border-[hsl(var(--m-border))]" />
                <div className="flex-1 text-[13px]">
                  <div className="font-medium">Pill</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">Badges, statuts, chips</div>
                </div>
              </div>
            </div>
          </div>

          <div className="m-card p-5">
            <div className="text-sm font-medium">Ombres tintées (multi-layer)</div>
            <div className="mt-4 space-y-3">
              {[
                { name: "xs", className: "shadow-[0_1px_2px_rgba(11,27,43,0.04)]" },
                {
                  name: "sm",
                  className:
                    "shadow-[0_1px_2px_rgba(11,27,43,0.04),0_4px_12px_rgba(11,27,43,0.04)]",
                },
                {
                  name: "md",
                  className:
                    "shadow-[0_2px_4px_rgba(11,27,43,0.04),0_8px_24px_rgba(11,27,43,0.06),0_16px_40px_rgba(46,107,230,0.04)]",
                },
                {
                  name: "lg",
                  className:
                    "shadow-[0_4px_8px_rgba(11,27,43,0.06),0_16px_40px_rgba(11,27,43,0.08),0_32px_64px_rgba(46,107,230,0.08)]",
                },
              ].map((s) => (
                <div key={s.name} className="flex items-center gap-3">
                  <div className={`h-12 w-12 rounded-xl bg-white ${s.className}`} />
                  <div className="flex-1 text-[13px]">
                    <div className="font-medium">shadow-{s.name}</div>
                    <div className="text-xs text-[hsl(var(--m-muted))]">
                      Teinte légère vers l'accent
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Avant / après */}
      <section>
        <SectionHeader
          eyebrow="Comparaison"
          title="Avant / après — éléments clés"
          subtitle="Mêmes informations, plus de hiérarchie, plus de profondeur."
        />

        <div className="grid gap-6 lg:grid-cols-2">
          <ComparisonCard label="Avant">
            <div className="rounded-md border border-[hsl(var(--m-border))] bg-white p-3">
              <div className="flex items-start gap-3">
                <FileText className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--m-muted))]" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium">CCN_Syntec_2024.pdf</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">142 chunks · 3,2 Mo</div>
                </div>
                <button className="rounded-md border border-[hsl(var(--m-border))] px-2 py-1 text-xs text-[hsl(var(--m-muted))]">
                  Supprimer
                </button>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button className="rounded-md bg-[hsl(var(--m-accent))] px-3 py-1.5 text-xs font-medium text-white">
                Indexer
              </button>
              <button className="rounded-md border border-[hsl(var(--m-border))] bg-white px-3 py-1.5 text-xs">
                Annuler
              </button>
              <span className="rounded-md bg-[hsl(var(--m-success-soft))] px-2 py-1 text-xs font-medium text-[hsl(var(--m-success))]">
                Indexé
              </span>
            </div>
          </ComparisonCard>

          <ComparisonCard label="Après" highlight>
            <div className="group relative overflow-hidden rounded-[14px] border border-[hsl(var(--m-border-soft))] bg-gradient-to-br from-white to-[hsl(var(--m-surface-2))] p-3.5 transition-all hover:-translate-y-0.5 hover:border-[hsl(var(--m-accent)/0.3)] hover:shadow-[0_2px_4px_rgba(11,27,43,0.04),0_8px_24px_rgba(11,27,43,0.06),0_16px_40px_rgba(46,107,230,0.06)]">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[hsl(var(--m-danger-soft))] to-[hsl(var(--m-warning-soft))]">
                  <FileText className="h-5 w-5 text-[hsl(var(--m-danger))]" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-semibold tracking-tight">
                    CCN_Syntec_2024.pdf
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-[hsl(var(--m-muted))]">
                    <span>142 chunks</span>
                    <span className="h-1 w-1 rounded-full bg-[hsl(var(--m-border))]" />
                    <span>3,2 Mo</span>
                    <span className="h-1 w-1 rounded-full bg-[hsl(var(--m-border))]" />
                    <span>indexé il y a 2 j</span>
                  </div>
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button className="m-btn-primary">
                Indexer
                <ArrowRight className="ml-1 inline h-3.5 w-3.5" />
              </button>
              <button className="m-btn-ghost">Annuler</button>
              <span className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--m-success)/0.25)] bg-[hsl(var(--m-success-soft))] px-2.5 py-1 text-xs font-medium text-[hsl(var(--m-success))]">
                <CheckCircle2 className="h-3 w-3" /> Indexé
              </span>
            </div>
          </ComparisonCard>
        </div>
      </section>
    </div>
  );
}

/* ============================================================
   CHAT MOCKUP
   ============================================================ */

const SUGGESTIONS = [
  {
    icon: Calculator,
    title: "Calculer la prime d'ancienneté",
    sub: "CCN66 — barème par tranches",
  },
  {
    icon: Calendar,
    title: "Durée du congé maternité",
    sub: "Cas standard et prolongations",
  },
  {
    icon: BookOpen,
    title: "DSN événementielle vs mensuelle",
    sub: "Différences et délais légaux",
  },
  {
    icon: Users,
    title: "Bulletin pour cadre forfait jours",
    sub: "Mentions obligatoires et exceptions",
  },
];

function ChatMockup() {
  return (
    <div className="space-y-10">
      <SectionHeader
        eyebrow="Étape 2"
        title="Chat — empty state, streaming, sources"
        subtitle="La page la plus utilisée. Mêmes briques (bulles, sources, feedback) mais avec hiérarchie, animations et état vide explicite."
      />

      {/* Empty state */}
      <div className="m-card-elevated overflow-hidden">
        <div className="border-b border-[hsl(var(--m-border-soft))] bg-white/60 px-6 py-3 text-[13px] font-medium">
          Empty state — nouvel onglet
        </div>
        <div className="px-6 py-12 text-center">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-[hsl(var(--m-accent))] to-[hsl(var(--m-violet))] text-white shadow-[0_8px_24px_rgba(46,107,230,0.3)]">
            <MessageCircle className="h-8 w-8" />
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">
            Que voulez-vous savoir aujourd'hui&nbsp;?
          </h2>
          <p className="mt-2 text-sm text-[hsl(var(--m-muted))]">
            Posez votre question en langage naturel — Tell me cherche dans vos documents et les
            sources publiques activées.
          </p>

          <div className="mx-auto mt-8 grid max-w-3xl gap-3 text-left sm:grid-cols-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.title}
                className="group flex items-start gap-3 rounded-2xl border border-[hsl(var(--m-border-soft))] bg-white p-4 text-left transition-all hover:-translate-y-0.5 hover:border-[hsl(var(--m-accent)/0.3)] hover:shadow-[0_2px_4px_rgba(11,27,43,0.04),0_8px_24px_rgba(11,27,43,0.06),0_16px_40px_rgba(46,107,230,0.06)]"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--m-accent-soft))] text-[hsl(var(--m-accent))]">
                  <s.icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium">{s.title}</div>
                  <div className="text-xs text-[hsl(var(--m-muted))]">{s.sub}</div>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-[hsl(var(--m-muted))] transition-all group-hover:translate-x-0.5 group-hover:text-[hsl(var(--m-accent))]" />
              </button>
            ))}
          </div>

          <div className="mx-auto mt-8 max-w-3xl">
            <ChatComposer placeholder="Posez votre question…" />
            <div className="mt-3 flex items-center justify-center gap-2 text-xs text-[hsl(var(--m-muted))]">
              <Toggle label="Recherche approfondie" on />
              <span className="h-1 w-1 rounded-full bg-[hsl(var(--m-border))]" />
              <Toggle label="Sources publiques" on />
              <span className="h-1 w-1 rounded-full bg-[hsl(var(--m-border))]" />
              <Toggle label="Reranker" />
            </div>
          </div>
        </div>
      </div>

      {/* Active conversation */}
      <div className="m-card-elevated overflow-hidden">
        <div className="border-b border-[hsl(var(--m-border-soft))] bg-white/60 px-6 py-3 text-[13px] font-medium">
          Conversation active — bulles, sources et streaming
        </div>
        <div className="space-y-6 px-6 py-8">
          {/* User bubble */}
          <div className="flex justify-end">
            <div className="max-w-[75%] rounded-2xl rounded-br-md bg-gradient-to-br from-[hsl(var(--m-accent))] to-[hsl(220_73%_48%)] px-4 py-2.5 text-[14px] text-white shadow-[0_4px_12px_rgba(46,107,230,0.2)]">
              Comment calculer la prime d'ancienneté pour un salarié de 8 ans en CCN66 ?
            </div>
          </div>

          {/* Assistant bubble — completed */}
          <div className="flex">
            <div className="max-w-[80%] space-y-3">
              <div className="rounded-2xl rounded-bl-md border border-[hsl(var(--m-border-soft))] bg-gradient-to-br from-white to-[hsl(var(--m-accent-soft)/0.4)] px-4 py-3 text-[14px] leading-relaxed shadow-[0_2px_8px_rgba(11,27,43,0.04)]">
                <p>
                  Selon la <strong>CCN66 (article 38)</strong>, la prime d'ancienneté pour un salarié
                  de 8 ans s'élève à{" "}
                  <strong className="text-[hsl(var(--m-accent))]">11 % du salaire de base</strong>{" "}
                  conventionnel.
                </p>
                <p className="mt-2">
                  Le barème progresse par tranches&nbsp;: 5 % à 5 ans, 8 % à 6 ans, 11 % à 8 ans,
                  17 % à 12 ans, et plafonne à 26 % à 25 ans.
                </p>

                {/* Sources */}
                <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[hsl(var(--m-border-soft))] pt-3">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-[hsl(var(--m-muted))]">
                    Sources
                  </span>
                  <SourceChip n={1} title="CCN66 — Art. 38" />
                  <SourceChip n={2} title="Avenant 322 (2023)" />
                  <SourceChip n={3} title="Légifrance · IDCC 0413" external />
                </div>
              </div>

              {/* Feedback row */}
              <div className="flex items-center gap-1 px-1">
                <button className="m-icon-btn"><ThumbsUp className="h-3.5 w-3.5" /></button>
                <button className="m-icon-btn"><ThumbsDown className="h-3.5 w-3.5" /></button>
                <span className="text-[11px] text-[hsl(var(--m-muted))]">·</span>
                <span className="text-[11px] text-[hsl(var(--m-muted))]">12 chunks · 1,8 s · gpt-4o-mini</span>
              </div>
            </div>
          </div>

          {/* Assistant bubble — streaming skeleton */}
          <div className="flex">
            <div className="max-w-[80%]">
              <div className="rounded-2xl rounded-bl-md border border-[hsl(var(--m-border-soft))] bg-white px-4 py-3 shadow-[0_2px_8px_rgba(11,27,43,0.04)]">
                <div className="flex items-center gap-1.5 text-[12px] text-[hsl(var(--m-muted))]">
                  <span className="m-typing-dot" />
                  <span className="m-typing-dot" style={{ animationDelay: "0.15s" }} />
                  <span className="m-typing-dot" style={{ animationDelay: "0.3s" }} />
                  <span className="ml-2">Tell me rédige sa réponse…</span>
                </div>
                <div className="mt-3 space-y-2">
                  <div className="m-skeleton h-3 w-[92%]" />
                  <div className="m-skeleton h-3 w-[78%]" />
                  <div className="m-skeleton h-3 w-[60%]" />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-[hsl(var(--m-border-soft))] bg-white/60 px-6 py-4">
          <ChatComposer placeholder="Suite à votre question…" />
        </div>
      </div>
    </div>
  );
}

function ChatComposer({ placeholder }: { placeholder: string }) {
  return (
    <div className="group relative">
      <div className="flex items-end gap-2 rounded-2xl border border-[hsl(var(--m-border))] bg-white p-2 shadow-[0_2px_8px_rgba(11,27,43,0.04)] transition-all focus-within:border-[hsl(var(--m-accent)/0.5)] focus-within:shadow-[0_4px_16px_rgba(46,107,230,0.12)]">
        <textarea
          rows={1}
          placeholder={placeholder}
          className="min-h-[28px] flex-1 resize-none bg-transparent px-3 py-2 text-[14px] outline-none placeholder:text-[hsl(var(--m-muted))]"
        />
        <button className="m-btn-primary !px-3 !py-2">
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function Toggle({ label, on }: { label: string; on?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`relative inline-block h-3.5 w-6 rounded-full transition-colors ${
          on ? "bg-[hsl(var(--m-accent))]" : "bg-[hsl(var(--m-border))]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition-all ${
            on ? "left-3" : "left-0.5"
          }`}
        />
      </span>
      <span className="text-xs">{label}</span>
    </span>
  );
}

function SourceChip({ n, title, external }: { n: number; title: string; external?: boolean }) {
  return (
    <button className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--m-border))] bg-white px-2.5 py-1 text-[11px] font-medium text-[hsl(var(--m-ink))] transition-all hover:-translate-y-0.5 hover:border-[hsl(var(--m-accent)/0.4)] hover:bg-[hsl(var(--m-accent-soft))] hover:text-[hsl(var(--m-accent))]">
      <span className="font-mono text-[10px] text-[hsl(var(--m-muted))]">[{n}]</span>
      <span className="max-w-[180px] truncate">{title}</span>
      {external && <ExternalLink className="h-3 w-3 opacity-60" />}
    </button>
  );
}

/* ============================================================
   ANALYSE D'ÉCARTS
   ============================================================ */

type ReqStatus = "success" | "warning" | "danger";
type ReqItem = { title: string; status: ReqStatus; confidence: number };

const REQUIREMENT_GROUPS: { name: string; icon: typeof Calculator; items: ReqItem[] }[] = [
  {
    name: "Paie",
    icon: Calculator,
    items: [
      { title: "Bulletin conforme syntec — toutes mentions obligatoires", status: "success", confidence: 92 },
      { title: "Indemnité kilométrique selon barème URSSAF", status: "warning", confidence: 67 },
      { title: "Saisie sur salaire — quotité disponible mensuelle", status: "danger", confidence: 41 },
      { title: "Net imposable / net social (réforme 2024)", status: "success", confidence: 88 },
    ],
  },
  {
    name: "Gestion des temps",
    icon: Calendar,
    items: [
      { title: "Pointage badgeuse multi-sites (entrée/sortie/pause)", status: "success", confidence: 88 },
      { title: "Modulation horaire annuelle — limite 1 607 h", status: "warning", confidence: 58 },
    ],
  },
  {
    name: "DSN",
    icon: Database,
    items: [
      { title: "DSN mensuelle — envoi automatique avant le 5/15", status: "success", confidence: 95 },
      { title: "DSN événementielle — arrêt maladie sous 5 j", status: "success", confidence: 91 },
    ],
  },
];

function AnalyseMockup() {
  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Étape 3"
        title="Analyse d'écarts — densité maîtrisée"
        subtitle="Exigences groupées par section, header sticky, indicateur de confiance visuel, slide-over plus aéré."
      />

      {/* Header CDC + métriques */}
      <div className="m-card-elevated overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[hsl(var(--m-border-soft))] bg-white/60 px-6 py-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-[hsl(var(--m-muted))]">
              <span>Coopérative Lambda</span>
              <span>·</span>
              <span>CDC v2.4</span>
            </div>
            <h2 className="mt-0.5 text-xl font-semibold tracking-tight">
              Analyse de couverture — Coopérative Lambda
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button className="m-btn-ghost">
              <Filter className="mr-1.5 inline h-4 w-4" /> Filtres
            </button>
            <button className="m-btn-primary">Exporter</button>
          </div>
        </div>

        <div className="grid gap-px bg-[hsl(var(--m-border-soft))] sm:grid-cols-4">
          <Metric label="Exigences" value="18" sub="identifiées" trend="+2 vs v2.3" />
          <Metric label="Couvertes" value="12" sub="67 %" tone="success" trend="+1 vs v2.3" />
          <Metric label="Partielles" value="4" sub="22 %" tone="warning" />
          <Metric label="Confiance moyenne" value="76 %" sub="qualification IA" tone="accent" />
        </div>
      </div>

      {/* Donut + groupes */}
      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <div className="m-card-elevated p-6">
          <div className="text-[13px] font-medium">Couverture</div>
          <div className="mx-auto mt-4 flex h-44 w-44 items-center justify-center">
            <ModernDonut covered={67} partial={22} missing={11} />
          </div>
          <div className="mt-4 space-y-2 text-xs">
            <LegendDot color="hsl(var(--m-success))" label="Couvertes" value="12" />
            <LegendDot color="hsl(var(--m-warning))" label="Partielles" value="4" />
            <LegendDot color="hsl(var(--m-danger))" label="Non couvertes" value="2" />
          </div>
        </div>

        <div className="space-y-4">
          {REQUIREMENT_GROUPS.map((group) => (
            <div key={group.name} className="m-card-elevated overflow-hidden">
              <div className="flex items-center justify-between border-b border-[hsl(var(--m-border-soft))] bg-white/60 px-5 py-3">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--m-accent-soft))] text-[hsl(var(--m-accent))]">
                    <group.icon className="h-3.5 w-3.5" />
                  </div>
                  <div className="font-medium">{group.name}</div>
                  <span className="rounded-full bg-[hsl(var(--m-muted)/0.15)] px-2 py-0.5 text-[11px] text-[hsl(var(--m-muted))]">
                    {group.items.length} exigences
                  </span>
                </div>
                <ChevronDown className="h-4 w-4 text-[hsl(var(--m-muted))]" />
              </div>
              <div className="divide-y divide-[hsl(var(--m-border-soft))]">
                {group.items.map((item, i) => (
                  <RequirementRow key={i} {...item} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RequirementRow({
  title,
  status,
  confidence,
}: {
  title: string;
  status: "success" | "warning" | "danger";
  confidence: number;
}) {
  const tone = {
    success: { bar: "hsl(var(--m-success))", soft: "hsl(var(--m-success-soft))", label: "Couverte", icon: CheckCircle2 },
    warning: { bar: "hsl(var(--m-warning))", soft: "hsl(var(--m-warning-soft))", label: "Partielle", icon: AlertCircle },
    danger: { bar: "hsl(var(--m-danger))", soft: "hsl(var(--m-danger-soft))", label: "Non couverte", icon: AlertCircle },
  }[status];

  return (
    <button className="group relative flex w-full items-start gap-4 px-5 py-4 text-left transition-colors hover:bg-[hsl(var(--m-accent-soft)/0.4)]">
      <span
        className="absolute left-0 top-3 h-[calc(100%-1.5rem)] w-[3px] rounded-r-full"
        style={{ background: tone.bar }}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <div className="text-[13.5px] font-medium leading-tight">{title}</div>
        </div>
        <div className="mt-2 flex items-center gap-3">
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
            style={{ background: tone.soft, color: tone.bar }}
          >
            <tone.icon className="h-3 w-3" />
            {tone.label}
          </span>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-[hsl(var(--m-muted))]">Confiance</span>
            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-[hsl(var(--m-border-soft))]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${confidence}%`,
                  background:
                    confidence > 75
                      ? "hsl(var(--m-success))"
                      : confidence > 50
                      ? "hsl(var(--m-warning))"
                      : "hsl(var(--m-danger))",
                }}
              />
            </div>
            <span className="font-mono text-[11px] tabular-nums">{confidence}%</span>
          </div>
        </div>
      </div>
      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[hsl(var(--m-muted))] transition-all group-hover:translate-x-0.5 group-hover:text-[hsl(var(--m-accent))]" />
    </button>
  );
}

function ModernDonut({ covered, partial, missing }: { covered: number; partial: number; missing: number }) {
  const total = covered + partial + missing;
  const r = 70;
  const c = 2 * Math.PI * r;
  let offset = 0;
  const segments = [
    { value: covered, color: "hsl(var(--m-success))" },
    { value: partial, color: "hsl(var(--m-warning))" },
    { value: missing, color: "hsl(var(--m-danger))" },
  ];
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full -rotate-90">
      <circle cx="100" cy="100" r={r} fill="none" stroke="hsl(var(--m-border-soft))" strokeWidth="14" />
      {segments.map((seg, i) => {
        const length = (seg.value / total) * c;
        const dasharray = `${length} ${c - length}`;
        const dashoffset = -offset;
        offset += length;
        return (
          <circle
            key={i}
            cx="100"
            cy="100"
            r={r}
            fill="none"
            stroke={seg.color}
            strokeWidth="14"
            strokeDasharray={dasharray}
            strokeDashoffset={dashoffset}
            strokeLinecap="round"
            className="transition-all"
          />
        );
      })}
      <text
        x="100"
        y="95"
        textAnchor="middle"
        className="rotate-90 origin-center fill-[hsl(var(--m-ink))] text-[28px] font-bold"
        style={{ transform: "rotate(90deg)", transformOrigin: "100px 100px" }}
      >
        {covered}%
      </text>
      <text
        x="100"
        y="115"
        textAnchor="middle"
        className="fill-[hsl(var(--m-muted))] text-[11px]"
        style={{ transform: "rotate(90deg)", transformOrigin: "100px 100px" }}
      >
        couverture
      </text>
    </svg>
  );
}

function LegendDot({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />
        <span>{label}</span>
      </div>
      <span className="font-mono tabular-nums text-[hsl(var(--m-muted))]">{value}</span>
    </div>
  );
}

/* ============================================================
   SCHEDULER
   ============================================================ */

function SchedulerMockup() {
  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Étape 4"
        title="Planificateur — métriques et timeline"
        subtitle="Cartes ‘metric’ avec sparkline plutôt que tableaux denses, status badges animés, timeline jobs."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          icon={Activity}
          label="Jobs en cours"
          value="3"
          sub="2 ingest · 1 refresh"
          tone="accent"
          spark={[2, 4, 3, 5, 4, 6, 3]}
        />
        <MetricCard
          icon={CheckCircle2}
          label="Taux succès 7 j"
          value="98,2 %"
          sub="138 / 141 jobs"
          tone="success"
          spark={[97, 98, 99, 97, 98, 99, 98]}
        />
        <MetricCard
          icon={Database}
          label="Sources actives"
          value="6"
          sub="BOSS · URSSAF · DILA · Légifrance · …"
          tone="violet"
          spark={[4, 5, 5, 5, 6, 6, 6]}
        />
        <MetricCard
          icon={Clock}
          label="Prochain run"
          value="14 min"
          sub="Refresh BOSS · 14:30"
          tone="warning"
          spark={[5, 4, 3, 5, 4, 3, 2]}
        />
      </div>

      <div className="m-card-elevated overflow-hidden">
        <div className="flex items-center justify-between border-b border-[hsl(var(--m-border-soft))] bg-white/60 px-6 py-3">
          <div className="text-[13px] font-medium">Timeline — dernières heures</div>
          <button className="m-btn-ghost">
            <Plus className="mr-1.5 inline h-3.5 w-3.5" /> Nouveau job
          </button>
        </div>
        <div className="px-6 py-5">
          <div className="relative">
            <div className="absolute left-[15px] top-2 h-[calc(100%-1rem)] w-px bg-[hsl(var(--m-border-soft))]" />
            <div className="space-y-4">
              <TimelineItem time="14:16" title="Refresh URSSAF" status="running" detail="42 documents · embedding en cours" />
              <TimelineItem time="14:02" title="Refresh BOSS" status="success" detail="38 documents · 2,3 s" />
              <TimelineItem time="13:45" title="Ingestion CDC Coopérative Lambda" status="success" detail="142 chunks · v2.4" />
              <TimelineItem time="13:12" title="Snapshot Qdrant rag_user_3" status="warning" detail="snapshot pris, mais 2 collections orphelines détectées" />
              <TimelineItem time="12:55" title="Refresh service-public.fr" status="success" detail="ZIP DILA · 1 247 documents" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = "accent",
  spark,
}: {
  icon: typeof Sparkles;
  label: string;
  value: string;
  sub: string;
  tone?: "accent" | "success" | "warning" | "danger" | "violet";
  spark: number[];
}) {
  const color = `hsl(var(--m-${tone}))`;
  const soft = `hsl(var(--m-${tone}-soft))`;
  return (
    <div className="m-card-elevated p-5">
      <div className="flex items-center justify-between">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: soft }}>
          <Icon className="h-4 w-4" style={{ color }} />
        </div>
        <Sparkline data={spark} color={color} />
      </div>
      <div className="mt-4">
        <div className="text-xs font-medium text-[hsl(var(--m-muted))]">{label}</div>
        <div className="mt-1 text-2xl font-semibold tracking-tight">{value}</div>
        <div className="mt-1 text-[11px] text-[hsl(var(--m-muted))]">{sub}</div>
      </div>
    </div>
  );
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const w = 60;
  const h = 24;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="opacity-80">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TimelineItem({
  time,
  title,
  status,
  detail,
}: {
  time: string;
  title: string;
  status: "running" | "success" | "warning" | "danger";
  detail: string;
}) {
  const tone = {
    running: { bg: "hsl(var(--m-accent))", soft: "hsl(var(--m-accent-soft))", pulse: true, label: "En cours" },
    success: { bg: "hsl(var(--m-success))", soft: "hsl(var(--m-success-soft))", pulse: false, label: "Succès" },
    warning: { bg: "hsl(var(--m-warning))", soft: "hsl(var(--m-warning-soft))", pulse: false, label: "Avertissement" },
    danger: { bg: "hsl(var(--m-danger))", soft: "hsl(var(--m-danger-soft))", pulse: false, label: "Échec" },
  }[status];

  return (
    <div className="relative flex items-start gap-4 pl-1">
      <div className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white" style={{ boxShadow: `0 0 0 2px ${tone.bg}` }}>
        <span
          className={`h-2 w-2 rounded-full ${tone.pulse ? "m-pulse" : ""}`}
          style={{ background: tone.bg }}
        />
      </div>
      <div className="min-w-0 flex-1 pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-[hsl(var(--m-muted))]">{time}</span>
          <span className="text-[13.5px] font-medium">{title}</span>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{ background: tone.soft, color: tone.bg }}
          >
            {tone.label}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-[hsl(var(--m-muted))]">{detail}</div>
      </div>
    </div>
  );
}

/* ============================================================
   Helpers visuels
   ============================================================ */

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="mb-6">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--m-accent))]">
        {eyebrow}
      </div>
      <h2 className="mt-1 text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm text-[hsl(var(--m-muted))]">{subtitle}</p>
    </div>
  );
}

function ComparisonCard({
  label,
  highlight,
  children,
}: {
  label: string;
  highlight?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`overflow-hidden rounded-[20px] border ${
        highlight
          ? "border-[hsl(var(--m-accent)/0.3)] shadow-[0_4px_8px_rgba(11,27,43,0.06),0_16px_40px_rgba(11,27,43,0.08),0_32px_64px_rgba(46,107,230,0.08)]"
          : "border-[hsl(var(--m-border-soft))]"
      } bg-white`}
    >
      <div
        className={`flex items-center justify-between border-b px-5 py-2.5 text-xs font-medium ${
          highlight
            ? "border-[hsl(var(--m-accent)/0.2)] bg-[hsl(var(--m-accent-soft))] text-[hsl(var(--m-accent))]"
            : "border-[hsl(var(--m-border-soft))] bg-[hsl(var(--m-surface-2))] text-[hsl(var(--m-muted))]"
        }`}
      >
        <span className="uppercase tracking-wider">{label}</span>
        {highlight && (
          <span className="inline-flex items-center gap-1 text-[11px]">
            <Sparkles className="h-3 w-3" /> v4
          </span>
        )}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  tone = "muted",
  trend,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "accent" | "success" | "warning" | "muted";
  trend?: string;
}) {
  const color =
    tone === "accent"
      ? "hsl(var(--m-accent))"
      : tone === "success"
      ? "hsl(var(--m-success))"
      : tone === "warning"
      ? "hsl(var(--m-warning))"
      : "hsl(var(--m-muted))";
  return (
    <div className="bg-white p-5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-[hsl(var(--m-muted))]">
        {label}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <div className="text-2xl font-semibold tracking-tight" style={{ color }}>
          {value}
        </div>
        <div className="text-xs text-[hsl(var(--m-muted))]">{sub}</div>
      </div>
      {trend && (
        <div className="mt-1 inline-flex items-center gap-1 text-[11px] text-[hsl(var(--m-success))]">
          <TrendingUp className="h-3 w-3" /> {trend}
        </div>
      )}
    </div>
  );
}

function Pill({
  tone,
  icon: Icon,
  children,
}: {
  tone: "accent" | "success" | "muted";
  icon: typeof Sparkles;
  children: React.ReactNode;
}) {
  const cls =
    tone === "accent"
      ? "bg-[hsl(var(--m-accent-soft))] text-[hsl(var(--m-accent))] border-[hsl(var(--m-accent)/0.25)]"
      : tone === "success"
      ? "bg-[hsl(var(--m-success-soft))] text-[hsl(var(--m-success))] border-[hsl(var(--m-success)/0.25)]"
      : "bg-white text-[hsl(var(--m-muted))] border-[hsl(var(--m-border))]";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}>
      <Icon className="h-3 w-3" />
      {children}
    </span>
  );
}

/* ============================================================
   Tokens locaux + utilitaires CSS scopés .m-root
   ============================================================ */

function MockupStyles() {
  return (
    <style
      dangerouslySetInnerHTML={{
        __html: `
        .m-root {
          --m-bg: 218 33% 98%;
          --m-surface: 0 0% 100%;
          --m-surface-2: 218 33% 99%;
          --m-ink: 211 60% 11%;
          --m-muted: 215 16% 49%;
          --m-border: 218 35% 90%;
          --m-border-soft: 218 35% 94%;

          --m-accent: 219 78% 54%;
          --m-accent-soft: 219 78% 95%;
          --m-success: 173 75% 38%;
          --m-success-soft: 173 75% 94%;
          --m-warning: 38 92% 50%;
          --m-warning-soft: 38 92% 94%;
          --m-danger: 347 78% 50%;
          --m-danger-soft: 347 78% 96%;
          --m-violet: 263 83% 58%;
          --m-violet-soft: 263 83% 96%;

          background:
            radial-gradient(ellipse 90% 50% at 50% -10%, hsl(var(--m-accent) / 0.08), transparent 70%),
            radial-gradient(ellipse 60% 40% at 90% 30%, hsl(var(--m-violet) / 0.05), transparent 70%),
            hsl(var(--m-bg));
          color: hsl(var(--m-ink));
          font-family: var(--font-inter), system-ui, sans-serif;
          font-feature-settings: "cv02","cv03","cv04","cv11";
          -webkit-font-smoothing: antialiased;
        }

        .m-card {
          background: hsl(var(--m-surface));
          border: 1px solid hsl(var(--m-border-soft));
          border-radius: 14px;
          box-shadow:
            0 1px 2px rgba(11,27,43,0.03),
            0 4px 12px rgba(11,27,43,0.04);
        }

        .m-card-elevated {
          background:
            linear-gradient(180deg, hsl(var(--m-surface)) 0%, hsl(var(--m-surface-2)) 100%);
          border: 1px solid hsl(var(--m-border-soft));
          border-radius: 20px;
          box-shadow:
            0 1px 2px rgba(11,27,43,0.04),
            0 8px 24px rgba(11,27,43,0.06),
            0 16px 48px rgba(46,107,230,0.04);
        }

        .m-btn-primary {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: linear-gradient(180deg, hsl(220 91% 58%) 0%, hsl(var(--m-accent)) 100%);
          color: white;
          border: 1px solid hsl(220 73% 45%);
          border-radius: 10px;
          padding: 7px 13px;
          font-weight: 500;
          font-size: 13px;
          line-height: 1;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.18),
            0 1px 2px rgba(46,107,230,0.3),
            0 4px 12px rgba(46,107,230,0.18);
          transition: transform 0.15s, box-shadow 0.15s;
          cursor: pointer;
        }
        .m-btn-primary:hover {
          transform: translateY(-1px);
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.18),
            0 2px 4px rgba(46,107,230,0.3),
            0 8px 20px rgba(46,107,230,0.25);
        }

        .m-btn-ghost {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: white;
          color: hsl(var(--m-ink));
          border: 1px solid hsl(var(--m-border));
          border-radius: 10px;
          padding: 7px 13px;
          font-weight: 500;
          font-size: 13px;
          line-height: 1;
          transition: all 0.15s;
          cursor: pointer;
        }
        .m-btn-ghost:hover {
          background: hsl(var(--m-accent-soft));
          color: hsl(var(--m-accent));
          border-color: hsl(var(--m-accent) / 0.3);
        }

        .m-icon-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 26px;
          height: 26px;
          border-radius: 8px;
          color: hsl(var(--m-muted));
          transition: all 0.15s;
        }
        .m-icon-btn:hover {
          background: hsl(var(--m-accent-soft));
          color: hsl(var(--m-accent));
        }

        .m-fade-in { animation: m-fade-in 0.4s ease-out; }
        @keyframes m-fade-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        .m-skeleton {
          background: linear-gradient(
            90deg,
            hsl(var(--m-border-soft)) 0%,
            hsl(var(--m-border)) 50%,
            hsl(var(--m-border-soft)) 100%
          );
          background-size: 200% 100%;
          animation: m-shimmer 1.6s linear infinite;
          border-radius: 6px;
        }
        @keyframes m-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        .m-typing-dot {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: hsl(var(--m-accent));
          animation: m-typing 1.2s ease-in-out infinite;
        }
        @keyframes m-typing {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30%           { transform: translateY(-4px); opacity: 1; }
        }

        .m-pulse {
          animation: m-pulse 1.6s ease-in-out infinite;
        }
        @keyframes m-pulse {
          0%, 100% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
          50%      { box-shadow: 0 0 0 6px transparent; opacity: 0.6; }
        }
      `,
      }}
    />
  );
}

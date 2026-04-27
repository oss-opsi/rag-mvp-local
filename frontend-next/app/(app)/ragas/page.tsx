"use client";

import * as React from "react";
import {
  Download,
  FileText,
  Info,
  KeyRound,
  LineChart as LineChartIcon,
  Loader2,
  Play,
  Upload,
} from "lucide-react";
import { Topbar } from "@/components/topbar";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";
import { api, type RagasMetrics, type RagasPerQuestion } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { ApiKeyInfo } from "@/lib/types";

type RagasResult = {
  per_question: RagasPerQuestion[];
  aggregate: RagasMetrics;
  ranAt: string;
  fileName: string;
  questionCount: number;
};

const METRIC_LABELS: Record<keyof RagasMetrics, string> = {
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy",
  context_precision: "Context precision",
  context_recall: "Context recall",
};

const METRIC_HINTS: Record<keyof RagasMetrics, string> = {
  faithfulness: "Réponses fidèles au contexte récupéré.",
  answer_relevancy: "La réponse traite-t-elle la question.",
  context_precision: "Le contexte récupéré est-il pertinent.",
  context_recall: "Le contexte couvre-t-il la vérité.",
};

function scoreColor(score: number): string {
  if (score >= 0.8) return "hsl(var(--success))";
  if (score >= 0.6) return "hsl(var(--violet))";
  if (score >= 0.4) return "hsl(var(--warning))";
  return "hsl(var(--danger))";
}

function GaugeCard({
  label,
  hint,
  value,
}: {
  label: string;
  hint: string;
  value: number | null;
}) {
  const pct = value === null || Number.isNaN(value) ? 0 : Math.max(0, Math.min(1, value));
  const display = value === null || Number.isNaN(value) ? "—" : (pct * 100).toFixed(0);
  const color = value === null ? "hsl(var(--muted-foreground))" : scoreColor(pct);
  const dash = `${pct * 251.2} 251.2`; // 2 * pi * 40

  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-soft bg-card p-5 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:shadow-tinted-md">
      <div className="relative">
        <svg width="120" height="120" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="hsl(var(--border-soft))"
            strokeWidth="10"
          />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={dash}
            transform="rotate(-90 50 50)"
            style={{ transition: "stroke-dasharray 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold tabular-nums" style={{ color }}>
            {display}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {value === null ? "—" : "/ 100"}
          </span>
        </div>
      </div>
      <div className="text-center">
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
      </div>
    </div>
  );
}

function ScoreCell({ value }: { value: number }) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className="text-muted-foreground">—</span>;
  }
  const pct = (value * 100).toFixed(0);
  const color = scoreColor(value);
  return (
    <span
      className="inline-flex h-6 min-w-[44px] items-center justify-center rounded-full border px-2 text-xs font-medium tabular-nums"
      style={{
        backgroundColor: `${color}14`, // ~8% opacity (soft)
        borderColor: `${color}40`, // ~25% opacity
        color,
      }}
    >
      {pct}
    </span>
  );
}

export default function RagasPage() {
  const { toast } = useToast();
  const [file, setFile] = React.useState<File | null>(null);
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<RagasResult | null>(null);
  const [keyInfo, setKeyInfo] = React.useState<ApiKeyInfo | null>(null);
  const [questionCount, setQuestionCount] = React.useState<number>(0);

  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    void api
      .getApiKey()
      .then((k) => setKeyInfo(k))
      .catch(() => setKeyInfo({ has_key: false }));
  }, []);

  // Quick CSV row counter (best-effort, client-side)
  React.useEffect(() => {
    if (!file) {
      setQuestionCount(0);
      return;
    }
    file
      .text()
      .then((txt) => {
        const lines = txt
          .split(/\r?\n/)
          .map((l) => l.trim())
          .filter(Boolean);
        // minus header
        setQuestionCount(Math.max(0, lines.length - 1));
      })
      .catch(() => setQuestionCount(0));
  }, [file]);

  const onPickFile = (f: File | null) => {
    setFile(f);
    setResult(null);
  };

  const handleRun = async () => {
    if (!file) {
      toast({
        title: "Aucun fichier",
        description: "Sélectionnez un CSV (question, ground_truth).",
        variant: "destructive",
      });
      return;
    }
    if (!keyInfo?.has_key) {
      toast({
        title: "Clé OpenAI manquante",
        description:
          "Ajoutez votre clé OpenAI dans Paramètres avant d'évaluer.",
        variant: "destructive",
      });
      return;
    }
    setRunning(true);
    try {
      const data = await api.evaluateRagas(file, "");
      setResult({
        per_question: data.per_question || [],
        aggregate: data.aggregate || {
          faithfulness: NaN,
          answer_relevancy: NaN,
          context_precision: NaN,
          context_recall: NaN,
        },
        ranAt: new Date().toISOString(),
        fileName: file.name,
        questionCount: (data.per_question || []).length,
      });
      toast({
        title: "Évaluation terminée",
        description: `${(data.per_question || []).length} question(s) évaluée(s).`,
      });
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    } finally {
      setRunning(false);
    }
  };

  const handleExport = () => {
    if (!result) return;
    const headers = [
      "question",
      "ground_truth",
      "answer",
      "faithfulness",
      "answer_relevancy",
      "context_precision",
      "context_recall",
    ];
    const escape = (v: unknown) => {
      const s = String(v ?? "");
      return `"${s.replace(/"/g, '""')}"`;
    };
    const rows = [headers.join(",")];
    for (const r of result.per_question) {
      rows.push(
        headers.map((h) => escape((r as Record<string, unknown>)[h])).join(","),
      );
    }
    const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ragas-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const aggregate = result?.aggregate;

  return (
    <div className="flex h-full flex-col">
      <Topbar
        breadcrumb={
          <>
            RAGAS <span className="mx-1.5 text-muted-foreground">—</span>
            <span className="font-normal text-muted-foreground">
              Évaluation
            </span>
          </>
        }
      >
        <span className="inline-flex items-center gap-1 rounded-full border border-violet/25 bg-violet-soft px-2.5 py-0.5 text-[11px] font-medium text-violet">
          <LineChartIcon className="h-3 w-3" />
          4 métriques
        </span>
      </Topbar>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-6 px-4 py-5 md:p-6 lg:grid-cols-[1fr_280px]">
          {/* Colonne principale */}
          <div className="flex flex-col gap-6">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-violet">
                Évaluation
              </div>
              <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
                RAGAS — qualité du pipeline
              </h1>
            </div>
            {/* Bandeau upload + run */}
            <section className="rounded-2xl border border-soft bg-card p-5 shadow-tinted-sm">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h2 className="text-base font-semibold">
                    Jeu d&apos;évaluation
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    CSV avec colonnes <code className="rounded bg-muted px-1">question</code>
                    {", "}
                    <code className="rounded bg-muted px-1">ground_truth</code> — 20 lignes max.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => onPickFile(e.target.files?.[0] || null)}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload className="mr-1.5 h-4 w-4" />
                    {file ? "Changer" : "Choisir un CSV"}
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => void handleRun()}
                    disabled={!file || running || !keyInfo?.has_key}
                  >
                    {running ? (
                      <>
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                        Évaluation...
                      </>
                    ) : (
                      <>
                        <Play className="mr-1.5 h-4 w-4" />
                        Lancer
                      </>
                    )}
                  </Button>
                </div>
              </div>

              {file ? (
                <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-dashed border-soft bg-muted/20 px-3 py-2 text-xs">
                  <FileText className="h-4 w-4 text-accent" />
                  <span className="font-medium text-foreground">{file.name}</span>
                  <span className="text-muted-foreground">
                    {(file.size / 1024).toFixed(1)} Ko
                  </span>
                  {questionCount > 0 ? (
                    <span className="inline-flex items-center rounded-full border border-soft bg-card px-2 py-0.5 text-[11px] font-medium text-muted-foreground tabular-nums">
                      {questionCount} question{questionCount > 1 ? "s" : ""}
                    </span>
                  ) : null}
                  {questionCount > 20 ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-warning/25 bg-warning-soft px-2 py-0.5 text-[11px] font-medium text-warning">
                      ⚠ seules les 20 premières seront évaluées
                    </span>
                  ) : null}
                </div>
              ) : null}
            </section>

            {/* Jauges */}
            <section>
              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="text-sm font-semibold">Scores agrégés</h3>
                {result ? (
                  <span className="text-xs text-muted-foreground">
                    {new Date(result.ranAt).toLocaleString("fr-FR")} · {result.questionCount} questions
                  </span>
                ) : null}
              </div>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {(Object.keys(METRIC_LABELS) as Array<keyof RagasMetrics>).map(
                  (k) => (
                    <GaugeCard
                      key={k}
                      label={METRIC_LABELS[k]}
                      hint={METRIC_HINTS[k]}
                      value={aggregate ? aggregate[k] : null}
                    />
                  ),
                )}
              </div>
            </section>

            {/* Tableau par question */}
            <section className="rounded-2xl border border-soft bg-card shadow-tinted-sm">
              <div className="flex items-center justify-between border-b border-soft px-5 py-3">
                <h3 className="text-sm font-semibold tracking-tight">Détail par question</h3>
                {result && result.per_question.length > 0 ? (
                  <Button variant="outline" size="sm" onClick={handleExport}>
                    <Download className="mr-1.5 h-4 w-4" />
                    Export CSV
                  </Button>
                ) : null}
              </div>
              {!result ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  Importez un CSV puis lancez une évaluation pour voir les
                  scores par question.
                </div>
              ) : result.per_question.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  Aucun résultat retourné.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-5 py-2.5 text-left font-medium">Question</th>
                        <th className="px-3 py-2.5 text-center font-medium">F</th>
                        <th className="px-3 py-2.5 text-center font-medium">AR</th>
                        <th className="px-3 py-2.5 text-center font-medium">CP</th>
                        <th className="px-3 py-2.5 text-center font-medium">CR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.per_question.map((r, i) => (
                        <tr
                          key={i}
                          className="border-t border-soft align-top transition-colors hover:bg-accent-soft/30"
                        >
                          <td className="px-5 py-3">
                            <div
                              className="line-clamp-2 max-w-[480px] font-medium text-foreground"
                              title={r.question}
                            >
                              {r.question}
                            </div>
                            <div
                              className="mt-1 line-clamp-1 max-w-[480px] text-xs text-muted-foreground"
                              title={r.ground_truth}
                            >
                              vérité : {r.ground_truth}
                            </div>
                          </td>
                          <td className="px-3 py-3 text-center"><ScoreCell value={r.faithfulness} /></td>
                          <td className="px-3 py-3 text-center"><ScoreCell value={r.answer_relevancy} /></td>
                          <td className="px-3 py-3 text-center"><ScoreCell value={r.context_precision} /></td>
                          <td className="px-3 py-3 text-center"><ScoreCell value={r.context_recall} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          {/* Sidebar info */}
          <aside className="flex flex-col gap-4">
            <section className="rounded-2xl border border-soft bg-card p-4 shadow-tinted-sm">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <Info className="h-4 w-4 text-accent" />
                Format CSV
              </div>
              <pre className="overflow-x-auto rounded-md border border-soft bg-muted/40 px-3 py-2 text-[11px] leading-relaxed">
{`question,ground_truth
"Quelle est la durée ?","12 mois"
"Combien de SLA ?","3 niveaux"`}
              </pre>
              <p className="mt-2 text-xs text-muted-foreground">
                Maximum 20 questions par évaluation.
              </p>
            </section>

            <section className="rounded-2xl border border-soft bg-card p-4 shadow-tinted-sm">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <KeyRound className="h-4 w-4 text-accent" />
                Clé OpenAI
              </div>
              {keyInfo?.has_key ? (
                <p className="text-xs text-muted-foreground">
                  Clé configurée :{" "}
                  <code className="rounded-md border border-soft bg-muted/40 px-1.5 py-0.5">{keyInfo.masked}</code>
                </p>
              ) : (
                <p className="text-xs text-warning">
                  Aucune clé. Configurez-la dans Paramètres avant d&apos;évaluer.
                </p>
              )}
            </section>

            <section className="rounded-2xl border border-soft bg-card p-4 shadow-tinted-sm">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <LineChartIcon className="h-4 w-4 text-violet" />
                Métriques
              </div>
              <ul className="space-y-2 text-xs text-muted-foreground">
                <li>
                  <span className="font-medium text-foreground">F · Faithfulness</span> — réponse fondée sur le contexte.
                </li>
                <li>
                  <span className="font-medium text-foreground">AR · Answer relevancy</span> — alignement question/réponse.
                </li>
                <li>
                  <span className="font-medium text-foreground">CP · Context precision</span> — pertinence du contexte.
                </li>
                <li>
                  <span className="font-medium text-foreground">CR · Context recall</span> — couverture vs. vérité.
                </li>
              </ul>
              <p className="mt-3 border-t border-soft pt-3 text-[11px] text-muted-foreground">
                Coût indicatif : ~0,18 $ pour 50 questions (gpt-4o-mini).
              </p>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}

const _unused = cn; // keep utility import warm
void _unused;

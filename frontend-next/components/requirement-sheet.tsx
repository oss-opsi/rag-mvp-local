"use client";

import * as React from "react";
import { CheckCircle2, Loader2, ShieldCheck, ThumbsDown, ThumbsUp, Trash2, Wand2 } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import {
  ConfidenceGauge,
  confidenceLabel,
  confidenceTextClass,
} from "@/components/confidence";
import {
  statusDotClass,
  statusLabel,
  statusPillClass,
} from "@/components/requirement-row";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  AnalysisJob,
  Requirement,
  RequirementCorrection,
  RequirementCorrectionVerdict,
  RequirementFeedback,
} from "@/lib/types";

function formatDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-FR");
}

export function RequirementSheet({
  requirement,
  analysisId,
  feedback,
  correction,
  open,
  onOpenChange,
  onFeedbackChange,
  onCorrectionChange,
  onAnalysisRefreshed,
}: {
  requirement: Requirement | null;
  analysisId?: number | string | null;
  feedback?: RequirementFeedback | null;
  correction?: RequirementCorrection | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFeedbackChange?: () => void | Promise<void>;
  onCorrectionChange?: () => void | Promise<void>;
  onAnalysisRefreshed?: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [vote, setVote] = React.useState<"up" | "down" | null>(null);
  const [comment, setComment] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [showBreakdown, setShowBreakdown] = React.useState(false);
  const [repassBusy, setRepassBusy] = React.useState(false);

  // État local pour la correction validée.
  const [corrVerdict, setCorrVerdict] =
    React.useState<RequirementCorrectionVerdict | null>(null);
  const [corrAnswer, setCorrAnswer] = React.useState("");
  const [corrNotes, setCorrNotes] = React.useState("");
  const [corrBusy, setCorrBusy] = React.useState(false);
  const [corrEditing, setCorrEditing] = React.useState(false);

  // Reset local state quand on change d'exigence ou que le feedback change.
  React.useEffect(() => {
    setVote(feedback?.vote ?? null);
    setComment(feedback?.comment ?? "");
    setEditing(false);
    setShowBreakdown(false);
  }, [requirement?.id, feedback?.vote, feedback?.comment]);

  // Reset correction state quand l'exigence ou la correction change.
  React.useEffect(() => {
    setCorrVerdict(correction?.verdict ?? null);
    setCorrAnswer(correction?.answer ?? "");
    setCorrNotes(correction?.notes ?? "");
    setCorrEditing(false);
  }, [requirement?.id, correction?.verdict, correction?.answer, correction?.notes]);

  const launchRepass = async () => {
    if (!requirement || !analysisId) return;
    setRepassBusy(true);
    try {
      const job = await api.repassAnalysis(analysisId, {
        requirementIds: [requirement.id],
      });
      const POLL_INTERVAL_MS = 3000;
      let final: AnalysisJob | null = null;
      while (true) {
        const j = await api.analysisJob(job.id);
        if (j.status === "done" || j.status === "error") {
          final = j;
          break;
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
      if (final.status === "error") {
        toast({
          title: "Échec du re-pass",
          description: final.error || "Erreur inconnue",
          variant: "destructive",
        });
        return;
      }
      toast({
        title: "Re-pass terminé",
        description: `Verdict re-passé pour ${requirement.id}`,
      });
      if (onAnalysisRefreshed) await onAnalysisRefreshed();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de re-pass";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setRepassBusy(false);
    }
  };

  const canEdit = analysisId !== null && analysisId !== undefined;
  const hasSavedFeedback = !!feedback;
  const showFeedbackForm = !hasSavedFeedback || editing;

  const hasSavedCorrection = !!correction;
  const showCorrectionForm = !hasSavedCorrection || corrEditing;

  const submitCorrection = async () => {
    if (!requirement || !analysisId || !corrVerdict) return;
    if (!corrAnswer.trim()) {
      toast({
        title: "Description manquante",
        description: "Décrivez la couverture validée.",
        variant: "destructive",
      });
      return;
    }
    setCorrBusy(true);
    try {
      await api.submitCorrection(analysisId, requirement.id, {
        verdict: corrVerdict,
        answer: corrAnswer.trim(),
        notes: corrNotes.trim() || null,
        category: requirement.category,
        subdomain: requirement.subdomain ?? null,
        title: requirement.title,
      });
      toast({ title: "Correction enregistrée" });
      setCorrEditing(false);
      if (onCorrectionChange) await onCorrectionChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'enregistrement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setCorrBusy(false);
    }
  };

  const removeCorrection = async () => {
    if (!requirement || !analysisId) return;
    setCorrBusy(true);
    try {
      await api.deleteCorrection(analysisId, requirement.id);
      setCorrVerdict(null);
      setCorrAnswer("");
      setCorrNotes("");
      setCorrEditing(false);
      toast({ title: "Correction supprimée" });
      if (onCorrectionChange) await onCorrectionChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de suppression";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setCorrBusy(false);
    }
  };

  const submitVote = async () => {
    if (!requirement || !analysisId || !vote) return;
    setBusy(true);
    try {
      await api.submitFeedback(
        analysisId,
        requirement.id,
        vote,
        comment.trim() || null,
      );
      toast({ title: "Votre avis est enregistré" });
      setEditing(false);
      if (onFeedbackChange) await onFeedbackChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'enregistrement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const removeFeedback = async () => {
    if (!requirement || !analysisId) return;
    setBusy(true);
    try {
      await api.deleteFeedback(analysisId, requirement.id);
      setVote(null);
      setComment("");
      setEditing(false);
      toast({ title: "Avis supprimé" });
      if (onFeedbackChange) await onFeedbackChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de suppression";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
        {requirement ? (
          <>
            <SheetHeader className="border-b border-soft p-6">
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "h-2.5 w-2.5 shrink-0 rounded-full",
                    statusDotClass(requirement.status)
                  )}
                  aria-hidden
                />
                <span className="font-mono text-xs text-muted-foreground">
                  {requirement.id}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-xs",
                    statusPillClass(requirement.status)
                  )}
                >
                  {statusLabel(requirement.status)}
                </span>
                {requirement.hyde_used ? (
                  <Badge variant="outline" className="text-[10px]">
                    HyDE
                  </Badge>
                ) : null}
                {requirement.repass_used ? (
                  <Badge variant="outline" className="text-[10px]">
                    re-pass
                  </Badge>
                ) : null}
              </div>
              <SheetTitle className="mt-1 text-xl">{requirement.title}</SheetTitle>
              <SheetDescription>
                {requirement.category}
                {requirement.subdomain ? ` · ${requirement.subdomain}` : ""}
              </SheetDescription>
            </SheetHeader>
            <ScrollArea className="flex-1">
              <div className="flex flex-col gap-5 p-6">
                {typeof requirement.confidence === "number" &&
                Number.isFinite(requirement.confidence) ? (
                  <section>
                    <button
                      type="button"
                      onClick={() => setShowBreakdown((v) => !v)}
                      className="block w-full text-left"
                      title="Cliquez pour voir le détail LLM/Retrieval"
                    >
                      <ConfidenceGauge
                        value={requirement.confidence}
                        caption="Score de confiance"
                      />
                      <div
                        className={cn(
                          "mt-1 text-xs font-medium",
                          confidenceTextClass(requirement.confidence),
                        )}
                      >
                        {confidenceLabel(requirement.confidence)}
                      </div>
                    </button>
                    {showBreakdown ? (
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
                        {typeof requirement.llm_confidence === "number" ? (
                          <span>
                            LLM :{" "}
                            <span className="tabular-nums text-foreground">
                              {Math.round(requirement.llm_confidence * 100)}%
                            </span>
                          </span>
                        ) : null}
                        {typeof requirement.retrieval_confidence === "number" ? (
                          <span>
                            Retrieval :{" "}
                            <span className="tabular-nums text-foreground">
                              {Math.round(requirement.retrieval_confidence * 100)}%
                            </span>
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {requirement.description ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Description
                    </h3>
                    <p className="text-sm text-foreground">
                      {requirement.description}
                    </p>
                  </section>
                ) : null}

                {requirement.acceptance_criteria &&
                requirement.acceptance_criteria.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Critères d'acceptation
                    </h3>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {requirement.acceptance_criteria.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <Separator />

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Verdict
                  </h3>
                  <p className="whitespace-pre-wrap text-sm text-foreground">
                    {requirement.verdict || "—"}
                  </p>
                </section>

                {requirement.evidence && requirement.evidence.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Preuves
                    </h3>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {requirement.evidence.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                {requirement.sources && requirement.sources.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Sources citées
                    </h3>
                    <div className="flex flex-col gap-3">
                      {requirement.sources.map((s, i) => (
                        <div
                          key={i}
                          className="rounded-md border border-soft p-3"
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">
                              {s.source}
                            </span>
                            {s.page !== undefined && s.page !== null ? (
                              <span>· page {String(s.page)}</span>
                            ) : null}
                            {typeof s.score === "number" ? (
                              <span>
                                · score{" "}
                                <span className="tabular-nums">
                                  {s.score.toFixed(3)}
                                </span>
                              </span>
                            ) : null}
                          </div>
                          <p className="whitespace-pre-wrap text-sm text-foreground">
                            {s.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}

                {canEdit ? (
                  <>
                    <Separator />
                    <section>
                      <div className="mb-1 flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
                        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Correction validée
                        </h3>
                      </div>
                      <p className="mb-3 text-xs text-muted-foreground">
                        Saisissez le verdict réel et la description de la
                        couverture. Cette correction écrase le verdict du LLM
                        et sera réutilisée à la ré-analyse de ce CDC{" "}
                        <strong>et sur les futurs CDCs</strong> contenant la
                        même exigence.
                      </p>

                      {hasSavedCorrection && !corrEditing ? (
                        <div className="rounded-2xl border border-accent/25 bg-accent-soft/50 p-3 shadow-tinted-sm">
                          <div className="flex flex-wrap items-center gap-2 text-sm">
                            <CheckCircle2
                              className="h-4 w-4 text-accent"
                              aria-hidden
                            />
                            <span>
                              Verdict validé :{" "}
                              <strong>
                                {correction!.verdict === "covered"
                                  ? "Couvert"
                                  : correction!.verdict === "partial"
                                  ? "Partiel"
                                  : "Manquant"}
                              </strong>
                              {correction!.updated_at
                                ? ` · ${formatDate(correction!.updated_at)}`
                                : ""}
                            </span>
                          </div>
                          <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">
                            {correction!.answer}
                          </p>
                          {correction!.notes ? (
                            <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
                              Notes : {correction!.notes}
                            </p>
                          ) : null}
                          <div className="mt-3 flex gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setCorrEditing(true)}
                              disabled={corrBusy}
                            >
                              Modifier
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void removeCorrection()}
                              disabled={corrBusy}
                              className="text-danger hover:text-danger"
                            >
                              {corrBusy ? (
                                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="mr-1 h-3 w-3" />
                              )}
                              Effacer
                            </Button>
                          </div>
                        </div>
                      ) : null}

                      {showCorrectionForm ? (
                        <div className="space-y-3">
                          <div className="grid grid-cols-3 gap-2">
                            {(
                              [
                                {
                                  v: "covered" as const,
                                  label: "Couvert",
                                  active:
                                    "border-success/40 bg-success-soft text-success",
                                },
                                {
                                  v: "partial" as const,
                                  label: "Partiel",
                                  active:
                                    "border-warning/40 bg-warning-soft text-warning",
                                },
                                {
                                  v: "missing" as const,
                                  label: "Manquant",
                                  active:
                                    "border-danger/40 bg-danger-soft text-danger",
                                },
                              ]
                            ).map((opt) => (
                              <button
                                key={opt.v}
                                type="button"
                                onClick={() => setCorrVerdict(opt.v)}
                                className={cn(
                                  "rounded-full border px-3 py-2 text-sm font-medium transition-all",
                                  corrVerdict === opt.v
                                    ? opt.active
                                    : "border-soft bg-background text-muted-foreground hover:border-accent/30 hover:text-accent",
                                )}
                                disabled={corrBusy}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                          <Textarea
                            value={corrAnswer}
                            onChange={(e) => setCorrAnswer(e.target.value)}
                            placeholder="Décrivez précisément comment la solution couvre (ou non) cette exigence — cette description remplace le verdict du LLM."
                            disabled={corrBusy}
                            rows={5}
                          />
                          <Textarea
                            value={corrNotes}
                            onChange={(e) => setCorrNotes(e.target.value)}
                            placeholder="Notes internes (optionnel)"
                            disabled={corrBusy}
                            rows={2}
                          />
                          <div className="flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              onClick={() => void submitCorrection()}
                              disabled={
                                corrBusy || !corrVerdict || !corrAnswer.trim()
                              }
                            >
                              {corrBusy ? (
                                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                              ) : null}
                              Enregistrer la correction
                            </Button>
                            {hasSavedCorrection && corrEditing ? (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setCorrEditing(false);
                                  setCorrVerdict(correction?.verdict ?? null);
                                  setCorrAnswer(correction?.answer ?? "");
                                  setCorrNotes(correction?.notes ?? "");
                                }}
                                disabled={corrBusy}
                              >
                                Annuler
                              </Button>
                            ) : null}
                          </div>
                          <p className="text-[11px] text-muted-foreground">
                            Sera ré-utilisé sur les futurs CDCs contenant une
                            exigence avec la même catégorie, le même
                            sous-domaine et le même titre.
                          </p>
                        </div>
                      ) : null}
                    </section>

                    <Separator />

                    <section>
                      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Votre avis sur ce verdict
                      </h3>
                      <p className="mb-3 text-xs text-muted-foreground">
                        Aidez-nous à améliorer la qualité de l'analyse en
                        signalant les verdicts pertinents ou à revoir.
                      </p>

                      {hasSavedFeedback && !editing ? (
                        <div className="rounded-md border border-soft p-3">
                          <div className="flex flex-wrap items-center gap-2 text-sm">
                            {feedback!.vote === "up" ? (
                              <ThumbsUp className="h-4 w-4 text-accent" aria-hidden />
                            ) : (
                              <ThumbsDown className="h-4 w-4 text-danger" aria-hidden />
                            )}
                            <span>
                              Vous avez signalé un verdict{" "}
                              <strong>
                                {feedback!.vote === "up"
                                  ? "pertinent"
                                  : "à revoir"}
                              </strong>
                              {feedback!.updated_at
                                ? ` le ${formatDate(feedback!.updated_at)}`
                                : ""}
                              .
                            </span>
                          </div>
                          {feedback!.comment ? (
                            <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
                              « {feedback!.comment} »
                            </p>
                          ) : null}
                          <div className="mt-3 flex gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setEditing(true)}
                              disabled={busy}
                            >
                              Modifier
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void removeFeedback()}
                              disabled={busy}
                              className="text-danger hover:text-danger"
                            >
                              {busy ? (
                                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="mr-1 h-3 w-3" />
                              )}
                              Supprimer
                            </Button>
                          </div>
                        </div>
                      ) : null}

                      {showFeedbackForm ? (
                        <div className="space-y-3">
                          <div className="grid grid-cols-2 gap-2">
                            <button
                              type="button"
                              onClick={() => setVote("up")}
                              className={cn(
                                "flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
                                vote === "up"
                                  ? "border-accent bg-accent/10 text-accent"
                                  : "border-soft bg-background hover:bg-muted/50",
                              )}
                              disabled={busy}
                            >
                              <ThumbsUp className="h-4 w-4" aria-hidden />
                              Verdict pertinent
                            </button>
                            <button
                              type="button"
                              onClick={() => setVote("down")}
                              className={cn(
                                "flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
                                vote === "down"
                                  ? "border-danger bg-danger/10 text-danger"
                                  : "border-soft bg-background hover:bg-muted/50",
                              )}
                              disabled={busy}
                            >
                              <ThumbsDown className="h-4 w-4" aria-hidden />
                              Verdict à revoir
                            </button>
                          </div>
                          <Textarea
                            value={comment}
                            onChange={(e) => setComment(e.target.value)}
                            placeholder="Commentaire optionnel — précisez ce qui manque ou ce qui est inexact"
                            disabled={busy}
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={() => void submitVote()}
                              disabled={busy || !vote}
                            >
                              {busy ? (
                                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                              ) : null}
                              Enregistrer mon avis
                            </Button>
                            {hasSavedFeedback && editing ? (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setEditing(false);
                                  setVote(feedback?.vote ?? null);
                                  setComment(feedback?.comment ?? "");
                                }}
                                disabled={busy}
                              >
                                Annuler
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      ) : null}
                    </section>

                    <Separator />

                    <section>
                      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Re-pass GPT-4o
                      </h3>
                      <div className="flex flex-wrap items-center gap-2">
                        {requirement.repass_applied ? (
                          <Badge variant="outline" className="text-[10px]">
                            {requirement.repass_reason === "batch_user_request"
                              ? "Verdict re-passé à votre demande"
                              : "Verdict re-passé avec gpt-4o"}
                            {requirement.repass_model
                              ? ` · ${requirement.repass_model}`
                              : ""}
                          </Badge>
                        ) : null}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void launchRepass()}
                          disabled={repassBusy || hasSavedCorrection}
                          title={
                            hasSavedCorrection
                              ? "Une correction validée existe — votre verdict humain l'emporte, le repass est inutile."
                              : undefined
                          }
                        >
                          {repassBusy ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Wand2 className="mr-2 h-4 w-4" />
                          )}
                          Re-passer cette exigence
                        </Button>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {hasSavedCorrection
                          ? "Bouton désactivé : votre correction validée l'emporte sur le verdict du LLM. Effacez la correction si vous voulez relancer GPT-4o."
                          : "Relance un verdict GPT-4o sur cette seule exigence. L'historique précédent reste consultable."}
                      </p>
                    </section>
                  </>
                ) : null}
              </div>
            </ScrollArea>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

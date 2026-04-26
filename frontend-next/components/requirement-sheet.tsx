"use client";

import * as React from "react";
import { Loader2, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
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
import type { Requirement, RequirementFeedback } from "@/lib/types";

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
  open,
  onOpenChange,
  onFeedbackChange,
}: {
  requirement: Requirement | null;
  analysisId?: number | string | null;
  feedback?: RequirementFeedback | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFeedbackChange?: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [vote, setVote] = React.useState<"up" | "down" | null>(null);
  const [comment, setComment] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [showBreakdown, setShowBreakdown] = React.useState(false);

  // Reset local state quand on change d'exigence ou que le feedback change.
  React.useEffect(() => {
    setVote(feedback?.vote ?? null);
    setComment(feedback?.comment ?? "");
    setEditing(false);
    setShowBreakdown(false);
  }, [requirement?.id, feedback?.vote, feedback?.comment]);

  const canEdit = analysisId !== null && analysisId !== undefined;
  const hasSavedFeedback = !!feedback;
  const showFeedbackForm = !hasSavedFeedback || editing;

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
            <SheetHeader className="border-b border-border p-6">
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
                          className="rounded-md border border-border p-3"
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
                      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Votre avis sur ce verdict
                      </h3>
                      <p className="mb-3 text-xs text-muted-foreground">
                        Aidez-nous à améliorer la qualité de l'analyse en
                        signalant les verdicts pertinents ou à revoir.
                      </p>

                      {hasSavedFeedback && !editing ? (
                        <div className="rounded-md border border-border p-3">
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
                                  : "border-border bg-background hover:bg-muted/50",
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
                                  : "border-border bg-background hover:bg-muted/50",
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

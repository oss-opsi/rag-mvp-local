"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { api, type LlmSettings } from "@/lib/api-client";

/**
 * Carte « Modèles LLM » — réservée aux admins.
 * 3 sélecteurs : Chat / Analyse / Re-pass.
 *
 * Les indications de coût sont relatives à gpt-4o-mini (tarifs OpenAI
 * publics avril 2026 ; à mettre à jour si OpenAI change ses prix).
 */

const COST_HINT: Record<string, string> = {
  "gpt-4o-mini": "économique",
  "gpt-4o": "~17× plus cher",
  "gpt-5": "~50× plus cher",
};

const QUALITY_HINT: Record<string, string> = {
  "gpt-4o-mini": "rapide",
  "gpt-4o": "équilibré",
  "gpt-5": "qualité maximale",
};

const FIELDS: { key: keyof LlmSettings; label: string; hint: string }[] = [
  {
    key: "llm_chat",
    label: "Chat",
    hint: "Modèle qui répond aux questions dans la page Chat. Choisir un modèle rapide pour un streaming fluide.",
  },
  {
    key: "llm_analysis",
    label: "Analyse de cahier des charges",
    hint: "Premier passage sur chaque exigence. Beaucoup d'appels, donc le coût se cumule rapidement.",
  },
  {
    key: "llm_repass",
    label: "Re-pass sur verdicts ambigus",
    hint: "Repasse uniquement les exigences douteuses (~10–20 %). Idéal pour fiabiliser sans exploser le coût.",
  },
];

export function LlmModelsCard() {
  const { toast } = useToast();
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [allowed, setAllowed] = React.useState<string[]>([]);
  const [values, setValues] = React.useState<LlmSettings | null>(null);
  const [draft, setDraft] = React.useState<LlmSettings | null>(null);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.adminGetLlmSettings();
      setAllowed(r.allowed);
      setValues(r.settings);
      setDraft(r.settings);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const dirty =
    values !== null &&
    draft !== null &&
    (draft.llm_chat !== values.llm_chat ||
      draft.llm_analysis !== values.llm_analysis ||
      draft.llm_repass !== values.llm_repass);

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const r = await api.adminSetLlmSettings(draft);
      setValues(r.settings);
      setDraft(r.settings);
      toast({ title: "Modèles mis à jour" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (values) setDraft(values);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement...
      </div>
    );
  }

  if (!draft) return null;

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted-foreground">
        Choisissez le modèle OpenAI utilisé par chaque pipeline. Les changements
        s'appliquent immédiatement aux nouvelles requêtes ; les analyses en
        cours conservent leur modèle initial.
      </p>

      {FIELDS.map((f) => (
        <div key={f.key} className="space-y-2">
          <div>
            <Label htmlFor={f.key} className="text-sm font-semibold">
              {f.label}
            </Label>
            <p className="mt-0.5 text-xs text-muted-foreground">{f.hint}</p>
          </div>
          <select
            id={f.key}
            value={draft[f.key]}
            onChange={(e) =>
              setDraft({ ...draft, [f.key]: e.target.value } as LlmSettings)
            }
            className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
          >
            {allowed.map((m) => (
              <option key={m} value={m}>
                {m}
                {COST_HINT[m] ? ` — ${QUALITY_HINT[m]} · ${COST_HINT[m]}` : ""}
              </option>
            ))}
          </select>
        </div>
      ))}

      <div className="flex items-center gap-2 pt-2">
        <Button
          onClick={() => void handleSave()}
          disabled={!dirty || saving}
        >
          {saving ? "Enregistrement..." : "Enregistrer"}
        </Button>
        <Button variant="outline" onClick={handleReset} disabled={!dirty || saving}>
          Annuler
        </Button>
      </div>
    </div>
  );
}

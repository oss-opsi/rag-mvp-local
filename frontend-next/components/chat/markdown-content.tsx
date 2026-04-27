"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

/**
 * Rendu Markdown sobre pour les réponses de l'assistant.
 * Le LLM répond souvent en Markdown (titres, listes, gras, code) — sans rendu,
 * le texte brut s'étalerait sans mise en forme. On limite aussi le débordement
 * horizontal pour les longues URL / chaînes sans espace via break-words sur
 * les paragraphes et overflow-x sur les blocs de code.
 */
export function MarkdownContent({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "max-w-full text-sm leading-relaxed [overflow-wrap:anywhere]",
        // espacements verticaux minimes entre éléments
        "[&>*]:my-0 [&>*+*]:mt-2",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-base font-semibold">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-semibold">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-sm font-semibold">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="whitespace-pre-wrap">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc space-y-1 pl-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-1 pl-5">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="[&>p]:my-0">{children}</li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline underline-offset-2 hover:text-accent-hover"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-soft pl-3 text-muted-foreground">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            if (isInline) {
              return (
                <code
                  className="rounded bg-black/5 px-1 py-0.5 font-mono text-[0.85em]"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={cn("font-mono text-[0.85em]", className)} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="max-w-full overflow-x-auto rounded-md bg-black/5 p-3 text-xs">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="max-w-full overflow-x-auto">
              <table className="min-w-full border-collapse text-xs">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-soft px-2 py-1 text-left font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-soft px-2 py-1 align-top">
              {children}
            </td>
          ),
          hr: () => <hr className="my-2 border-soft" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

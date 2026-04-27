import * as React from "react";
import { cn } from "@/lib/utils";

function colorForPercent(pct: number): string {
  if (pct >= 70) return "hsl(var(--success))";
  if (pct >= 40) return "hsl(var(--warning))";
  return "hsl(var(--danger))";
}

export function CoverageDonut({
  percent,
  size = 160,
  stroke = 14,
  className,
}: {
  percent: number;
  size?: number;
  stroke?: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const color = colorForPercent(clamped);

  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} role="img" aria-label={`Couverture ${clamped.toFixed(0)}%`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--border-soft))"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 600ms ease" }}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-3xl font-bold tabular-nums">
          {clamped.toFixed(0)}%
        </div>
        <div className="text-xs text-muted-foreground">Couverture</div>
      </div>
    </div>
  );
}

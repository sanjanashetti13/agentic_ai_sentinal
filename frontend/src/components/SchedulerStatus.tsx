import { Check, TriangleAlert } from "lucide-react";
import { Spinner } from "@/components/ui/reui-spinner";
import type { SystemStatus } from "../types";

type StepTone = "muted" | "success" | "warning";

type StatusStep = {
  tone: StepTone;
  spinning: boolean;
  ticked?: boolean;
  label: string;
  detail?: string;
};

function stepsFor(status: SystemStatus | null | undefined): StatusStep[] {
  const every = status?.scheduler_interval_seconds ?? 10;

  if (!status) {
    return [
      {
        tone: "warning",
        spinning: true,
        label: "Scheduler not confirmed",
        detail: "waiting for API status",
      },
    ];
  }

  if (status.scheduler === "ok") {
    return [
      {
        tone: "success",
        spinning: false,
        ticked: true,
        label: "Scheduler running",
        detail: `n8n every ${every} seconds`,
      },
      {
        tone: "muted",
        spinning: false,
        ticked: true,
        label: status.message,
      },
    ];
  }

  if (status.scheduler === "never") {
    return [
      {
        tone: "muted",
        spinning: true,
        label: "Waiting for first scheduled check",
        detail: `n8n every ${every} seconds`,
      },
      {
        tone: "warning",
        spinning: false,
        label: status.message,
      },
    ];
  }

  if (status.scheduler === "stale") {
    return [
      {
        tone: "warning",
        spinning: true,
        label: "Scheduler not running",
        detail: "n8n has not checked recently",
      },
      {
        tone: "warning",
        spinning: false,
        label: status.message,
      },
    ];
  }

  return [
    {
      tone: "muted",
      spinning: false,
      label: "Scheduler idle",
      detail: "no enabled website monitors",
    },
    {
      tone: "muted",
      spinning: false,
      label: status.message,
    },
  ];
}

function bannerTone(
  status: SystemStatus | null | undefined,
): "ok" | "warning" | "idle" {
  if (!status) {
    return "warning";
  }
  if (status.scheduler === "ok") {
    return "ok";
  }
  if (status.scheduler === "idle") {
    return "idle";
  }
  return "warning";
}

export function SchedulerStatus({
  status,
}: {
  status: SystemStatus | null | undefined;
}) {
  const steps = stepsFor(status);
  const tone = bannerTone(status);
  const title = steps[0];
  const rest = steps.slice(1);

  return (
    <div
      className={`scheduler-status scheduler-${tone}`}
      role="status"
      aria-live="polite"
    >
      <div className="scheduler-badge" aria-hidden="true">
        {tone === "ok" ? (
          <Check className="h-4 w-4" />
        ) : title?.spinning ? (
          <Spinner className="size-4" />
        ) : (
          <TriangleAlert className="h-4 w-4" />
        )}
      </div>
      <div className="scheduler-copy">
        {title ? (
          <div className="scheduler-title">
            {title.label}
            {title.detail ? (
              <span className="scheduler-detail"> — {title.detail}</span>
            ) : null}
          </div>
        ) : null}
        {rest.map((step, index) => (
          <div
            className="scheduler-detail"
            key={`${step.label}-${step.detail ?? index}`}
          >
            {step.label}
          </div>
        ))}
      </div>
    </div>
  );
}

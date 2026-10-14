"use client";

import { useRef, useState } from "react";
import { Check, X, Clock, RotateCcw } from "lucide-react";
import { cx } from "@/components/ui/utils";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { type PortalApprovalInfo, submitRecommendationApproval } from "@/services/portalService";

interface PortalApprovalButtonsProps {
  projectId: string;
  auditId: number;
  recommendationKey: string;
  currentApproval: PortalApprovalInfo | null;
  onApprovalChange?: () => void;
}

type ApprovalAction = "approved" | "rejected" | "deferred";

const statusConfig: Record<
  ApprovalAction,
  { label: string; color: "success" | "warning" | "danger"; icon: typeof Check }
> = {
  approved: { label: "Approved", color: "success", icon: Check },
  rejected: { label: "Rejected", color: "danger", icon: X },
  deferred: { label: "Deferred", color: "warning", icon: Clock },
};

export function PortalApprovalButtons({
  projectId,
  auditId,
  recommendationKey,
  currentApproval,
  onApprovalChange,
}: PortalApprovalButtonsProps) {
  const [approval, setApproval] = useState<PortalApprovalInfo | null>(currentApproval);
  const [isEditing, setIsEditing] = useState(false);
  const [loadingAction, setLoadingAction] = useState<ApprovalAction | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const submissionInFlight = useRef(false);

  const handleApproval = async (action: ApprovalAction) => {
    if (submissionInFlight.current) return;

    submissionInFlight.current = true;
    setLoadingAction(action);
    setSubmitError(null);
    try {
      const updatedApproval = await submitRecommendationApproval(
        projectId,
        auditId,
        recommendationKey,
        action
      );
      setApproval(updatedApproval);
      setIsEditing(false);
      onApprovalChange?.();
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Unable to submit recommendation approval."
      );
    } finally {
      submissionInFlight.current = false;
      setLoadingAction(null);
    }
  };

  const showButtons = !approval || isEditing;

  if (!showButtons && approval) {
    const config = statusConfig[approval.status as ApprovalAction];
    if (!config) return null;
    const Icon = config.icon;

    return (
      <div className="flex items-center gap-2">
        <Badge color={config.color}>
          <Icon className="mr-1 h-3 w-3" />
          {config.label}
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsEditing(true)}
          className={cx(
            "h-6 px-1.5 text-xs",
            "text-(--muted-foreground) hover:text-(--foreground)"
          )}
        >
          <RotateCcw className="mr-1 h-3 w-3" />
          Change
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleApproval("approved")}
          loading={loadingAction === "approved"}
          loadingText="…"
          disabled={loadingAction !== null}
          className={cx(
            "h-7 px-2 text-xs",
            "border-emerald-600/50 text-emerald-400",
            "hover:bg-emerald-600/10 hover:border-emerald-500"
          )}
        >
          <Check className="mr-1 h-3 w-3" />
          Approve
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={() => handleApproval("rejected")}
          loading={loadingAction === "rejected"}
          loadingText="…"
          disabled={loadingAction !== null}
          className={cx(
            "h-7 px-2 text-xs",
            "border-red-600/50 text-red-400",
            "hover:bg-red-600/10 hover:border-red-500"
          )}
        >
          <X className="mr-1 h-3 w-3" />
          Reject
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={() => handleApproval("deferred")}
          loading={loadingAction === "deferred"}
          loadingText="…"
          disabled={loadingAction !== null}
          className={cx(
            "h-7 px-2 text-xs",
            "border-yellow-600/50 text-yellow-400",
            "hover:bg-yellow-600/10 hover:border-yellow-500"
          )}
        >
          <Clock className="mr-1 h-3 w-3" />
          Defer
        </Button>

        {isEditing && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setIsEditing(false);
              setSubmitError(null);
            }}
            disabled={loadingAction !== null}
            className="h-7 px-1.5 text-xs text-(--muted-foreground)"
          >
            Cancel
          </Button>
        )}
      </div>
      {submitError && (
        <p role="alert" className="text-xs text-red-400">
          {submitError}
        </p>
      )}
    </div>
  );
}

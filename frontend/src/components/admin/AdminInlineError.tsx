import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import Button from "@/components/ui/Button";

interface AdminInlineErrorProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Styled inline error card for admin pages.
 * Shows error message with optional retry button.
 */
export function AdminInlineError({ message, onRetry, className = "" }: AdminInlineErrorProps) {
  return (
    <Alert variant="destructive" className={className}>
      <AlertTriangle />
      <AlertTitle>Error</AlertTitle>
      <AlertDescription className="flex items-center justify-between gap-4">
        <span>{message}</span>
        {onRetry && (
          <Button variant="ghost" size="sm" onClick={onRetry} className="shrink-0">
            <RefreshCw size={12} />
            Retry
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

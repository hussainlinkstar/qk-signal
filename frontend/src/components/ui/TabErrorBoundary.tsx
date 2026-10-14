"use client";

import React, { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCcw } from "lucide-react";
import { toast } from "sonner";
import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";

type Props = {
  /** Human-readable name of the wrapped section (e.g. "AEO Analysis") */
  sectionName: string;
  children: ReactNode;
};

type State = {
  hasError: boolean;
  error: Error | null;
};

/**
 * TabErrorBoundary, wraps individual tab modules so that a crash
 * in one section (e.g. AEO) doesn't take down the whole workspace.
 */
export default class TabErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error(`[TabErrorBoundary] ${this.props.sectionName} crashed:`, error, errorInfo);
    toast.error(`${this.props.sectionName} encountered an error. Other tabs still work.`);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <SignalAlert
          tone="danger"
          title={`${this.props.sectionName} failed to render`}
          actions={
            <button type="button" onClick={this.handleRetry} className={SIGNAL_ALERT_ACTION}>
              <RefreshCcw className="h-4 w-4" />
              Try Again
            </button>
          }
        >
          <p>This section encountered an unexpected error. Your other tabs are unaffected.</p>
          {this.state.error && <p className="mt-2 break-words">{this.state.error.message}</p>}
        </SignalAlert>
      );
    }

    return this.props.children;
  }
}

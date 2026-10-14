"use client";

import React from "react";
import TextField from "./TextField";
import { cx } from "./utils";
import { Loader2, Search, Lock } from "lucide-react";

interface CyberFieldProps extends React.ComponentProps<typeof TextField> {
  icon?: React.ReactNode;
  leftIcon?: React.ReactNode;
  onAction?: () => void;
  actionLoading?: boolean;
}

const CyberField = ({ icon, leftIcon, onAction, actionLoading, ...props }: CyberFieldProps) => (
  <div className="relative group/field">
    {leftIcon && (
      <div className="pointer-events-none absolute bottom-0 left-4 flex h-[42px] items-center text-(--text-muted) transition-colors duration-300 group-focus-within/field:text-primary">
        {React.cloneElement(leftIcon as React.ReactElement, { size: 14 })}
      </div>
    )}
    <TextField
      {...props}
      className={cx(
        "transition-[border-color,background-color,box-shadow,color] duration-300",
        leftIcon && "pl-11",
        props.readOnly && " opacity-80 cursor-not-allowed",
        props.className
      )}
    />
    {props.readOnly && (
      <div className="absolute right-3 top-[34px] text-(--text-muted)">
        <Lock className="h-3 w-3" />
      </div>
    )}
    {onAction && !props.readOnly && (
      <button
        type="button"
        onClick={onAction}
        disabled={actionLoading}
        className="absolute right-1 top-[26px] flex h-10 w-10 items-center justify-center text-(--text-muted) hover:text-primary transition-colors"
      >
        {actionLoading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          icon || <Search className="h-3 w-3" />
        )}
      </button>
    )}
  </div>
);

export default CyberField;

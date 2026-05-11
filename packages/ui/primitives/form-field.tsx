"use client";

import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type HTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "../lib/cn";
import { Label } from "./label";

/**
 * Lightweight form-field plumbing. Wraps a label + control + help text +
 * error message so all four are wired together via `id` /
 * `aria-describedby` / `aria-invalid` without the caller having to think
 * about it.
 *
 * Usage:
 *   <FormField name="email" label="Email" required error={errors.email?.message}>
 *     <Input type="email" autoComplete="email" />
 *   </FormField>
 *
 * The single child receives:
 *   - `id`
 *   - `aria-describedby` (pointing at help + error)
 *   - `aria-invalid="true"` when `error` is set
 *   - `aria-required="true"` when `required`
 */

interface FormFieldContextValue {
  id: string;
  helpId?: string;
  errorId?: string;
  invalid: boolean;
  required: boolean;
}
const FormFieldContext = createContext<FormFieldContextValue | null>(null);

export function useFormField() {
  return useContext(FormFieldContext);
}

interface FormFieldProps {
  /** Label rendered above the control. Pass `null` to skip (rare). */
  label?: ReactNode;
  /** Inline help text below the control. */
  help?: ReactNode;
  /** Error message — when present, the field renders in invalid state. */
  error?: ReactNode;
  /** Marks the label with an asterisk and sets `aria-required`. */
  required?: boolean;
  /** Optional explicit id — defaults to a generated useId(). */
  id?: string;
  className?: string;
  /** A single form control. Will be cloned with id + aria-* props. */
  children: ReactNode;
  /** Extra props for the label (e.g. className). */
  labelProps?: LabelHTMLAttributes<HTMLLabelElement>;
}

export function FormField({
  label,
  help,
  error,
  required = false,
  id,
  className,
  children,
  labelProps,
}: FormFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const helpId = help ? `${fieldId}-help` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const invalid = Boolean(error);

  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <FormFieldContext.Provider
      value={{ id: fieldId, helpId, errorId, invalid, required }}
    >
      <div className={cn("space-y-1.5", className)}>
        {label != null && (
          <Label htmlFor={fieldId} required={required} {...labelProps}>
            {label}
          </Label>
        )}
        <Slot
          id={fieldId}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          aria-required={required || undefined}
        >
          {children}
        </Slot>
        {help && !error && (
          <p id={helpId} className="text-xs text-muted-foreground">
            {help}
          </p>
        )}
        {error && (
          <p
            id={errorId}
            role="alert"
            className="text-xs font-medium text-destructive"
          >
            {error}
          </p>
        )}
      </div>
    </FormFieldContext.Provider>
  );
}

// Minimal Slot — clones the single child and merges aria props. We don't
// pull in `@radix-ui/react-slot` because the rest of the package avoids
// the dependency.
const Slot = forwardRef<HTMLElement, HTMLAttributes<HTMLElement> & { children: ReactNode }>(
  ({ children, ...props }, _ref) => {
    if (!children || typeof children !== "object" || !("props" in children)) {
      return <>{children}</>;
    }
    const child = children as React.ReactElement<Record<string, unknown>>;
    const merged: Record<string, unknown> = {
      ...props,
      ...child.props,
    };
    // Prefer the FormField-supplied id/aria over a child-supplied value,
    // since the form-field is the source of truth for wiring.
    if (props.id) merged.id = props.id;
    if (props["aria-describedby"]) merged["aria-describedby"] = props["aria-describedby"];
    if (props["aria-invalid"]) merged["aria-invalid"] = props["aria-invalid"];
    if (props["aria-required"]) merged["aria-required"] = props["aria-required"];
    return <child.type {...merged} />;
  },
);
Slot.displayName = "FormFieldSlot";

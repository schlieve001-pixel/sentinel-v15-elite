/**
 * Tooltip — CSS-positioned popover shown on hover/focus.
 * No dependencies beyond React. Keyboard-accessible (role=tooltip).
 *
 * Usage:
 *   <Tooltip content="GOLD: Math-confirmed overbid with provenance doc">
 *     <span className="grade-badge grade-gold">GOLD</span>
 *   </Tooltip>
 */
import React, { useState, useRef, useId } from "react";

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  position?: "top" | "bottom" | "left" | "right";
  maxWidth?: number;
}

export function Tooltip({ content, children, position = "top", maxWidth = 260 }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setVisible(true), 180);
  };
  const hide = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setVisible(false);
  };

  const posStyles: Record<string, React.CSSProperties> = {
    top:    { bottom: "calc(100% + 8px)", left: "50%", transform: "translateX(-50%)" },
    bottom: { top:    "calc(100% + 8px)", left: "50%", transform: "translateX(-50%)" },
    left:   { right:  "calc(100% + 8px)", top:  "50%", transform: "translateY(-50%)" },
    right:  { left:   "calc(100% + 8px)", top:  "50%", transform: "translateY(-50%)" },
  };

  const arrowStyles: Record<string, React.CSSProperties> = {
    top:    { bottom: -5, left: "50%", transform: "translateX(-50%)", borderColor: "#1e293b transparent transparent transparent", borderWidth: "5px 5px 0 5px" },
    bottom: { top:    -5, left: "50%", transform: "translateX(-50%)", borderColor: "transparent transparent #1e293b transparent", borderWidth: "0 5px 5px 5px" },
    left:   { right:  -5, top:  "50%", transform: "translateY(-50%)", borderColor: "transparent transparent transparent #1e293b", borderWidth: "5px 0 5px 5px" },
    right:  { left:   -5, top:  "50%", transform: "translateY(-50%)", borderColor: "transparent #1e293b transparent transparent", borderWidth: "5px 5px 5px 0" },
  };

  return (
    <span
      style={{ position: "relative", display: "inline-flex", alignItems: "center" }}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {React.cloneElement(children as React.ReactElement<React.HTMLAttributes<HTMLElement>>, {
        "aria-describedby": visible ? id : undefined,
      })}
      {visible && (
        <span
          id={id}
          role="tooltip"
          style={{
            position: "absolute",
            zIndex: 9999,
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: "0.72em",
            lineHeight: 1.5,
            color: "#cbd5e1",
            maxWidth,
            width: "max-content",
            pointerEvents: "none",
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
            letterSpacing: "0.01em",
            ...posStyles[position],
          }}
        >
          {content}
          <span style={{
            position: "absolute",
            width: 0,
            height: 0,
            borderStyle: "solid",
            ...arrowStyles[position],
          }} />
        </span>
      )}
    </span>
  );
}

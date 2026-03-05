import { useState, useEffect } from "react";

export type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

let _setToasts: React.Dispatch<React.SetStateAction<ToastItem[]>> | null = null;
let _nextId = 0;

export function toast(message: string, type: ToastType = "info") {
  if (!_setToasts) return;
  const id = ++_nextId;
  _setToasts((prev) => [...prev, { id, type, message }]);
  setTimeout(() => {
    _setToasts?.((prev) => prev.filter((t) => t.id !== id));
  }, 4500);
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    _setToasts = setToasts;
    return () => {
      _setToasts = null;
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast-${t.type}`}
          onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}

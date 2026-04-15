import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useReducer,
  useRef,
  useEffect,
} from "react";
import { ToastContainer } from "../components/Toast";

export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration?: number;
}

interface ToastContextValue {
  show: (message: string, type?: ToastType, duration?: number) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const MAX_VISIBLE = 3;
const DEFAULT_DURATION = 5000;

type Action =
  | { type: "ADD"; toast: Toast }
  | { type: "REMOVE"; id: string };

function toastReducer(state: Toast[], action: Action): Toast[] {
  switch (action.type) {
    case "ADD": {
      const next = [...state, action.toast];
      // Keep only the last MAX_VISIBLE toasts
      return next.length > MAX_VISIBLE ? next.slice(-MAX_VISIBLE) : next;
    }
    case "REMOVE":
      return state.filter((t) => t.id !== action.id);
    default:
      return state;
  }
}

let toastCounter = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, dispatch] = useReducer(toastReducer, []);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    dispatch({ type: "REMOVE", id });
  }, []);

  const show = useCallback(
    (message: string, type: ToastType = "info", duration?: number) => {
      const id = `toast-${++toastCounter}-${Date.now()}`;
      const toast: Toast = { id, message, type, duration };
      dispatch({ type: "ADD", toast });

      const ms = duration ?? DEFAULT_DURATION;
      const timer = setTimeout(() => {
        timersRef.current.delete(id);
        dispatch({ type: "REMOVE", id });
      }, ms);
      timersRef.current.set(id, timer);

      return id;
    },
    []
  );

  // Cleanup all timers on unmount
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const value = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

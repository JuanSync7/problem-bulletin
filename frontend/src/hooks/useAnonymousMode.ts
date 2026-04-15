import { useState, useCallback } from "react";

const STORAGE_KEY = "pb-anonymous";

function getStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function useAnonymousMode() {
  const [isAnonymous, setAnonymousState] = useState(getStored);

  const toggle = useCallback(() => {
    setAnonymousState((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, []);

  return { isAnonymous, toggle };
}

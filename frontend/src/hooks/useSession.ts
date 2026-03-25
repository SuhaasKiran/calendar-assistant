import { useContext } from "react";
import {
  SessionContext,
  type SessionContextValue,
} from "../context/SessionContext";

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within SessionProvider");
  }
  return ctx;
}

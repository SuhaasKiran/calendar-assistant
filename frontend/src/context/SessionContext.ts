import { createContext } from "react";
import type { User } from "../api/auth";

export type SessionContextValue = {
  user: User | null;
  loading: boolean;
  oauthBanner: string | null;
  clearOAuthBanner: () => void;
  refetch: () => Promise<void>;
  logout: () => Promise<void>;
};

export const SessionContext = createContext<SessionContextValue | null>(null);

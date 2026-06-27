import { create } from "zustand";

interface AuthState {
  token: string | null;
  userId: string | null;
  username: string | null;
  setAuth: (token: string, userId: string, username: string) => void;
  logout: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem("echosoul_token"),
  userId: localStorage.getItem("echosoul_userId"),
  username: localStorage.getItem("echosoul_username"),

  setAuth: (token, userId, username) => {
    localStorage.setItem("echosoul_token", token);
    localStorage.setItem("echosoul_userId", userId);
    localStorage.setItem("echosoul_username", username);
    set({ token, userId, username });
  },

  logout: () => {
    localStorage.removeItem("echosoul_token");
    localStorage.removeItem("echosoul_userId");
    localStorage.removeItem("echosoul_username");
    set({ token: null, userId: null, username: null });
  },

  isAuthenticated: () => !!get().token,
}));
